# Databricks notebook source
# MAGIC %md
# MAGIC # 05 · Unity Catalog governance
# MAGIC Health planning data is aggregated open data, but the *design* must be safe to extend to MOH's own records. This task (re)applies, idempotently:
# MAGIC 1. **Sensitivity tags** on every HealthPulse table (`sensitivity`, `layer`, `domain`)
# MAGIC 2. **Row filter by healthcare cluster** — a planner entitled to `NUHS` sees only NUHS-served planning areas in every Gold table (entitlements table, not hard-coded users)
# MAGIC 3. **Small-cell column mask** — subzone senior counts below 20 are hidden unless the caller is entitled to see small cells (re-identification risk)
# MAGIC 4. **Column comments** so Genie and humans read the same definitions
# MAGIC
# MAGIC Lineage from Volume files → Bronze → Silver → Gold is captured automatically by Unity Catalog.

# COMMAND ----------

dbutils.widgets.text("catalog", "workspace")
dbutils.widgets.text("app_principal", "")  # Databricks App service principal (application id), added once the app exists
C = dbutils.widgets.get("catalog")
APP_SP = dbutils.widgets.get("app_principal").strip()
S, G, B = f"{C}.healthpulse_silver", f"{C}.healthpulse_gold", f"{C}.healthpulse_bronze"
OWNER = spark.sql("SELECT current_user()").first()[0]

# COMMAND ----------

# MAGIC %md ## 1. Entitlements table

# COMMAND ----------

spark.sql(f"""CREATE TABLE IF NOT EXISTS {S}.planner_entitlements (
  principal STRING COMMENT 'User email or service-principal application id',
  cluster STRING COMMENT 'ALL, NHG, NUHS or SingHealth',
  can_see_small_cells BOOLEAN COMMENT 'May see subzone counts below 20')
COMMENT 'Who may see which healthcare cluster (row filter) and small cells (column mask). Edit this table to change access - no code change needed.'""")
rows = [(OWNER, "ALL", True)] + ([(APP_SP, "ALL", False)] if APP_SP else [])
for p, c, sc in rows:
    spark.sql(f"""MERGE INTO {S}.planner_entitlements t USING (SELECT '{p}' principal, '{c}' cluster, {sc} can_see_small_cells) s
                  ON t.principal = s.principal WHEN NOT MATCHED THEN INSERT *""")
display(spark.table(f"{S}.planner_entitlements"))

# COMMAND ----------

# MAGIC %md ## 2. Row filter by cluster on Gold

# COMMAND ----------

spark.sql(f"""CREATE OR REPLACE FUNCTION {S}.cluster_row_filter(pa STRING)
RETURNS BOOLEAN
COMMENT 'Row filter: workspace admins see every area; other callers see a planning area if entitled to ALL or to the cluster serving it.'
RETURN is_member('admins') OR EXISTS (
  SELECT 1 FROM {S}.planner_entitlements e
  LEFT JOIN {G}.planning_area_meta m ON m.pa_key = pa
  WHERE e.principal = current_user() AND (e.cluster = 'ALL' OR e.cluster = m.cluster))""")

FILTERED = ["service_area_year", "service_priorities", "population_forecast", "facilities_v2", "boundary_check"]
for t in FILTERED:
    spark.sql(f"ALTER TABLE {G}.{t} SET ROW FILTER {S}.cluster_row_filter ON (pa_key)")

# COMMAND ----------

# MAGIC %md ## 3. Small-cell mask on subzone population

# COMMAND ----------

spark.sql(f"""CREATE OR REPLACE FUNCTION {S}.small_cell_mask(v INT)
RETURNS INT
COMMENT 'Column mask: hide counts below 20 unless the caller may see small cells.'
RETURN CASE WHEN v IS NULL OR v >= 20 THEN v
            WHEN is_member('admins') THEN v
            WHEN EXISTS (SELECT 1 FROM {S}.planner_entitlements e WHERE e.principal = current_user() AND e.can_see_small_cells) THEN v
            ELSE NULL END""")
for col in ["pop_65_74", "pop_75_84", "pop_85plus"]:
    spark.sql(f"ALTER TABLE {S}.population_subzone_ageband ALTER COLUMN {col} SET MASK {S}.small_cell_mask")

# COMMAND ----------

# MAGIC %md ## 4. Tags and column comments

# COMMAND ----------

def tag(schema, sensitivity, layer):
    for r in spark.sql(f"SHOW TABLES IN {schema}").collect():
        try:
            spark.sql(f"ALTER TABLE {schema}.{r.tableName} SET TAGS ('sensitivity' = '{sensitivity}', 'layer' = '{layer}', 'domain' = 'community_care_planning')")
        except Exception as e:
            print("tag skipped", r.tableName, str(e)[:120])

tag(B, "public_open_data", "bronze")
tag(S, "internal_aggregate", "silver")
tag(G, "internal_planning", "gold")
spark.sql(f"ALTER TABLE {S}.population_subzone_ageband SET TAGS ('sensitivity' = 'small_cell_risk')")
spark.sql(f"ALTER TABLE {S}.planner_entitlements SET TAGS ('sensitivity' = 'access_control')")

COMMENTS = {
    "service_priorities": {
        "service": "community_hospital, nursing_home, day_care or primary",
        "scenario_id": "preset|prevention, e.g. base|no_hsg is the base case; presets optimistic, base, pessimistic; hsg = prevention targets met (illustrative)",
        "rank": "Rank within the service for 2031 (1 = largest gap)",
        "gap_2026": "Gap today (2026) in the service unit: beds, places, or seniors living far from care for primary",
        "gap_2031": "Gap in 2031 in the service unit",
        "need_2031": "Beds or places needed in 2031 to keep today's Singapore level of care",
        "capacity_2031": "Share of nearby capacity reachable by the area's residents in 2031",
        "gap_start": "First year the gap is at least 5 beds or places",
        "presets_in_top5": "Number of the 3 scenario presets (prevention off) in which the area is in the top 5",
        "stability_share": "Share of 200 random capacity draws (or 3 distance thresholds for primary care) in which the area stays top 5",
        "next_step": "Suggested next step: Assess expansion, Verify current capacity, Verify capacity then assess, Check planned capacity & timing, Study primary care access, Monitor",
        "confidence": "Data confidence label for the service",
        "cluster": "Regional health cluster serving the area",
    },
    "service_area_year": {
        "need": "Beds or places needed to keep today's Singapore level of care (null for primary care)",
        "capacity": "Reachable share of nearby capacity (two-step floating catchment)",
        "gap": "Need minus capacity, floored at 0; for primary care: residents 65+ living > 1 km from a polyclinic or CHAS GP",
        "seniors_far": "Day care only: residents 75+ living > 2 km from a day care / rehab centre",
        "preset": "optimistic, base or pessimistic", "hsg": "True = prevention targets met (illustrative -10% use by 2031)",
    },
}
for t, cols in COMMENTS.items():
    for c, txt in cols.items():
        spark.sql(f"ALTER TABLE {G}.{t} ALTER COLUMN {c} COMMENT '{txt.replace(chr(39), chr(92) + chr(39))}'")
print("governance applied")
