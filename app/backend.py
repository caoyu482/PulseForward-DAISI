"""Data access for the HealthPulse app (v2).

Deployed: reads Unity Catalog Gold tables through the SQL warehouse as the app's service principal
(Unity Catalog row filters decide which planning areas it may see).
Local testing: set HP_MOCK_DIR to a folder of parquet exports with the same schema.
"""
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

CATALOG = os.getenv("HP_CATALOG", "workspace")
TABLES = {
    "area_year": "healthpulse_gold.service_area_year",
    "priorities": "healthpulse_gold.service_priorities",
    "national": "healthpulse_gold.service_national_year",
    "facilities": "healthpulse_gold.facilities_v2",
    "meta": "healthpulse_gold.planning_area_meta",
    "backtest": "healthpulse_gold.model_backtest",
    "boundary": "healthpulse_gold.boundary_check",
    "prevention": "healthpulse_gold.prevention_impact",
    "services": "healthpulse_gold.services_ref",
    "presets": "healthpulse_gold.presets_ref",
    "allocation": "healthpulse_gold.allocation_check",
    "pop": "healthpulse_gold.population_forecast",
    "assumptions": "healthpulse_gold.assumptions",
    "geo": "healthpulse_silver.planning_area_geo",
    "dq": "healthpulse_silver.dq_results",
}
OPTIONAL = {"waits": "healthpulse_gold.polyclinic_waits", "origins": "healthpulse_gold.backtest_origins",
            "scen_check": "healthpulse_gold.scenario_check"}


def _mock(t):
    d = os.environ["HP_MOCK_DIR"]
    p = os.path.join(d, t.replace("healthpulse_", "").replace(".", "__") + ".parquet")
    return pd.read_parquet(p) if os.path.exists(p) else None


def _connect():
    from databricks import sql
    from databricks.sdk.core import Config
    cfg = Config()
    return sql.connect(server_hostname=cfg.host.replace("https://", ""),
                       http_path=f"/sql/1.0/warehouses/{os.environ['DATABRICKS_WAREHOUSE_ID']}",
                       credentials_provider=lambda: cfg.authenticate)


def load_all():
    if os.getenv("HP_MOCK_DIR"):
        out = {k: _mock(t) for k, t in TABLES.items()}
        out.update({k: _mock(t) for k, t in OPTIONAL.items()})
        return out
    out = {}
    with _connect() as conn:
        for k, t in {**TABLES, **OPTIONAL}.items():
            try:
                with conn.cursor() as c:
                    c.execute(f"SELECT * FROM {CATALOG}.{t}")
                    out[k] = c.fetchall_arrow().to_pandas()
            except Exception:
                if k in OPTIONAL:
                    out[k] = None
                else:
                    raise
    return out


# ------------------------------------------------------------------ planning decisions (write-back)
STATUSES = ["Not reviewed", "Capacity being verified", "Expansion under assessment", "Project planned", "No action needed"]
DECISIONS_TABLE = f"{CATALOG}.healthpulse_gold.planning_decisions"
DECISIONS_CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "decisions_cache.json"
DECISION_COLUMNS = ["pa_key", "service", "status", "owner", "note", "scenario_id", "reviewer", "created_at"]


def _read_local_decisions():
    if not DECISIONS_CACHE_PATH.exists():
        return []
    with DECISIONS_CACHE_PATH.open(encoding="utf-8") as cache:
        records = json.load(cache)
    if not isinstance(records, list) or not all(isinstance(record, dict) for record in records):
        raise ValueError(f"Invalid decisions cache format: {DECISIONS_CACHE_PATH}")
    return records


def _write_local_decision(record):
    DECISIONS_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    records = _read_local_decisions()
    records.append(record)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=DECISIONS_CACHE_PATH.parent,
                                        delete=False, suffix=".tmp") as cache:
            temp_path = Path(cache.name)
            json.dump(records, cache, ensure_ascii=False, indent=2)
            cache.flush()
            os.fsync(cache.fileno())
        os.replace(temp_path, DECISIONS_CACHE_PATH)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def load_reviews():
    try:
        with _connect() as conn, conn.cursor() as cursor:
            cursor.execute(f"SELECT {', '.join(DECISION_COLUMNS)} FROM {DECISIONS_TABLE} "
                           "ORDER BY created_at DESC LIMIT 2000")
            remote_records = [dict(zip(DECISION_COLUMNS, row)) for row in cursor.fetchall()]
        for record in remote_records:
            record["store"] = "databricks"
        store_status = "Databricks table and local decision cache"
        remote_available = True
    except Exception as error:
        remote_records = []
        store_status = f"Local decision cache (Databricks unavailable: {str(error)[:160]})"
        remote_available = False
    try:
        local_records = _read_local_decisions()
    except Exception as error:
        if not remote_available:
            raise RuntimeError(f"Databricks unavailable and local decision cache could not be read: {error}") from error
        local_records = []
        store_status += f" (local cache unavailable: {str(error)[:120]})"
    for record in local_records:
        record.setdefault("store", "local")
    decisions = pd.DataFrame(remote_records + local_records)
    decisions.attrs["store_status"] = store_status
    return decisions


def top5_decision_count(priorities, decisions):
    top5 = priorities[(priorities.scenario_id == "base|no_hsg") & (priorities["rank"] <= 5)][["pa_key", "service"]]
    if top5.empty or decisions is None or decisions.empty:
        return 0, len(top5)
    recorded = decisions[["pa_key", "service"]].drop_duplicates()
    return len(top5.merge(recorded, on=["pa_key", "service"])), len(top5)


def save_review(pa_key, service, status, owner, note, scenario_id, reviewer, confirmations=None):
    record = {
        "pa_key": pa_key,
        "service": service,
        "status": status,
        "owner": owner or None,
        "note": note or None,
        "confirmations": confirmations or [],
        "scenario_id": scenario_id,
        "reviewer": reviewer,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    parameters = tuple(record[column] for column in DECISION_COLUMNS)
    placeholders = ", ".join(["?"] * len(DECISION_COLUMNS))
    insert_sql = (f"INSERT INTO {DECISIONS_TABLE} ({', '.join(DECISION_COLUMNS)}) "
                  f"VALUES ({placeholders})")
    try:
        with _connect() as conn, conn.cursor() as cursor:
            cursor.execute(insert_sql, parameters)
        record["store"] = "databricks"
        return record
    except Exception as error:
        record["store"] = "local"
        record["storage_error"] = str(error)[:160]
        try:
            _write_local_decision(record)
        except Exception as local_error:
            raise RuntimeError(
                f"Databricks write failed ({str(error)[:120]}); local cache write failed ({str(local_error)[:120]})"
            ) from local_error
        return record
