"""Data access for the HealthPulse app (v2).

Deployed: reads Unity Catalog Gold tables through the SQL warehouse as the app's service principal
(Unity Catalog row filters decide which planning areas it may see).
Local testing: set HP_MOCK_DIR to a folder of parquet exports with the same schema.
"""
import os
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
# Deployed: Lakebase Postgres (the App's "postgres" resource injects PGHOST / PGDATABASE / PGUSER / LAKEBASE_ENDPOINT).
# Local testing: a SQLite file next to the mock data. The table is append-only, so every decision keeps its history.
REVIEW_SCHEMA = "healthpulse_app"
STATUSES = ["Not reviewed", "Capacity being verified", "Expansion under assessment", "Project planned", "No action needed"]
_DDL = """CREATE TABLE IF NOT EXISTS {t} (
  id {pk}, pa_key TEXT NOT NULL, service TEXT NOT NULL, status TEXT NOT NULL, owner TEXT, note TEXT,
  scenario_id TEXT, reviewer TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"""


def reviews_mode():
    if os.getenv("PGHOST") and os.getenv("LAKEBASE_ENDPOINT"):
        return "lakebase"
    if os.getenv("HP_MOCK_DIR"):
        return "sqlite"
    return None


def _pg():
    import psycopg
    from databricks.sdk import WorkspaceClient
    tok = WorkspaceClient().postgres.generate_database_credential(endpoint=os.environ["LAKEBASE_ENDPOINT"]).token
    conn = psycopg.connect(host=os.environ["PGHOST"], port=int(os.getenv("PGPORT", "5432")), dbname=os.environ["PGDATABASE"],
                           user=os.environ["PGUSER"], password=tok, sslmode="require", autocommit=True)
    with conn.cursor() as c:
        c.execute(f"CREATE SCHEMA IF NOT EXISTS {REVIEW_SCHEMA}")
        c.execute(_DDL.format(t=f"{REVIEW_SCHEMA}.area_reviews", pk="BIGSERIAL PRIMARY KEY"))
    return conn


def _sqlite():
    import sqlite3
    conn = sqlite3.connect(os.path.join(os.environ["HP_MOCK_DIR"], "area_reviews.sqlite"))
    conn.execute(_DDL.format(t="area_reviews", pk="INTEGER PRIMARY KEY AUTOINCREMENT"))
    return conn


def load_reviews():
    mode = reviews_mode()
    cols = ["id", "pa_key", "service", "status", "owner", "note", "scenario_id", "reviewer", "created_at"]
    if mode is None:
        return pd.DataFrame(columns=cols)
    if mode == "lakebase":
        with _pg() as conn, conn.cursor() as c:
            c.execute(f"SELECT {', '.join(cols)} FROM {REVIEW_SCHEMA}.area_reviews ORDER BY created_at DESC LIMIT 2000")
            return pd.DataFrame(c.fetchall(), columns=cols)
    with _sqlite() as conn:
        return pd.read_sql(f"SELECT {', '.join(cols)} FROM area_reviews ORDER BY created_at DESC, id DESC LIMIT 2000", conn)


def save_review(pa_key, service, status, owner, note, scenario_id, reviewer):
    vals = (pa_key, service, status, owner or None, note or None, scenario_id, reviewer)
    sql = "INSERT INTO {t} (pa_key, service, status, owner, note, scenario_id, reviewer) VALUES ({p})"
    if reviews_mode() == "lakebase":
        with _pg() as conn, conn.cursor() as c:
            c.execute(sql.format(t=f"{REVIEW_SCHEMA}.area_reviews", p=", ".join(["%s"] * 7)), vals)
    else:
        with _sqlite() as conn:
            conn.execute(sql.format(t="area_reviews", p=", ".join(["?"] * 7)), vals)
