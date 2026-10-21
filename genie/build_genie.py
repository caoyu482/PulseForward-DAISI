import json, uuid
G = "workspace.healthpulse_gold"
def nid(): return uuid.uuid4().hex
samples = [
    "Which 5 areas have the largest nursing home bed gap in 2031?",
    "Where should we add day care places first, and what is the next step?",
    "How many community hospital beds will Singapore need in 2031 in the pessimistic scenario?",
    "Which NUHS areas have the most seniors living far from a polyclinic or GP?",
    "Which polyclinics have the longest waits to see a doctor?",
    "How many nursing home beds would prevention save by 2031?",
]
examples = [
    ("Top 5 areas for nursing homes in 2031 with next steps",
     f"SELECT rank, planning_area, cluster, ROUND(gap_2026) AS gap_now_beds, ROUND(gap_2031) AS gap_2031_beds, gap_start AS short_from_year, next_step, next_step_reason FROM {G}.service_priorities WHERE service = 'nursing_home' AND scenario_id = 'base|no_hsg' AND rank <= 5 ORDER BY rank"),
    ("Singapore community hospital beds needed vs capacity by year, pessimistic scenario",
     f"SELECT year, ROUND(need) AS beds_needed, ROUND(capacity) AS beds_capacity, ROUND(area_gap_sum) AS sum_of_area_shortfalls, ROUND(national_gap) AS net_singapore_gap FROM {G}.service_national_year WHERE service = 'community_hospital' AND scenario_id = 'pessimistic|no_hsg' ORDER BY year"),
    ("Day care places gap in Bedok from 2026 to 2031",
     f"SELECT year, ROUND(need) AS places_needed, ROUND(capacity) AS places_reachable, ROUND(gap) AS places_gap FROM {G}.service_area_year WHERE service = 'day_care' AND planning_area = 'Bedok' AND scenario_id = 'base|no_hsg' ORDER BY year"),
    ("Seniors living far from primary care by area in 2031",
     f"SELECT planning_area, cluster, ROUND(gap) AS seniors_far FROM {G}.service_area_year WHERE service = 'primary' AND year = 2031 AND scenario_id = 'base|no_hsg' ORDER BY seniors_far DESC LIMIT 10"),
    ("Beds and places avoided in 2031 if prevention targets are met",
     f"SELECT service_label, ROUND(avoided) AS avoided, unit FROM {G}.prevention_impact"),
]
instr = [
    "This space answers where Singapore should prioritise community care for seniors, by planning area, 2026-2031. Services: community_hospital (beds), nursing_home (beds), day_care (day places), primary (coverage: seniors 65+ living more than 1 km from a polyclinic or CHAS GP).",
    "Never add numbers across services: each service has its own unit (see column unit).",
    "Default scenario: scenario_id = 'base|no_hsg'. Presets: optimistic (slower ageing, undated projects open), base, pessimistic (faster ageing, projects 2 years late). Suffix |hsg = prevention targets met (illustrative 10% lower use, not an official target). Say which scenario you used.",
    "Two gap totals exist: area_gap_sum = sum of each area's shortfall (default, used in the App; a surplus in one area does not cancel a shortfall in another) and national_gap = net Singapore need minus capacity (smaller). Name the one you report. gap_start = first year an area is short (2026 = already short today). next_step is a cautious suggestion from the 2031 outlook ('Assess expansion' means verify nearby operating capacity first); cluster is approximated by the nearest polyclinic's cluster.",
    "Gaps are estimates against today's Singapore-average level of care, not observed unmet need. 2026 is the baseline; 2027-2031 are forecasts. Nursing home and day care capacities are partly estimated; quote the confidence column when relevant.",
]
cols = {
    "service_priorities": [{"column_name": "service", "enable_format_assistance": True, "enable_entity_matching": True},
                           {"column_name": "service_label", "enable_entity_matching": True, "synonyms": ["service type", "care type"]},
                           {"column_name": "scenario_id", "enable_format_assistance": True, "enable_entity_matching": True},
                           {"column_name": "planning_area", "enable_entity_matching": True, "synonyms": ["area", "town"]},
                           {"column_name": "cluster", "enable_entity_matching": True, "synonyms": ["healthcare cluster", "RHS"]},
                           {"column_name": "next_step", "enable_entity_matching": True, "synonyms": ["recommendation", "action"]},
                           {"column_name": "gap_2031", "synonyms": ["shortfall", "beds short", "gap"]},
                           {"column_name": "gap_start", "synonyms": ["short from", "when does the gap start", "first year short"]}],
    "service_area_year": [{"column_name": "service", "enable_format_assistance": True, "enable_entity_matching": True},
                          {"column_name": "scenario_id", "enable_format_assistance": True, "enable_entity_matching": True},
                          {"column_name": "planning_area", "enable_entity_matching": True},
                          {"column_name": "gap", "synonyms": ["shortfall", "deficit"]}],
    "service_national_year": [{"column_name": "service", "enable_format_assistance": True, "enable_entity_matching": True},
                              {"column_name": "scenario_id", "enable_format_assistance": True, "enable_entity_matching": True}],
    "facilities_v2": [{"column_name": "status", "enable_format_assistance": True, "enable_entity_matching": True},
                      {"column_name": "service", "enable_format_assistance": True}, {"column_name": "lat", "exclude": True}, {"column_name": "lon", "exclude": True}],
    "population_forecast": [{"column_name": "ageing_scenario", "enable_format_assistance": True, "enable_entity_matching": True},
                            {"column_name": "pop65", "synonyms": ["seniors", "elderly", "residents aged 65 and over"]}],
    "prevention_impact": [],
    "polyclinic_waits": [{"column_name": "polyclinic", "enable_entity_matching": True}, {"column_name": "lat", "exclude": True}, {"column_name": "lon", "exclude": True},
                         {"column_name": "consult_p50_min", "synonyms": ["waiting time", "wait to see a doctor", "median wait"]},
                         {"column_name": "consult_p95_min", "synonyms": ["busy time wait", "worst wait"]}],
}
tables = []
for t, cc in sorted(cols.items(), key=lambda x: f"{G}.{x[0]}"):
    e = {"identifier": f"{G}.{t}"}
    if cc:
        e["column_configs"] = sorted(cc, key=lambda c: c["column_name"])
    tables.append(e)
space = {"version": 2,
         "config": {"sample_questions": sorted([{"id": nid(), "question": [q]} for q in samples], key=lambda x: x["id"])},
         "data_sources": {"tables": tables},
         "instructions": {"example_question_sqls": sorted([{"id": nid(), "question": [q], "sql": [s]} for q, s in examples], key=lambda x: x["id"]),
                          "text_instructions": [{"id": nid(), "content": instr}]}}
print(json.dumps(space))
