# Databricks notebook source
# MAGIC %md
# MAGIC # 04 · Service planning: need, capacity, gaps and priorities (v2)
# MAGIC Each service keeps its own unit — nothing is added across services.
# MAGIC
# MAGIC | Service | Need | Capacity |
# MAGIC |---|---|---|
# MAGIC | Community hospitals | expected admissions (MOH 2025 age-sex rates) × national beds per admission | 10 hospitals (8 publish beds) |
# MAGIC | Nursing homes | residents 75+ × national beds per 75+ | 94 homes (3 publish beds; others share the national total) |
# MAGIC | Day care & rehab | residents 75+ × national day places per 75+ | 387 centres share the national day places |
# MAGIC | Primary care | **coverage**: seniors 65+ living > 1 km from a polyclinic or CHAS GP | locations only |
# MAGIC
# MAGIC "National per ..." = today's (2026) level of provision. Capacity is shared with a two-step floating catchment;
# MAGIC shares add back exactly to national capacity (checked below). Three scenario presets × prevention on/off.
# MAGIC Top 5 robustness: across presets, and over 200 random draws of the estimated capacities.

# COMMAND ----------

dbutils.widgets.text("catalog", "workspace")
C = dbutils.widgets.get("catalog")
S, G = f"{C}.healthpulse_silver", f"{C}.healthpulse_gold"

import os, sys, json
sys.path.append(os.path.abspath("../src"))
import importlib, hp_core as hc, hp_services as hs, hp_pipeline as hpp
for m in (hc, hs, hpp):
    importlib.reload(m)
import pandas as pd
import mlflow

a = hc.Assumptions()
T = lambda t: spark.table(f"{S}.{t}").toPandas()

cells = T("population_forecast_cells")
cubes = {ag: g.pivot_table(index=["pa_key", "sex", "age_group"], columns="year", values="population", aggfunc="sum")
              .rename_axis(index=["pa", "sex", "age_group"]) for ag, g in cells.groupby("ageing_scenario")}

def fc(rows):
    return {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": json.loads(r["geometry_json"]), "properties": r} for r in rows]}

pa_geo = fc([{"planning_area": r.pa_key, "region": r.region, "geometry_json": r.geometry_json} for r in T("planning_area_geo").itertuples()])
sz_geo = fc([{"subzone": r.subzone, "planning_area": r.pa_key, "geometry_json": r.geometry_json} for r in T("subzone_geo").itertuples()])
ren = lambda d: d.rename(columns={"pa_key": "planning_area_mp2019"})
poly, ch, nh = ren(T("supply_polyclinics")), ren(T("supply_community_hospitals")), ren(T("supply_nursing_homes"))
other, chas = ren(T("supply_other_community_care")), ren(T("supply_chas_clinics"))
planned = T("planned_facilities")
rates = T("hospital_age_sex_rates")
natcap = T("national_capacity_moh")
subzone_pop = T("population_subzone_ageband")

# COMMAND ----------

V = hpp.stage_v2(cubes, rates, natcap, poly, ch, nh, other, planned, subzone_pop, sz_geo, pa_geo, a, mc_draws=200, chas=chas)
display(V["conservation"])
assert (V["conservation"].difference_pct.abs() < 0.01).all(), "2SFCA allocation does not add back to national capacity"

# COMMAND ----------

# forecast outputs needed by the Gold builder
fb = spark.table(f"{G}.population_forecast").toPandas().rename(columns={"pa_key": "pa"})
if "planning_area" in fb.columns:
    fb = fb.drop(columns=["planning_area"])
bt = spark.table(f"{G}.model_backtest").toPandas()
F = {"best_model": bt.loc[bt.selected.astype(str).str.lower() == "true", "model"].iloc[0],
     "backtest_summary": {r["model"]: {k: r[k] for k in bt.columns if k not in ("model", "selected")} for _, r in bt.iterrows()},
     "pop_jumps": spark.table(f"{S}.population_boundary_jumps").toPandas().rename(columns={"pa_key": "pa"}),
     "forecast_bands": fb}
iou = T("planning_area_boundary_overlap").rename(columns={"pa_key": "pa"})
names = T("planning_area_geo").set_index("pa_key").planning_area
GOLD = hpp.build_gold_v2(F, V, names, iou, a, waits=T("polyclinic_waiting_times"))

# COMMAND ----------

def release_policies(full_name):
    if spark.catalog.tableExists(full_name):
        try:
            spark.sql(f"ALTER TABLE {full_name} DROP ROW FILTER")
        except Exception:
            pass

COMMENTS = {
    "service_area_year": "Need, reachable capacity and gap per planning area, service, year (2026-2031) and scenario. Units: beds (community hospital, nursing home), places (day care), seniors living far from care (primary).",
    "service_priorities": "Per-service ranking of planning areas: gap now (2026) and by 2031, top-5 robustness across scenarios and capacity estimates, and the recommended next step.",
    "service_national_year": "Singapore totals per service, year and scenario: need, capacity and national gap.",
    "facilities_v2": "Facilities used in the model, existing and announced, with capacity basis and whether they count in each scenario.",
    "planning_area_meta": "Planning area region, centre point and serving healthcare cluster (cluster of nearest polyclinic).",
    "model_backtest": "Population model backtest (train 2011-2020, test 2021-2025): MAE and MAPE for residents 65+ in areas with >=2,000 seniors.",
    "boundary_check": "Boundary-change check per planning area: overlap between Master Plan versions and unusual 65+ jumps at the change year.",
    "prevention_impact": "Need avoided in 2031 if prevention lowers 65+ use by 10% (illustrative assumption, not an official target).",
    "services_ref": "Service definitions, units, reach and data-confidence labels.",
    "presets_ref": "The three scenario presets shown to users.",
    "allocation_check": "Check that capacity shared across areas adds back exactly to national capacity (no double counting).",
    "population_forecast": "Residents (total, 65+, 75+, 85+) by planning area and year: observed 2011-2026, forecast 2027-2031 (low / base / high ageing).",
    "assumptions": "Every assumption in plain language. Items marked ASSUMPTION are not official figures.",
    "polyclinic_waits": "MOH polyclinic waiting times (August 2026): median and 95th-percentile minutes to register and to see a doctor, with location, planning area and cluster.",
}
for name, df in GOLD.items():
    d = df.copy()
    for c in d.columns:
        if d[c].dtype == object:
            d[c] = d[c].astype(object).where(d[c].notna(), None).map(lambda v: v if v is None else str(v))
    release_policies(f"{G}.{name}")
    spark.createDataFrame(d).write.mode("overwrite").option("overwriteSchema", True).saveAsTable(f"{G}.{name}")
    spark.sql(f"COMMENT ON TABLE {G}.{name} IS '{COMMENTS.get(name, '').replace(chr(39), '')}'")
    print(name, d.shape)

# v1 tables replaced by the per-service model
for old in ["gap_by_area_line_year", "demand_by_area_year", "priority_tiers_2031", "facilities_supply", "fan_chart_series",
            "headline_impact", "service_benchmarks", "scenarios"]:
    spark.sql(f"DROP TABLE IF EXISTS {G}.{old}")

# COMMAND ----------

# log the robustness results next to the forecast runs
user = spark.sql("SELECT current_user()").first()[0]
mlflow.set_experiment(f"/Users/{user}/healthpulse_population_forecast")
pr = GOLD["service_priorities"]
with mlflow.start_run(run_name="service_priorities_2031"):
    mlflow.log_params({"capacity_draws": 200, "capacity_noise_sd_log": 0.35, "scenarios": "optimistic/base/pessimistic x prevention"})
    base = pr[(pr.scenario_id == "base|no_hsg") & (pr.top5.astype(str).str.lower() == "true")]
    for sv, g in base.groupby("service"):
        mlflow.log_metric(f"{sv}_top5_mean_stability", float(pd.to_numeric(g.stability_share).mean()))
        mlflow.log_metric(f"{sv}_top5_all_presets", float((pd.to_numeric(g.presets_in_top5) >= 3).mean()))
display(base)
