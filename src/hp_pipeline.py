"""HealthPulse stages. Each stage takes/returns pandas DataFrames so the same code runs
locally (tests) and inside Databricks notebooks (which read Silver and write Gold Delta tables)."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

import hp_core as hc

SCENARIOS = [(ag, hsg, pl) for ag in ["low", "base", "high"] for hsg in ["no_hsg", "hsg"] for pl in ["on_time", "delayed"]]


def scenario_id(ag, hsg, pl):
    return f"{ag}|{hsg}|{pl}"


# ---------------------------------------------------------------- stage 1: forecast
def stage_forecast(pop_long: pd.DataFrame, lt: pd.DataFrame, a: hc.Assumptions):
    cube = hc.to_cube(hc.prep_population(pop_long))
    err, summary = hc.backtest(cube, lt)
    best = min(summary, key=lambda m: summary[m]["mape_pop65"])

    years = a.horizon
    cubes = {}
    for ag, p in a.ageing.items():
        cubes[ag] = hc.cohort_forecast(cube, lt, a.base_year, years, mig_years=[2022, 2023, 2024],
                                       lt_year=2025, qx_mult=p["qx_mult"], mig65_mult=p["mig65_mult"])
    # If another model wins the backtest, use it as the base level and apply cohort scenario ratios.
    if best == "M1_linear_trend":
        base_level = hc.trend_forecast(cube, a.base_year, years)
    elif best == "M2_damped_growth":
        base_level = hc.damped_forecast(cube, a.base_year, years)
    else:
        base_level = cubes["base"]
    if best != "M3_cohort_component":
        for ag in list(cubes):
            ratio = (cubes[ag][years] / cubes["base"][years].replace(0, np.nan)).fillna(1.0)
            c = cubes[ag].copy()
            c[years] = base_level[years].values * ratio.values
            cubes[ag] = c

    rows = []
    for ag, c in cubes.items():
        b = hc.bands(c)
        b["ageing_scenario"] = ag
        rows.append(b)
    fc = pd.concat(rows, ignore_index=True)
    fc["is_forecast"] = fc.year > a.base_year
    fc["model"] = np.where(fc.is_forecast, best, "observed")
    long = []
    for ag, c in cubes.items():
        s = c.stack().rename("population").reset_index().rename(columns={"level_3": "year"})
        s.columns = ["pa", "sex", "age_group", "year", "population"]
        s["ageing_scenario"] = ag
        long.append(s[s.year >= a.base_year])
    cube_long = pd.concat(long, ignore_index=True)
    jumps = hc.population_jumps(cube)
    origins = hc.backtest_origins(cube, lt)
    f = fc[fc.is_forecast].pivot_table(index=["pa", "year"], columns="ageing_scenario", values="pop65").reset_index()
    f["ordered"] = (f["low"] <= f["base"] + 0.5) & (f["base"] <= f["high"] + 0.5)
    return {"cube": cube, "cubes": cubes, "forecast_bands": fc, "forecast_cells": cube_long,
            "backtest_errors": err, "backtest_summary": summary, "best_model": best, "pop_jumps": jumps,
            "backtest_origins": origins, "scenario_order": f}


# ---------------------------------------------------------------- stage 2: demand, access, gaps
def stage_gaps(cubes: dict, rates_df: pd.DataFrame, beds_annual: pd.DataFrame, poly, ch, nh, planned,
               subzone_pop: pd.DataFrame, subzones_geo: dict, pa_geo: dict, a: hc.Assumptions):
    years = [a.base_year] + a.horizon
    rates = hc.ch_rates(rates_df, 2025)

    beds = beds_annual[beds_annual.year == 2025].set_index("series_path")["value"]
    beds_nat = {"ch": float(beds["Community Hospitals"]), "nh": float(beds["Nursing Homes"])}

    # geometry helpers
    def centroid(geom):
        coords = geom["coordinates"]
        pts = np.array(coords[0] if geom["type"] == "Polygon" else max(coords, key=lambda p: len(p[0]))[0])
        return pts[:, 1].mean(), pts[:, 0].mean()

    zxy = pd.DataFrame([{"subzone": f["properties"]["subzone"], "pa_geo": f["properties"]["planning_area"],
                         "lat": centroid(f["geometry"])[0], "lon": centroid(f["geometry"])[1]} for f in subzones_geo["features"]])
    pa_meta = pd.DataFrame([{"pa": f["properties"]["planning_area"], "region": f["properties"]["region"],
                             "lat": centroid(f["geometry"])[0], "lon": centroid(f["geometry"])[1]} for f in pa_geo["features"]])

    # subzone shares within PA from 2025 (MP2019 subzones)
    sz = subzone_pop[subzone_pop.year == 2025].copy()
    sz["pa"] = hc.pa_key(sz.planning_area)
    sz["subzone"] = sz.subzone.str.upper()
    sz["p65"] = sz.pop_65_74 + sz.pop_75_84 + sz.pop_85plus
    sz["p75"] = sz.pop_75_84 + sz.pop_85plus
    tot = sz.groupby("pa")[["p65", "p75"]].transform("sum")
    sz["s65"] = (sz.p65 / tot.p65.replace(0, np.nan)).fillna(0)
    sz["s75"] = (sz.p75 / tot.p75.replace(0, np.nan)).fillna(0)
    zone_share = sz[["pa", "subzone", "s65", "s75"]]
    zones_xy = zxy[["subzone", "lat", "lon"]]

    facs, fill = hc.build_supply(poly, ch, nh, planned, beds_nat, a)
    facs = hc.fill_missing_coords(facs, pa_meta[["pa", "lat", "lon"]])
    # cluster per planning area = cluster of nearest polyclinic (used for row-level security)
    pc = facs[(facs.line == "primary") & facs.cluster.notna()]
    D = hc.haversine_km(pa_meta.lat.values, pa_meta.lon.values, pc.lat.values, pc.lon.values)
    pa_meta["cluster"] = pc.cluster.values[D.argmin(1)]

    # national benchmark = today's (2026) provision per unit of target
    base_dem = hc.demand_from_cube(cubes["base"], rates, {"primary": 1, "intermediate": 1, "longterm": 1}, [a.base_year], a, False)
    ex = facs[facs.status == "existing"].groupby("line").capacity.sum()
    bench = {"primary": ex["primary"] / base_dem.target_primary.sum(),
             "intermediate": ex["intermediate"] / base_dem.target_intermediate.sum(),
             "longterm": ex["longterm"] / base_dem.target_longterm.sum()}

    gaps, demands = [], []
    for ag, hsg, pl in hc_scenarios():
        dem = hc.demand_from_cube(cubes[ag], rates, bench, years, a, hsg == "hsg")
        g = hc.access_gap(dem, zone_share, zones_xy, facs, a, a.planned_delay_years if pl == "delayed" else 0, bench)
        sid = scenario_id(ag, hsg, pl)
        g["scenario_id"], g["ageing_scenario"], g["hsg_scenario"], g["planned_scenario"] = sid, ag, hsg, pl
        dem["scenario_id"] = sid
        gaps.append(g)
        demands.append(dem)
    gaps = pd.concat(gaps, ignore_index=True)
    demands = pd.concat(demands, ignore_index=True)

    base_pop = demands[demands.scenario_id == "base|no_hsg|on_time"][["pa", "year", "pop65"]]
    tiers = hc.priority_tiers(gaps, base_pop, a.horizon[-1], a)
    tiers = tiers.merge(pa_meta[["pa", "region", "cluster", "lat", "lon"]], on="pa", how="left")
    p26 = base_pop[base_pop.year == a.base_year].set_index("pa").pop65
    p31 = base_pop[base_pop.year == a.horizon[-1]].set_index("pa").pop65
    tiers["pop65_2026"] = tiers.pa.map(p26)
    tiers["pop65_2031"] = tiers.pa.map(p31)
    tiers["pop65_growth"] = tiers.pop65_2031 / tiers.pop65_2026 - 1
    tiers["recommendation"] = tiers.apply(_recommend, axis=1)

    bench_df = pd.DataFrame([{"line": k, "label": hc.LINE_LABEL[k], "unit": hc.LINE_UNIT[k],
                              "benchmark_units_per_target": v,
                              "target_definition": {"primary": "residents aged 65+", "intermediate": "expected community-hospital admissions (MOH 2025 age-sex rates)", "longterm": "residents aged 75+"}[k]}
                             for k, v in bench.items()])
    return {"gaps": gaps, "demand": demands, "tiers": tiers, "facilities": facs, "pa_meta": pa_meta,
            "benchmarks": bench_df, "capacity_fill": fill, "beds_national": beds_nat}


def hc_scenarios():
    return SCENARIOS


def _recommend(r):
    if r.get("tier") in (None, "Not ranked (few residents)") or pd.isna(r.get("priority_line")):
        return None
    ln = r.priority_line
    short = r.get(f"shortfall_{ln}", 0) or 0
    if ln == "primary":
        what = f"primary care: about {short:.1f} polyclinic-equivalents short by 2031"
    elif ln == "intermediate":
        what = f"community hospital capacity: about {short:,.0f} beds short by 2031"
    else:
        what = f"nursing home capacity: about {short:,.0f} beds short by 2031"
    return f"Prioritise {what} (base scenario, vs today's national provision)."


# ---------------------------------------------------------------- stage 3: fan chart + headline impact
def stage_story(fc_bands: pd.DataFrame, demands: pd.DataFrame, gaps: pd.DataFrame, a: hc.Assumptions):
    """Fan-chart series per area and Singapore: history + low/base/high, and HSG effect."""
    hist = fc_bands[(fc_bands.ageing_scenario == "base") & (~fc_bands.is_forecast)]
    rows = []
    # metric: long-term care need (beds) = what drives most investment; plus 65+ population
    for pa, h in hist.groupby("pa"):
        for _, r in h.iterrows():
            rows.append({"pa": pa, "year": int(r.year), "metric": "pop65", "series": "history", "value": r.pop65})
    for sid, label in [("high|no_hsg|on_time", "worst"), ("base|no_hsg|on_time", "base"), ("low|hsg|on_time", "best")]:
        d = demands[demands.scenario_id == sid]
        for _, r in d.iterrows():
            rows.append({"pa": r.pa, "year": int(r.year), "metric": "pop65", "series": label, "value": r.pop65})
            for ln in hc.LINES:
                rows.append({"pa": r.pa, "year": int(r.year), "metric": f"need_{ln}", "series": label, "value": r[f"need_{ln}"]})
    fan = pd.DataFrame(rows)
    sg = fan.groupby(["year", "metric", "series"], as_index=False).value.sum()
    sg["pa"] = "SINGAPORE"
    fan = pd.concat([fan, sg[fan.columns]], ignore_index=True)

    y = a.horizon[-1]
    dn = demands[(demands.year == y)]
    no = dn[dn.scenario_id == "base|no_hsg|on_time"][["need_intermediate", "need_longterm"]].sum()
    yes = dn[dn.scenario_id == "base|hsg|on_time"][["need_intermediate", "need_longterm"]].sum()
    impact = pd.DataFrame([
        {"metric": "hsg_beds_avoided_intermediate_2031", "value": float(no.need_intermediate - yes.need_intermediate), "unit": "beds"},
        {"metric": "hsg_beds_avoided_longterm_2031", "value": float(no.need_longterm - yes.need_longterm), "unit": "beds"},
    ])
    return {"fan": fan, "impact": impact}


# ================================================================ v2: per-service planning outputs
def pa_meta_from_geo(pa_geo, poly):
    def centroid(geom):
        coords = geom["coordinates"]
        pts = np.array(coords[0] if geom["type"] == "Polygon" else max(coords, key=lambda p: len(p[0]))[0])
        return pts[:, 1].mean(), pts[:, 0].mean()
    m = pd.DataFrame([{"pa": f["properties"]["planning_area"], "region": f["properties"]["region"],
                       "lat": centroid(f["geometry"])[0], "lon": centroid(f["geometry"])[1]} for f in pa_geo["features"]])
    D = hc.haversine_km(m.lat.values, m.lon.values, poly.latitude.values, poly.longitude.values)
    m["cluster"] = poly.cluster.values[D.argmin(1)]
    return m


def stage_v2(cubes, rates_df, nat_capacity_long, poly, ch, nh, other_care, planned, subzone_pop, subzones_geo, pa_geo,
             a: hc.Assumptions, mc_draws=200, chas=None):
    import hp_services as hs
    nc = nat_capacity_long[(nat_capacity_long.ownership == "Total") & (nat_capacity_long.year == 2025)].set_index("service").value
    centres = other_care[other_care.facility_type.isin(["Day Care", "Community Rehabilitation Centre", "Centre-based Nursing"])]
    pa_meta = pa_meta_from_geo(pa_geo, poly)
    gps = None if chas is None else chas[chas.licence_type == "MC"].dropna(subset=["latitude", "longitude"])
    R = hs.stage_services(cubes, rates_df, nc, poly, ch, nh, centres, planned, subzone_pop, subzones_geo, pa_meta, a, mc_draws, gps=gps)
    ay = R["area_year"]
    nat = (ay.groupby(["scenario_id", "preset", "hsg", "service", "year"], as_index=False)
             .agg(need=("need", "sum"), capacity=("capacity", "sum"), area_gap_sum=("gap", "sum"),
                  pop65=("pop65", "sum"), pop75=("pop75", "sum"), facilities_open=("facilities_open", "max")))
    nat["national_gap"] = np.where(nat.service == "primary", nat.area_gap_sum, (nat.need - nat.capacity).clip(lower=0))
    y = a.horizon[-1]
    b = ay[(ay.year == y) & (ay.preset == "base")].groupby(["service", "hsg"]).need.sum().unstack()
    impact = pd.DataFrame({"service": b.index, "need_no_prevention": b[False].values, "need_with_prevention": b[True].values})
    impact["avoided"] = impact.need_no_prevention - impact.need_with_prevention
    services = pd.DataFrame([{"service": k, **v} for k, v in hs.SERVICES.items()])
    services["provision_ratio_today"] = services.service.map(R["ratios"])
    presets = pd.DataFrame([{"preset": k, **v} for k, v in hs.PRESETS.items()])
    return {**R, "national_year": nat, "prevention_impact": impact, "pa_meta": pa_meta,
            "services_ref": services, "presets_ref": presets}


def build_gold_v2(F, V, pa_names: pd.Series, boundary_iou: pd.DataFrame | None, a: hc.Assumptions, waits: pd.DataFrame | None = None):
    """Final Gold tables (v2) with user-facing names. pa_names: index pa_key -> display name."""
    import hp_services as hs

    def named(df, pa_col="pa"):
        d = df.rename(columns={pa_col: "pa_key"}).copy()
        d.insert(1, "planning_area", d.pa_key.map(pa_names).fillna(d.pa_key.str.title()))
        return d
    meta = V["pa_meta"].set_index("pa")
    lab = {k: v["label"] for k, v in hs.SERVICES.items()}
    unit = {k: v["unit"] for k, v in hs.SERVICES.items()}
    ay = named(V["area_year"])
    ay["service_label"], ay["unit"] = ay.service.map(lab), ay.service.map(unit)
    ay["cluster"] = ay.pa_key.map(meta.cluster)
    pr = named(V["priorities"])
    pr["service_label"], pr["unit"] = pr.service.map(lab), pr.service.map(unit)
    pr["cluster"], pr["region"] = pr.pa_key.map(meta.cluster), pr.pa_key.map(meta.region)
    nat = V["national_year"].copy()
    nat["service_label"], nat["unit"] = nat.service.map(lab), nat.service.map(unit)
    fac = named(V["facilities"])
    fac["service_label"] = fac.service.map({**lab, "primary_gp": "CHAS GP clinic", "hospital_reference": "Hospital project"})
    pm = named(V["pa_meta"])
    bt = pd.DataFrame([{"model": m, **s, "selected": m == F["best_model"]} for m, s in F["backtest_summary"].items()])
    jumps = named(F["pop_jumps"])
    if boundary_iou is not None:
        jumps = jumps.merge(boundary_iou.rename(columns={"pa": "pa_key"})[["pa_key", "change", "iou"]], on=["pa_key", "change"], how="left")
        jumps["boundary_overlap"] = jumps.pop("iou")
    imp = V["prevention_impact"].copy()
    imp["service_label"], imp["unit"] = imp.service.map(lab), imp.service.map(unit)
    imp = imp[imp.service != "primary"]
    fb = named(F["forecast_bands"])
    extra = {}
    if waits is not None:
        poly = V["facilities"][V["facilities"].service == "primary"][["facility", "lat", "lon", "pa", "status", "cluster"]]
        w = waits.merge(poly[poly.status == "existing"], left_on="polyclinic", right_on="facility", how="left").drop(columns=["facility", "status"])
        extra["polyclinic_waits"] = named(w)
    return {**extra,
        "service_area_year": ay, "service_priorities": pr, "service_national_year": nat, "facilities_v2": fac,
        "planning_area_meta": pm, "model_backtest": bt, "boundary_check": jumps, "prevention_impact": imp,
        "services_ref": V["services_ref"], "presets_ref": V["presets_ref"], "allocation_check": V["conservation"],
        "population_forecast": fb, "assumptions": assumptions_v2(a),
    }


def assumptions_v2(a: hc.Assumptions):
    import hp_services as hs
    rows = [
        ("Base year", "2026", "Latest observed SingStat population (June)"),
        ("Forecast years", "2027-2031", "Cohort-component model (won the 2021-2025 backtest)"),
        ("Level of provision", "Today's Singapore average", "Need = what each area needs to match the 2026 national ratio of capacity to users"),
        ("Community hospital need", "Expected admissions x national beds per admission", "MOH 2025 age-sex admission rates; equals average stay / (365 x occupancy) as the system runs today"),
        ("Nursing home need", "Residents 75+ x national beds per 75+", "MOH 2025 nursing home beds"),
        ("Day care & rehab need", "Residents 75+ x national day places per 75+", "MOH 2025 total day places (9,400)"),
        ("Primary care", "Seniors 65+ living > 1 km from a polyclinic or CHAS GP", "Straight-line distance from subzone centre; CHAS list is a 2021 snapshot"),
        ("Sharing capacity across areas", "Two-step floating catchment", "Each bed or place is shared by everyone within reach; shares add up exactly to national capacity"),
    ]
    for k, v in hs.SERVICES.items():
        if k != "primary":
            rows.append((f"Reach of {v['label'].lower()}", f"{v['catchment_km']:g} km", "Gaussian distance decay, straight-line"))
    for k, v in hs.PRESETS.items():
        rows.append((f"Scenario: {k}", v["text"], "Scenario switch on every page"))
    rows += [
        ("Prevention scenario", f"-{a.hsg_reduction_2031:.0%} use by 2031 (65+)", "ASSUMPTION for illustration; not an official Healthier SG target"),
        ("Announced homes without a date", f"Open by {a.undated_nursing_home_open_year} (optimistic only)", "ASSUMPTION; not counted in base"),
        ("Hospital projects", "Not counted", "Community hospital bed numbers not announced; shown as reference only"),
        ("Capacity estimate test", "200 random draws (+/-35%)", "Estimated capacities varied, national totals kept; share of draws an area stays top 5"),
        ("Areas ranked", "Areas with >= 2,000 residents 65+", "CBD, industrial and nature areas are not ranked"),
    ]
    return pd.DataFrame(rows, columns=["item", "value", "note"])
