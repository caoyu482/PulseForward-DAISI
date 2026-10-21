SCN = """CASE split(scenario_id, '[|]')[0] WHEN 'optimistic' THEN 'Optimistic' WHEN 'base' THEN 'Base' ELSE 'Pessimistic' END AS scenario,
  CASE WHEN scenario_id LIKE '%|hsg' THEN 'Targets met' ELSE 'Not met' END AS prevention"""
DS = {
"ds_prio": f"""SELECT p.service_label AS service, {SCN}, p.planning_area, p.cluster, p.rank, p.unit,
  ROUND(p.gap_2026) AS gap_now, ROUND(p.gap_2031) AS gap_2031, p.next_step, p.next_step_reason, p.confidence,
  CASE WHEN p.gap_start IS NULL THEN 'No gap by 2031' WHEN p.gap_start <= 2026 THEN 'Already today'
       ELSE CAST(CAST(p.gap_start AS INT) AS STRING) END AS short_from,
  p.stability_share, p.presets_in_top5, m.lat, m.lon
FROM service_priorities p JOIN planning_area_meta m ON p.pa_key = m.pa_key""",
"ds_nat": f"""SELECT service_label AS service, {SCN}, cluster, make_date(year, 6, 30) AS year_date, year,
  need, capacity, GREATEST(gap, 0) AS shortfall, unit
FROM service_area_year""",
"ds_kpi": f"""SELECT service_label AS service, {SCN}, cluster, need AS need_2031, capacity AS capacity_2031,
  GREATEST(gap, 0) AS gap_2031, pop65 AS seniors_2031
FROM service_area_year WHERE year = 2031""",
"ds_monthly": """SELECT month, value FROM healthpulse_silver.hospital_activity_monthly
WHERE series = 'Community Hospitals Admissions' AND month >= '2015-01-01' AND value IS NOT NULL ORDER BY month""",
}
