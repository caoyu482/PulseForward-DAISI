# Databricks notebook source
# MAGIC %md
# MAGIC # 03 · Planning-area population forecast + backtest (MLflow)
# MAGIC Three candidate models per planning area x sex x 5-year age group, compared on a hold-out backtest:
# MAGIC
# MAGIC | Model | Idea |
# MAGIC |---|---|
# MAGIC | M1 linear trend | per-cell linear regression on the last 6 years |
# MAGIC | M2 damped growth | Holt-type time series: recent log-growth, damped each year |
# MAGIC | M3 cohort-component | each group ages 1/5 per year, survives by SingStat life tables, plus the area's own observed net in-movement |
# MAGIC
# MAGIC Backtest: train on 2011-2020 → forecast 2021-2025 → compare with observed. The winner drives the 2027-2031 forecast;
# MAGIC M3 mechanics provide the low / base / high ageing scenarios. All runs are logged to MLflow.

# COMMAND ----------

dbutils.widgets.text("catalog", "workspace")
C = dbutils.widgets.get("catalog")
S, G = f"{C}.healthpulse_silver", f"{C}.healthpulse_gold"

import os, sys, json
sys.path.append(os.path.abspath("../src"))
import importlib, hp_core as hc, hp_pipeline as hpp
importlib.reload(hc); importlib.reload(hpp)
import mlflow
import pandas as pd

a = hc.Assumptions()
pop = spark.table(f"{S}.population_pa_age_sex").toPandas()
lt = spark.table(f"{S}.life_tables").toPandas()

# COMMAND ----------

F = hpp.stage_forecast(pop, lt, a)
summary, best = F["backtest_summary"], F["best_model"]
pd.DataFrame(summary).T

# COMMAND ----------

user = spark.sql("SELECT current_user()").first()[0]
mlflow.set_experiment(f"/Users/{user}/healthpulse_population_forecast")
with mlflow.start_run(run_name="backtest_2021_2025") as parent:
    mlflow.log_params({"train_years": "2011-2020", "test_years": "2021-2025", "unit": "planning area x sex x 5-year age group",
                       "areas_scored": "areas with >=2,000 residents aged 65+"})
    for m, s in summary.items():
        with mlflow.start_run(run_name=m, nested=True):
            mlflow.log_param("model", m)
            mlflow.log_metrics(s)
    mlflow.log_param("selected_model", best)
    mlflow.log_metric("selected_mape_pop65", summary[best]["mape_pop65"])
    err = F["backtest_errors"]
    err_path = "/tmp/backtest_errors.csv"; err.to_csv(err_path, index=False); mlflow.log_artifact(err_path)
with mlflow.start_run(run_name="forecast_2027_2031"):
    mlflow.log_params({"model": best, "base_year": a.base_year, "horizon": f"{a.horizon[0]}-{a.horizon[-1]}",
                       "migration_window": "2022-2025 transitions (all MP2019 boundaries)", "life_table_year": 2025,
                       **{f"ageing_{k}": json.dumps(v) for k, v in a.ageing.items()}})
    fb = F["forecast_bands"]
    for ag in ["low", "base", "high"]:
        t = fb[(fb.ageing_scenario == ag) & (fb.year == a.horizon[-1])][["pop65", "pop75", "total"]].sum()
        mlflow.log_metrics({f"sg_pop65_2031_{ag}": float(t.pop65), f"sg_pop75_2031_{ag}": float(t.pop75)})
print("selected:", best)

# COMMAND ----------

def release_policies(full_name, mask_cols=()):
    """Row filters / masks block overwrites; drop them first (05_governance re-applies them)."""
    if not spark.catalog.tableExists(full_name):
        return
    try:
        spark.sql(f"ALTER TABLE {full_name} DROP ROW FILTER")
    except Exception:
        pass
    for c in mask_cols:
        try:
            spark.sql(f"ALTER TABLE {full_name} ALTER COLUMN {c} DROP MASK")
        except Exception:
            pass


def save(df, name, comment):
    release_policies(f"{G}.{name}")
    spark.createDataFrame(df).write.mode("overwrite").option("overwriteSchema", True).saveAsTable(f"{G}.{name}")
    spark.sql(f"COMMENT ON TABLE {G}.{name} IS '{comment}'")

fb = F["forecast_bands"].rename(columns={"pa": "pa_key"})
save(fb, "population_forecast",
     "Residents (total, 65+, 75+, 85+) by planning area and year: observed 2011-2026, forecast 2027-2031 for low / base / high ageing scenarios.")
cells = F["forecast_cells"].rename(columns={"pa": "pa_key"})
spark.createDataFrame(cells).write.mode("overwrite").option("overwriteSchema", True).saveAsTable(f"{S}.population_forecast_cells")
spark.sql(f"COMMENT ON TABLE {S}.population_forecast_cells IS 'Forecast population by planning area x sex x 5-year age group, 2026-2031, per ageing scenario (input to demand model).'")
pj = F["pop_jumps"].rename(columns={"pa": "pa_key"})
spark.createDataFrame(pj).write.mode("overwrite").option("overwriteSchema", True).saveAsTable(f"{S}.population_boundary_jumps")
bt = pd.DataFrame([{"model": m, **s, "selected": m == best} for m, s in summary.items()])
save(bt, "model_backtest", "Backtest of three population models (train 2011-2020, test 2021-2025); MAPE = mean absolute percentage error across planning areas with >=2,000 seniors.")
display(bt)

# COMMAND ----------

# Rolling-origin backtest (origins 2016-2020) and scenario-order check (slower <= base <= faster ageing, every area-year)
bo = F["backtest_origins"]
save(bo, "backtest_origins", "Rolling-origin backtest: each origin year trains on data up to that year and forecasts up to 5 years ahead; MAPE/MAE for residents 65+ in areas with >=2,000 seniors.")
so = F["scenario_order"].rename(columns={"pa": "pa_key"})
assert so.ordered.all(), f"ageing scenarios out of order in {int((~so.ordered).sum())} area-years"
save(so, "scenario_check", "Residents 65+ per area and forecast year under slower / base / faster ageing; ordered = slower <= base <= faster.")
with mlflow.start_run(run_name="backtest_rolling_origins"):
    for r in bo.itertuples():
        mlflow.log_metric(f"{r.model}_mape_pop65_origin_{r.origin}", r.mape_pop65)
    mlflow.log_metric("cohort_best_share_of_origins", float(bo[bo.model == "M3_cohort_component"].best_at_origin.mean()))
display(bo)
