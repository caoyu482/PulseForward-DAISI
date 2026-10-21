# Databricks notebook source
# MAGIC %md
# MAGIC # 02 · Silver transform + data-quality checks
# MAGIC Typed, documented, analysis-ready tables. Every check is written to `healthpulse_silver.dq_results`; a failed **critical** check stops the job.
# MAGIC
# MAGIC Messy-data handling made explicit here:
# MAGIC - planning-area names normalised to one key (`pa_key`, upper case) across SingStat, URA and AIC sources
# MAGIC - placeholder / out-of-country coordinates rejected by a Singapore bounding-box rule
# MAGIC - missing 2025 age-sex rates kept as NULL (not 0); the model treats them as "no admissions recorded" only for ages < 15
# MAGIC - data.gov.sg wide month columns (e.g. `2005Dec`) unpivoted to a long monthly series; "na" → NULL

# COMMAND ----------

dbutils.widgets.text("catalog", "workspace")
C = dbutils.widgets.get("catalog")
B, S = f"{C}.healthpulse_bronze", f"{C}.healthpulse_silver"

import pandas as pd
from datetime import datetime

dq = []
def check(name, table, value, ok, critical=True):
    dq.append({"check": name, "table": table, "value": str(value), "passed": bool(ok), "critical": critical,
               "checked_at": datetime.utcnow()})

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


def ctas(name, comment, sql):
    spark.sql(f"CREATE OR REPLACE TABLE {S}.{name} COMMENT '{comment}' AS {sql}")
    return spark.table(f"{S}.{name}")

# COMMAND ----------

# MAGIC %md ## Population

# COMMAND ----------

pop = ctas("population_pa_age_sex",
    "Resident population by planning area x 5-year age group x sex, June 2011-2026 (SingStat; rounded to nearest 10; MP2014 boundaries 2011-19, MP2019 2020-25, MP2025 2026).",
    f"""SELECT CAST(year AS INT) year, trim(planning_area) planning_area, upper(trim(planning_area)) pa_key,
               age_group, CAST(age_lower AS INT) age_lower, lower(sex) sex,
               CAST(population_rounded AS INT) population, boundary_version
        FROM {B}.population__population_planning_area_5year_age_sex_2011_2026""")
r = spark.sql(f"SELECT count(DISTINCT pa_key) n_pa, min(year) y0, max(year) y1, sum(CASE WHEN population<0 THEN 1 ELSE 0 END) neg, sum(CASE WHEN population IS NULL THEN 1 ELSE 0 END) nul FROM {S}.population_pa_age_sex").first()
check("55 planning areas", "population_pa_age_sex", r.n_pa, r.n_pa == 55)
check("years 2011-2026", "population_pa_age_sex", f"{r.y0}-{r.y1}", (r.y0, r.y1) == (2011, 2026))
check("no negative population", "population_pa_age_sex", r.neg, r.neg == 0)
check("no null population", "population_pa_age_sex", r.nul, r.nul == 0)

release_policies(f"{S}.population_subzone_ageband", ["pop_65_74", "pop_75_84", "pop_85plus"])
ctas("population_subzone_ageband",
    "Residents by MP2019 subzone and senior age band, 2020-2026 (derived from SingStat single-age subzone table). Used to place demand inside planning areas for 2SFCA.",
    f"""SELECT CAST(year AS INT) year, boundary_version, upper(trim(planning_area)) pa_key, trim(planning_area) planning_area,
               upper(trim(subzone)) subzone, CAST(pop_0_64 AS INT) pop_0_64, CAST(pop_65_74 AS INT) pop_65_74,
               CAST(pop_75_84 AS INT) pop_75_84, CAST(pop_85plus AS INT) pop_85plus
        FROM {B}.population__population_subzone_ageband_2020_2026""")

# COMMAND ----------

# MAGIC %md ## Health service rates, mortality, national capacity

# COMMAND ----------

ctas("life_tables",
    "Complete life tables for Singapore residents by single year of age and sex, 2003-2025 (SingStat). qx = probability of dying within one year.",
    f"""SELECT CAST(reference_year AS INT) reference_year, lower(sex) sex, CAST(age_x AS INT) age_x,
               CAST(qx AS DOUBLE) qx, CAST(lx AS DOUBLE) lx, CAST(ex AS DOUBLE) ex
        FROM {B}.healthcare__resident_life_tables_2003_2025_analysis WHERE lower(sex) IN ('male','female')""")
r = spark.sql(f"SELECT min(qx) a, max(qx) b, count(DISTINCT reference_year) n FROM {S}.life_tables").first()
check("qx within [0,1]", "life_tables", f"{r.a}-{r.b}", 0 <= r.a and r.b <= 1)

ctas("hospital_age_sex_rates",
    "MOH inpatient discharge rates per 1,000 residents by 5-year age group, sex and hospital type, 2024-2025 (2025 preliminary). National rates - no planning-area detail exists.",
    f"""SELECT CAST(rate_year AS INT) rate_year, hospital_type, lower(sex) sex, age_group, CAST(age_lower AS INT) age_lower,
               CAST(rate_per_1000_residents AS DOUBLE) rate_per_1000_residents, CAST(preliminary AS BOOLEAN) preliminary, source_url
        FROM {B}.healthcare__hospital_age_sex_rates_five_year_analysis""")
r = spark.sql(f"SELECT count(*) n FROM {S}.hospital_age_sex_rates WHERE rate_year=2025 AND hospital_type='Community Hospital' AND age_lower>=65 AND rate_per_1000_residents IS NULL").first()
check("2025 community-hospital 65+ rates complete", "hospital_age_sex_rates", r.n, r.n == 0)
r = spark.sql(f"SELECT count(*) n FROM {S}.hospital_age_sex_rates WHERE rate_per_1000_residents IS NULL").first()
check("missing rates kept as NULL (not zero)", "hospital_age_sex_rates", r.n, True, critical=False)

ctas("national_capacity",
    "National beds (by institution type) and admissions/attendances per year, Singapore (MOH via data.gov.sg).",
    f"""SELECT CAST(year AS INT) year, series_path, CAST(value AS DOUBLE) value, unit, 'beds' AS measure FROM {B}.healthcare__beds_annual_long
        UNION ALL
        SELECT CAST(year AS INT), series_path, CAST(value AS DOUBLE), unit, 'activity' FROM {B}.healthcare__hospital_annual_long""")
r = spark.sql(f"SELECT max(CASE WHEN series_path='Nursing Homes' AND year=2025 THEN value END) nh, max(CASE WHEN series_path='Community Hospitals' AND year=2025 THEN value END) ch FROM {S}.national_capacity WHERE measure='beds'").first()
check("2025 national nursing-home and community-hospital beds present", "national_capacity", f"NH {r.nh}, CH {r.ch}", r.nh and r.ch)

# COMMAND ----------

# MAGIC %md ## data.gov.sg API series → long monthly table

# COMMAND ----------

w = spark.table(f"{B}.datagov__hospital_admissions_monthly").toPandas()
months = [c for c in w.columns if len(c) == 7 and c[:4].isdigit()]
lg = w.melt(id_vars=["DataSeries"], value_vars=months, var_name="period", value_name="raw")
lg["month"] = pd.to_datetime(lg.period, format="%Y%b")
lg["value"] = pd.to_numeric(lg.raw.str.replace(",", ""), errors="coerce")
lg = lg.rename(columns={"DataSeries": "series"})[["series", "month", "value"]].sort_values(["series", "month"])
spark.createDataFrame(lg).write.mode("overwrite").option("overwriteSchema", True).saveAsTable(f"{S}.hospital_activity_monthly")
spark.sql(f"COMMENT ON TABLE {S}.hospital_activity_monthly IS 'Monthly hospital admissions and attendances by series (MOH via data.gov.sg datastore API, ingested live).'")
check("API monthly series parsed", "hospital_activity_monthly", len(lg), len(lg) > 1000)

# COMMAND ----------

# MAGIC %md ## Facilities (existing + planned) and geography

# COMMAND ----------

BBOX = "latitude BETWEEN 1.15 AND 1.48 AND longitude BETWEEN 103.6 AND 104.1"
def fac(tbl, line, extra=""):
    return f"""SELECT CAST(facility_id AS STRING) facility_id, name, facility_type, CAST(subcategory AS STRING) subcategory,
               CAST(latitude AS DOUBLE) latitude, CAST(longitude AS DOUBLE) longitude, upper(planning_area_mp2019) pa_key,
               '{line}' AS service_line {extra}
               FROM {B}.supply__{tbl} WHERE {BBOX}"""

ctas("supply_polyclinics", "28 polyclinics with cluster (NHG/NUHS/SingHealth) and planning area: 26 from the supply package plus Serangoon (opened Nov 2025) and Tengah, added because they appear in MOH waiting-time data (Aug 2026).",
     fac("supply_polyclinics", "primary", ", cluster") + " UNION ALL " + fac("supply_polyclinics_additions_2026", "primary", ", cluster"))
ctas("supply_community_hospitals", "10 community hospitals with published beds where available.",
     fac("supply_community_hospitals", "intermediate", ", CAST(beds_reported AS DOUBLE) beds_reported, CAST(beds_period AS STRING) beds_period, CAST(beds_source AS STRING) beds_source"))
ctas("supply_nursing_homes", "94 nursing homes (AIC); beds published for only 3 - others estimated downstream and flagged.",
     fac("supply_nursing_homes", "longterm", ", CAST(beds_reported AS DOUBLE) beds_reported"))
ctas("facility_points",
    "All mapped community care points (existing): polyclinics, community hospitals, nursing homes, active ageing centres, day care / rehab / centre-based nursing, CHAS clinics (2021 snapshot).",
    " UNION ALL ".join([
        fac("supply_polyclinics", "primary"), fac("supply_community_hospitals", "intermediate"), fac("supply_nursing_homes", "longterm"),
        fac("supply_active_ageing_centres", "context"), fac("supply_other_community_care", "context"), fac("supply_chas_clinics", "context")]))
ctas("planned_facilities",
    "31 MOH-announced upcoming projects (as of 2026-03) with geocode quality; capacity and year often not announced.",
    f"""SELECT CAST(facility_id AS STRING) facility_id, project_name, service_type, CAST(target_year AS DOUBLE) target_year,
               CAST(phase_start_year AS DOUBLE) phase_start_year, CAST(reported_capacity_beds AS DOUBLE) reported_capacity_beds,
               CAST(latitude AS DOUBLE) latitude, CAST(longitude AS DOUBLE) longitude, upper(planning_area_mp2019) planning_area_mp2019,
               geocode_quality, timing_text, status
        FROM {B}.supply__supply_planned_facilities_geocoded""")
for tbl, n in [("supply_polyclinics", 28), ("supply_community_hospitals", 10), ("supply_nursing_homes", 94)]:
    got = spark.table(f"{S}.{tbl}").count()
    check(f"{tbl}: expected {n} valid-coordinate rows", tbl, got, got == n)
bad = spark.sql(f"SELECT count(*) n FROM {B}.supply__supply_chas_clinics WHERE NOT ({BBOX}) OR latitude IS NULL").first().n
check("CHAS clinics rejected by Singapore bounding box", "facility_points", bad, True, critical=False)

ctas("planning_area_geo", "URA Master Plan 2019 planning-area boundaries (GeoJSON geometry as text).",
     f"SELECT upper(planning_area) pa_key, initcap(planning_area) planning_area, region, geometry_json FROM {B}.geography__ura_mp2019_planning_areas")
ctas("subzone_geo", "URA Master Plan 2019 subzone boundaries (GeoJSON geometry as text).",
     f"SELECT upper(subzone) subzone, upper(planning_area) pa_key, region, geometry_json FROM {B}.geography__ura_mp2019_subzones")
n_pa = spark.table(f"{S}.planning_area_geo").count(); n_sz = spark.table(f"{S}.subzone_geo").count()
check("55 planning-area polygons", "planning_area_geo", n_pa, n_pa == 55)
check("332 subzone polygons", "subzone_geo", n_sz, n_sz == 332)
miss = spark.sql(f"SELECT count(DISTINCT p.subzone) n FROM {S}.population_subzone_ageband p LEFT ANTI JOIN {S}.subzone_geo g ON p.subzone=g.subzone WHERE p.year=2025").first().n
check("every 2025 population subzone has a polygon", "subzone_geo", miss, miss == 0)


# COMMAND ----------

# MAGIC %md ## v2 inputs: national day places, all community care centres, CHAS GPs, boundary overlap

# COMMAND ----------

ctas("national_capacity_moh",
    "MOH beds in inpatient facilities and places in non-residential long-term care (day places, home care places), Singapore, 2006-2025 (2026 release).",
    f"""SELECT service, ownership, CAST(year AS INT) year, CAST(value AS DOUBLE) value, unit, status, source_url
        FROM {B}.healthcare__moh_national_capacity_2006_2025""")
r = spark.sql(f"SELECT max(CASE WHEN service='Total No. of Day Places' THEN value END) dp, max(CASE WHEN service='Nursing Homes' THEN value END) nh FROM {S}.national_capacity_moh WHERE ownership='Total' AND year=2025").first()
check("2025 day places and nursing-home beds present (MOH 2026 release)", "national_capacity_moh", f"day {r.dp}, NH {r.nh}", r.dp and r.nh)

ctas("supply_other_community_care", "Day care, community rehabilitation, centre-based nursing, respite and Silver Generation Office points (AIC directory).",
     fac("supply_other_community_care", "context"))
ctas("supply_chas_clinics", "CHAS GP and dental clinics (MOH, 2021 snapshot) with licence type; GP clinics (MC) count as subsidised primary care access points.",
     fac("supply_chas_clinics", "context", ", licence_type"))
n_c = spark.table(f"{S}.supply_other_community_care").count()
check("day care / rehab / nursing centres with valid coordinates", "supply_other_community_care", n_c, n_c > 400)

ctas("planning_area_boundary_overlap",
    "Share of each planning area that stays the same between URA Master Plan versions (intersection over union, SVY21 projection). Below 0.98 = real boundary change.",
    f"SELECT upper(pa) pa_key, change, CAST(iou AS DOUBLE) iou, CAST(area_old_km2 AS DOUBLE) area_old_km2, CAST(area_new_km2 AS DOUBLE) area_new_km2 FROM {B}.geography__planning_area_boundary_overlap")
r = spark.sql(f"SELECT sum(CASE WHEN iou >= 0.98 THEN 1 ELSE 0 END) same, count(*) n FROM {S}.planning_area_boundary_overlap").first()
check("planning areas with >=98% unchanged boundary (both MP changes)", "planning_area_boundary_overlap", f"{r.same}/{r.n}", True, critical=False)


ctas("polyclinic_waiting_times",
    "MOH median (P50) and 95th-percentile (P95) waiting times in minutes for registration and consultation at each polyclinic, August 2026.",
    f"""SELECT trim(polyclinic) polyclinic, CAST(reg_p50_min AS DOUBLE) reg_p50_min, CAST(consult_p50_min AS DOUBLE) consult_p50_min,
               CAST(reg_p95_min AS DOUBLE) reg_p95_min, CAST(consult_p95_min AS DOUBLE) consult_p95_min, month, source_url
        FROM {B}.healthcare__polyclinic_waiting_times_2026_08""")
miss = spark.sql(f"SELECT count(*) n FROM {S}.polyclinic_waiting_times w LEFT ANTI JOIN {S}.supply_polyclinics p ON w.polyclinic = p.name").first().n
check("every polyclinic in MOH waiting-time list is on the map", "polyclinic_waiting_times", miss, miss == 0)

# COMMAND ----------

res = pd.DataFrame(dq)
spark.createDataFrame(res).write.mode("overwrite").option("overwriteSchema", True).saveAsTable(f"{S}.dq_results")
display(res)
failed = res[(~res.passed) & (res.critical)]
assert failed.empty, f"Critical data-quality checks failed: {failed.check.tolist()}"
