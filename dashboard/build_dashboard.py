"""HealthPulse AI/BI dashboard (v2) — same story and colours as the App."""
import json
from datasets_sql import DS

CORAL, MINT, BLUE, NAVY = "#EF5B4C", "#1FAE84", "#2F6FED", "#13254B"
def lines(q): return [l + "\n" for l in q.split("\n")]
datasets = [{"name": k, "displayName": k.replace("ds_", "").title(), "queryLines": lines(q), "catalog": "workspace", "schema": "healthpulse_gold"} for k, q in DS.items()]

def text(name, md, pos):
    return {"widget": {"name": name, "multilineTextboxSpec": {"lines": md}}, "position": pos}

def flt(name, ds, field, title, default, pos, multi=False):
    qs = [{"name": f"q_{name}_{i}", "query": {"datasetName": d, "fields": [{"name": field, "expression": f"`{field}`"}], "disaggregated": False}} for i, d in enumerate(ds)]
    s = {"version": 2, "widgetType": "filter-multi-select" if multi else "filter-single-select",
         "encodings": {"fields": [{"fieldName": field, "displayName": title, "queryName": q["name"]} for q in qs]},
         "frame": {"showTitle": True, "title": title}}
    if default:
        s["selection"] = {"defaultSelection": {"values": {"dataType": "STRING", "values": [{"value": default}]}}}
    return {"widget": {"name": name, "queries": qs, "spec": s}, "position": pos}

def counter(name, field, title, pos):
    return {"widget": {"name": name, "queries": [{"name": "main_query", "query": {"datasetName": "ds_kpi",
            "fields": [{"name": f"sum({field})", "expression": f"SUM(`{field}`)"}], "disaggregated": False}}],
            "spec": {"version": 2, "widgetType": "counter", "encodings": {"value": {"fieldName": f"sum({field})", "displayName": title,
                     "format": {"type": "number-plain", "decimalPlaces": {"type": "max", "places": 0}}}},
                     "frame": {"showTitle": True, "title": title}}}, "position": pos}

SVC = ["ds_prio", "ds_nat", "ds_kpi"]
layout = [
    text("title", ["# Where should we prioritise community care?\n",
                   "A 5-year planning view for regional healthcare teams. Pick a **service** and a **scenario**: each service keeps its own unit "
                   "(beds, day places, or seniors living far from a polyclinic / CHAS GP). Gaps compare 2031 need with the capacity residents can reach, "
                   "at today's Singapore-average level of care — estimates for planning, not observed unmet need. Cluster = cluster of the nearest polyclinic (approximation of the regional health system boundary). Area shortfalls are summed, so a surplus in one area does not cancel a shortfall in another."],
         {"x": 0, "y": 0, "width": 12, "height": 2}),
    flt("f_service", SVC, "service", "Service", "Nursing homes", {"x": 0, "y": 2, "width": 4, "height": 2}),
    flt("f_scn", SVC, "scenario", "Scenario", "Base", {"x": 4, "y": 2, "width": 3, "height": 2}),
    flt("f_prev", SVC, "prevention", "Prevention targets", "Not met", {"x": 7, "y": 2, "width": 2, "height": 2}),
    flt("f_cluster", SVC, "cluster", "Healthcare cluster (approx.)", None, {"x": 9, "y": 2, "width": 3, "height": 2}, multi=True),
    counter("k_need", "need_2031", "Needed in 2031 (beds / places), selected areas", {"x": 0, "y": 4, "width": 4, "height": 3}),
    counter("k_cap", "capacity_2031", "Capacity residents can reach, 2031", {"x": 4, "y": 4, "width": 4, "height": 3}),
    counter("k_gap", "gap_2031", "Sum of area shortfalls, 2031 (primary care: seniors living far)", {"x": 8, "y": 4, "width": 4, "height": 3}),
    {"widget": {"name": "bar_top", "queries": [{"name": "main_query", "query": {"datasetName": "ds_prio", "fields": [
        {"name": "planning_area", "expression": "`planning_area`"}, {"name": "sum(gap_2031)", "expression": "SUM(`gap_2031`)"}],
        "disaggregated": False}}],
        "spec": {"version": 3, "widgetType": "bar", "encodings": {
            "y": {"fieldName": "planning_area", "scale": {"type": "categorical", "sort": {"by": "value"}}, "displayName": "Planning area"},
            "x": {"fieldName": "sum(gap_2031)", "scale": {"type": "quantitative"}, "displayName": "Gap in 2031"}},
            "frame": {"showTitle": True, "title": "Gap by planning area, 2031 (selected service and scenario)"}}},
     "position": {"x": 0, "y": 7, "width": 6, "height": 8}},
    {"widget": {"name": "map", "queries": [{"name": "main_query", "query": {"datasetName": "ds_prio", "fields": [
        {"name": "lat", "expression": "`lat`"}, {"name": "lon", "expression": "`lon`"}, {"name": "planning_area", "expression": "`planning_area`"},
        {"name": "sum(gap_2031)", "expression": "SUM(`gap_2031`)"}], "disaggregated": False}}],
        "spec": {"version": 2, "widgetType": "symbol-map", "mark": {"opacity": 0.85}, "encodings": {
            "coordinates": {"latitude": {"fieldName": "lat"}, "longitude": {"fieldName": "lon"}},
            "color": {"fieldName": "sum(gap_2031)", "scale": {"type": "quantitative", "colorRamp": {"mode": "custom-sequential", "colors": {"start": "#A9E3CB", "end": CORAL}}}, "displayName": "Gap 2031"},
            "size": {"fieldName": "sum(gap_2031)", "scale": {"type": "quantitative"}, "displayName": "Gap 2031"},
            "extra": [{"fieldName": "planning_area", "displayName": "Planning area"}]},
            "frame": {"showTitle": True, "title": "Where the gaps are (bigger, redder = larger gap)"}}},
     "position": {"x": 6, "y": 7, "width": 6, "height": 8}},
    {"widget": {"name": "line_nat", "queries": [{"name": "main_query", "query": {"datasetName": "ds_nat", "fields": [
        {"name": "year_date", "expression": "`year_date`"}, {"name": "sum(need)", "expression": "SUM(`need`)"},
        {"name": "sum(capacity)", "expression": "SUM(`capacity`)"}], "disaggregated": False}}],
        "spec": {"version": 3, "widgetType": "line", "encodings": {
            "x": {"fieldName": "year_date", "scale": {"type": "temporal"}, "displayName": "Year"},
            "y": {"scale": {"type": "quantitative"}, "fields": [{"fieldName": "sum(need)", "displayName": "Need"}, {"fieldName": "sum(capacity)", "displayName": "Capacity"}]},
            "color": {"scale": {"type": "categorical", "mappings": [{"value": "Need", "color": CORAL}, {"value": "Capacity", "color": MINT}]}}},
            "frame": {"showTitle": True, "title": "When does the gap open up? Need vs reachable capacity in the selected areas, 2026-2031"}}},
     "position": {"x": 0, "y": 15, "width": 6, "height": 6}},
    {"widget": {"name": "line_ch", "queries": [{"name": "main_query", "query": {"datasetName": "ds_monthly", "fields": [
        {"name": "month", "expression": "`month`"}, {"name": "sum(value)", "expression": "SUM(`value`)"}], "disaggregated": False}}],
        "spec": {"version": 3, "widgetType": "line", "encodings": {
            "x": {"fieldName": "month", "scale": {"type": "temporal"}, "displayName": "Month"},
            "y": {"fieldName": "sum(value)", "scale": {"type": "quantitative"}, "displayName": "Admissions"}},
            "frame": {"showTitle": True, "title": "Community hospital admissions per month (MOH, live from data.gov.sg API)"}}},
     "position": {"x": 6, "y": 15, "width": 6, "height": 6}},
    {"widget": {"name": "tbl", "queries": [{"name": "main_query", "query": {"datasetName": "ds_prio", "fields": [
        {"name": c, "expression": f"`{c}`"} for c in ["rank", "planning_area", "cluster", "gap_now", "gap_2031", "short_from", "unit", "next_step", "next_step_reason", "stability_share", "presets_in_top5", "confidence"]],
        "disaggregated": True, "orders": [{"direction": "ASC", "expression": "`rank`"}]}}],
        "spec": {"version": 2, "widgetType": "table", "encodings": {"columns": [
            {"fieldName": "rank", "displayName": "#"}, {"fieldName": "planning_area", "displayName": "Area"}, {"fieldName": "cluster", "displayName": "Cluster"},
            {"fieldName": "gap_now", "displayName": "Gap now (2026)"}, {"fieldName": "gap_2031", "displayName": "Gap 2031"}, {"fieldName": "short_from", "displayName": "Short from"}, {"fieldName": "unit", "displayName": "Unit"},
            {"fieldName": "next_step", "displayName": "Suggested next step (2031 outlook)"}, {"fieldName": "next_step_reason", "displayName": "Why"},
            {"fieldName": "stability_share", "displayName": "Stays top 5 in % of tests (population + capacity varied)", "format": {"type": "number-percent", "decimalPlaces": {"type": "max", "places": 0}}},
            {"fieldName": "presets_in_top5", "displayName": "Top 5 in # of 3 scenarios"}, {"fieldName": "confidence", "displayName": "Data confidence"}]},
            "frame": {"showTitle": True, "title": "Areas to review, ranked within the selected service"}}},
     "position": {"x": 0, "y": 21, "width": 12, "height": 8}},
]
dash = {"datasets": datasets,
        "pages": [{"name": "overview", "displayName": "Investment overview", "pageType": "PAGE_TYPE_CANVAS", "layoutVersion": "GRID_V1", "layout": layout}],
        "uiSettings": {"theme": {"canvasBackgroundColor": {"light": "#FFF9F1", "dark": "#1F272D"}, "widgetBackgroundColor": {"light": "#FFFFFF", "dark": "#11171C"},
                                 "widgetBorderColor": {"light": "#F0E9DF", "dark": "#11171C"}, "fontColor": {"light": NAVY, "dark": "#E8ECF0"},
                                 "selectionColor": {"light": BLUE, "dark": "#8ACAFF"},
                                 "visualizationColors": [CORAL, MINT, BLUE, "#F7A86B", "#7C6AE6", "#E7B416", "#13254B"],
                                 "widgetHeaderAlignment": "LEFT", "widgetCornerRadius": 18},
                       "genieSpace": {"isEnabled": True, "overrideId": "01f1c7c254091ed9a5e4ddf00c87ee5e", "enablementMode": "ENABLED"}}}
print(json.dumps(dash))
