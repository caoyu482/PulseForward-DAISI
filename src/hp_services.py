"""HealthPulse v2 — per-service demand, capacity, gaps, timing and priorities.

Each service keeps its own unit; nothing is added across services.

| service       | need (unit)                                   | capacity                                                     |
|---------------|-----------------------------------------------|--------------------------------------------------------------|
| primary       | residents 65+ living > 1 km from a polyclinic or CHAS GP | locations only (coverage, no capacity claimed)   |
| community_hospital | beds = expected admissions x national beds per admission | 10 community hospitals (8 published bed counts)  |
| nursing_home  | beds = residents 75+ x national beds per 75+  | 94 homes (3 published, rest share the national total)        |
| day_care      | places = residents 75+ x national places per 75+ | 387 day care / rehab / centre-based nursing centres share the national places |

"National ... per ..." ratios are today's (2026) level of provision, so a gap means
"below what Singapore provides on average today". For community hospitals this ratio is the
national beds / admissions ratio, i.e. average length of stay / (365 x occupancy) as the system runs now.
Capacity is spread to residents with a two-step floating catchment (2SFCA): each place is shared by
everyone who can reach it, and the shares add up exactly to the national capacity (no double counting).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import hp_core as hc

SERVICES = {
    "community_hospital": dict(label="Community hospitals", unit="beds", target="adm", catchment_km=10.0,
                                confidence="Estimate · 8 of 10 hospitals publish bed counts"),
    "nursing_home": dict(label="Nursing homes", unit="beds", target="p75", catchment_km=5.0,
                         confidence="Estimate · 3 of 94 homes publish bed counts"),
    "day_care": dict(label="Day care & rehab", unit="places", target="p75", catchment_km=3.0,
                     confidence="Estimate · national places shared across centres"),
    "primary": dict(label="Primary care", unit="seniors far from subsidised primary care", target="p65",
                    catchment_km=1.0, confidence="Official locations · coverage only (CHAS list is a 2021 snapshot)"),
}
PRESETS = {  # one simple scenario control for users
    "optimistic": dict(ageing="low", include_undated=True, delay=0,
                       text="Slower ageing; announced projects without a date open by 2029-30"),
    "base": dict(ageing="base", include_undated=False, delay=0,
                 text="Base ageing; only projects with an announced year count"),
    "pessimistic": dict(ageing="high", include_undated=False, delay=2,
                        text="Faster ageing; announced projects open 2 years late"),
}
FAR_KM = {"primary": 1.0, "day_care": 2.0}
MIN_POP65_RANK = 2000
GAP_THRESHOLD = {"beds": 5.0, "places": 5.0}


# ---------------------------------------------------------------- inputs
def subzone_points(subzone_pop, subzones_geo):
    sz = subzone_pop[subzone_pop.year == 2025].copy()
    sz["pa"] = hc.pa_key(sz.planning_area)
    sz["subzone"] = sz.subzone.str.upper()
    sz["p65"] = sz.pop_65_74 + sz.pop_75_84 + sz.pop_85plus
    sz["p75"] = sz.pop_75_84 + sz.pop_85plus
    sz["pall"] = sz.pop_0_64 + sz.p65
    for c in ("p65", "p75", "pall"):
        tot = sz.groupby("pa")[c].transform("sum")
        sz[f"s_{c}"] = (sz[c] / tot.replace(0, np.nan)).fillna(0)

    def centroid(geom):
        coords = geom["coordinates"]
        pts = np.array(coords[0] if geom["type"] == "Polygon" else max(coords, key=lambda p: len(p[0]))[0])
        return pts[:, 1].mean(), pts[:, 0].mean()
    xy = pd.DataFrame([{"subzone": f["properties"]["subzone"], "lat": centroid(f["geometry"])[0],
                        "lon": centroid(f["geometry"])[1]} for f in subzones_geo["features"]])
    return sz[["pa", "subzone", "s_p65", "s_p75", "s_pall"]].merge(xy, on="subzone")


def facility_table(poly, ch, nh, centres, planned, nat: dict, pa_centroids, a: hc.Assumptions, gps=None):
    """One row per facility with service, capacity, capacity_basis, status, open_year."""
    rows = []
    if gps is not None:
        for _, r in gps.iterrows():
            rows.append(dict(facility=r["name"], service="primary_gp", lat=r.latitude, lon=r.longitude, capacity=np.nan,
                             capacity_basis="location (CHAS GP, 2021 snapshot)", estimated=False, status="existing",
                             open_year=0, pa=str(r.planning_area_mp2019).upper(), cluster=None))
    for _, r in poly.iterrows():
        rows.append(dict(facility=r["name"], service="primary", lat=r.latitude, lon=r.longitude, capacity=1.0,
                         capacity_basis="location", estimated=False, status="existing", open_year=0,
                         pa=str(r.planning_area_mp2019).upper(), cluster=r.get("cluster")))
    known = ch.beds_reported.fillna(0).sum(); miss = int(ch.beds_reported.isna().sum())
    fill = max(nat["ch_beds"] - known, 0) / miss if miss else 0
    for _, r in ch.iterrows():
        est = pd.isna(r.beds_reported)
        rows.append(dict(facility=r["name"], service="community_hospital", lat=r.latitude, lon=r.longitude,
                         capacity=float(fill if est else r.beds_reported), estimated=bool(est),
                         capacity_basis="estimated (national total minus published)" if est else f"published ({r.get('beds_period')})",
                         status="existing", open_year=0, pa=str(r.planning_area_mp2019).upper(), cluster=None))
    known = nh.beds_reported.fillna(0).sum(); miss = int(nh.beds_reported.isna().sum())
    fill_nh = (nat["nh_beds"] - known) / miss
    for _, r in nh.iterrows():
        est = pd.isna(r.beds_reported)
        rows.append(dict(facility=r["name"], service="nursing_home", lat=r.latitude, lon=r.longitude,
                         capacity=float(fill_nh if est else r.beds_reported), estimated=bool(est),
                         capacity_basis="estimated (national beds shared)" if est else "published",
                         status="existing", open_year=0, pa=str(r.planning_area_mp2019).upper(), cluster=None))
    per_centre = nat["day_places"] / len(centres)
    for _, r in centres.iterrows():
        rows.append(dict(facility=r["name"], service="day_care", lat=r.latitude, lon=r.longitude, capacity=per_centre,
                         estimated=True, capacity_basis="estimated (national day places shared)", status="existing",
                         open_year=0, pa=str(r.planning_area_mp2019).upper(), cluster=None, subtype=r.get("facility_type")))
    avg_nh = nat["nh_beds"] / len(nh)
    for _, r in planned.iterrows():
        name, st = r.project_name, str(r.service_type).lower()
        services = []
        if "polyclinic" in st and not name.startswith("Redeveloped"):
            services.append("primary")
        if "nursing home" in st:
            services.append("nursing_home")
        if "hospital project" in st:
            services.append("hospital_reference")
        for sv in services:
            dated = not pd.isna(r.target_year)
            yr = int(r.target_year) if dated else (a.undated_polyclinic_open_year if sv == "primary" else a.undated_nursing_home_open_year)
            if sv == "hospital_reference":
                status, cap, basis = "reference only", np.nan, "type mix and community-hospital beds not announced"
            elif sv == "primary":
                status, cap, basis = ("announced with year" if dated else "announced, no year"), 1.0, "location"
            else:
                status = "announced with year" if dated else "announced, no year"
                cap = r.reported_capacity_beds if not pd.isna(r.reported_capacity_beds) else avg_nh
                basis = "announced beds" if not pd.isna(r.reported_capacity_beds) else "assumed average home size"
            rows.append(dict(facility=name, service=sv, lat=r.latitude, lon=r.longitude, capacity=float(cap) if not pd.isna(cap) else np.nan,
                             estimated=sv != "primary", capacity_basis=basis, status=status, open_year=yr,
                             year_assumed=not dated, pa=str(r.planning_area_mp2019).upper(), cluster=None))
    f = pd.DataFrame(rows)
    f = f.merge(pa_centroids.rename(columns={"lat": "clat", "lon": "clon"}), on="pa", how="left")
    miss = f.lat.isna()
    f["location_note"] = np.where(miss, "planning-area centre (address not announced)", "geocoded")
    f.loc[miss, "lat"], f.loc[miss, "lon"] = f.loc[miss, "clat"], f.loc[miss, "clon"]
    return f.drop(columns=["clat", "clon"])


def open_facilities(f, service, year, preset):
    p = PRESETS[preset]
    fl = f[f.service == service]
    ok = (fl.status == "existing") | ((fl.status == "announced with year") & (fl.open_year + p["delay"] <= year))
    if p["include_undated"]:
        ok |= (fl.status == "announced, no year") & (fl.open_year <= year)
    return fl[ok]


# ---------------------------------------------------------------- demand per area-year
def area_targets(cube, rates, years, a, hsg_on):
    lower = np.array([hc.AGE_LOWER[g] for g in cube.index.get_level_values("age_group")])
    rate_vec = np.array([rates.get((sx, g), 0.0) for _, sx, g in cube.index]) / 1000.0
    out = []
    for y in years:
        f = hc.hsg_factor(y, a, hsg_on)
        v = cube[y].values
        df = pd.DataFrame({"pa": cube.index.get_level_values("pa"), "pall": v, "p65": v * (lower >= 65),
                           "p75": v * (lower >= 75), "p75_hsg": v * (lower >= 75) * f,
                           "adm": v * rate_vec * np.where(lower >= 65, f, 1.0)})
        g = df.groupby("pa").sum().reset_index()
        g["year"] = y
        out.append(g)
    return pd.concat(out, ignore_index=True)


def two_sfca_area(zones, facs, demand_col, d0):
    acc = hc.two_step_fca(zones.rename(columns={demand_col: "demand"}), facs, d0)
    z = zones.assign(reached=acc * zones[demand_col])
    return z.groupby("pa").reached.sum()


def far_seniors(zones, facs, km, pop_col):
    if len(facs) == 0:
        return zones.groupby("pa")[pop_col].sum()
    D = hc.haversine_km(zones.lat.values, zones.lon.values, facs.lat.values, facs.lon.values)
    far = D.min(1) > km
    return zones.assign(far=zones[pop_col] * far).groupby("pa").far.sum()


# ---------------------------------------------------------------- main stage
def stage_services(cubes, rates_df, nat_capacity, poly, ch, nh, centres, planned, subzone_pop, subzones_geo,
                   pa_meta, a: hc.Assumptions, mc_draws=200, seed=7, gps=None):
    years = [a.base_year] + a.horizon
    rates = hc.ch_rates(rates_df, 2025)
    nc = nat_capacity
    nat = {"ch_beds": float(nc.loc["Community Hospitals"]), "nh_beds": float(nc.loc["Nursing Homes"]),
           "day_places": float(nc.loc["Total No. of Day Places"])}
    zones = subzone_points(subzone_pop, subzones_geo)
    facs = facility_table(poly, ch, nh, centres, planned, nat, pa_meta[["pa", "lat", "lon"]], a, gps)

    # national provision today (2026, base) = benchmark ratios
    t26 = area_targets(cubes["base"], rates, [a.base_year], a, False).sum(numeric_only=True)
    ratio = {"community_hospital": nat["ch_beds"] / t26.adm, "nursing_home": nat["nh_beds"] / t26.p75,
             "day_care": nat["day_places"] / t26.p75}

    rows = []
    for preset, p in PRESETS.items():
        for hsg in (False, True):
            tg = area_targets(cubes[p["ageing"]], rates, years, a, hsg)
            for y, ty in tg.groupby("year"):
                z = zones.merge(ty, on="pa", how="left").fillna(0)
                for c in ("pall", "p65", "p75", "p75_hsg", "adm"):
                    share = {"pall": "s_pall", "p65": "s_p65", "p75": "s_p75", "p75_hsg": "s_p75", "adm": "s_p65"}[c]
                    z[c] = z[c] * z[share]
                for sv in SERVICES:
                    fl = open_facilities(facs, sv, y, preset)
                    if sv == "primary":
                        far = far_seniors(z, pd.concat([fl, facs[facs.service == "primary_gp"]]), FAR_KM["primary"], "p65")
                        d = pd.DataFrame({"pa": ty.pa, "need": np.nan, "capacity": np.nan, "gap": ty.pa.map(far).values,
                                          "facilities_open": len(fl)})
                    else:
                        tcol = "adm" if sv == "community_hospital" else "p75_hsg"
                        need = ty.set_index("pa")[tcol] * ratio[sv]
                        reached = two_sfca_area(z.assign(dem=z[tcol]), fl.dropna(subset=["capacity"]), "dem",
                                                SERVICES[sv]["catchment_km"])
                        d = pd.DataFrame({"pa": need.index, "need": need.values, "capacity": need.index.map(reached).fillna(0).values})
                        d["gap"] = (d.need - d.capacity).clip(lower=0)
                        d["facilities_open"] = len(fl)
                        if sv == "day_care":
                            far = far_seniors(z, fl, FAR_KM["day_care"], "p75")
                            d["seniors_far"] = d.pa.map(far).values
                    d["year"], d["service"], d["preset"], d["hsg"] = y, sv, preset, hsg
                    d["pop65"] = d.pa.map(ty.set_index("pa").p65).values
                    d["pop75"] = d.pa.map(ty.set_index("pa").p75).values
                    rows.append(d)
    ay = pd.concat(rows, ignore_index=True)
    ay["scenario_id"] = ay.preset + "|" + np.where(ay.hsg, "hsg", "no_hsg")

    # capacity conservation check (2SFCA must not double count)
    chk = ay[(ay.year == a.base_year) & (ay.scenario_id == "base|no_hsg") & (ay.service != "primary")].groupby("service").capacity.sum()
    exist = facs[facs.status == "existing"].groupby("service").capacity.sum()
    conservation = pd.DataFrame({"allocated": chk, "existing_total": exist.reindex(chk.index)})
    conservation["difference_pct"] = (conservation.allocated / conservation.existing_total - 1) * 100

    priorities = rank_priorities(ay, facs, zones, cubes, rates, a, ratio, mc_draws, seed)
    return {"area_year": ay, "facilities": facs, "priorities": priorities, "ratios": ratio, "national": nat,
            "conservation": conservation.reset_index()}


def gap_start(series_by_year, unit):
    thr = GAP_THRESHOLD.get(unit, 0.5)
    for y, v in series_by_year.sort_index().items():
        if v >= thr:
            return int(y)
    return None


def rank_priorities(ay, facs, zones, cubes, rates, a, ratio, mc_draws, seed):
    last = a.horizon[-1]
    eligible = set(ay[(ay.year == a.base_year) & (ay.scenario_id == "base|no_hsg") & (ay.pop65 >= MIN_POP65_RANK)].pa)
    out = []
    for sid, g in ay.groupby("scenario_id"):
        for sv, gs in g.groupby("service"):
            unit = "seniors" if sv == "primary" else SERVICES[sv]["unit"]
            fin = gs[(gs.year == last) & gs.pa.isin(eligible)].set_index("pa")
            rank = fin.gap.rank(ascending=False, method="first")
            piv = gs[gs.pa.isin(eligible)].pivot_table(index="pa", columns="year", values="gap")
            starts = piv.apply(lambda r: gap_start(r, unit), axis=1)
            now = piv[a.base_year]
            for pa in fin.index:
                out.append(dict(scenario_id=sid, service=sv, pa=pa, rank=int(rank[pa]), gap_2031=float(fin.gap[pa]),
                                gap_2026=float(now.get(pa, np.nan)),
                                need_2031=fin.need[pa], capacity_2031=fin.capacity[pa], gap_start=starts.get(pa),
                                pop65_2031=fin.pop65[pa]))
    pr = pd.DataFrame(out)
    pr["top5"] = pr["rank"] <= 5
    # scenario stability: in how many of the 3 presets (prevention off) is the area in the top 5?
    st = pr[pr.scenario_id.str.endswith("no_hsg")].groupby(["service", "pa"]).top5.sum().rename("presets_in_top5")
    pr = pr.merge(st.reset_index(), on=["service", "pa"], how="left")
    # capacity-estimate stability (base scenario): perturb estimated capacities, keep national totals fixed
    mc = capacity_stability(ay, facs, zones, cubes, rates, a, ratio, eligible, mc_draws, seed)
    pr = pr.merge(mc, on=["service", "pa"], how="left")
    pr["next_step"] = pr.apply(next_step, axis=1, facs=facs)
    pr["next_step_reason"] = pr.apply(next_step_reason, axis=1, facs=facs)
    pr["confidence"] = pr.service.map({k: v["confidence"] for k, v in SERVICES.items()})
    return pr


def capacity_stability(ay, facs, zones, cubes, rates, a, ratio, eligible, draws, seed):
    """Share of random draws in which the area stays top 5 (2031). Each draw varies BOTH inputs:
    population (one of the slower / base / faster ageing forecasts) and estimated capacities (log-normal factor,
    sd 0.35, re-scaled so the national total is unchanged). Primary care has no capacity; we vary the distance
    threshold (0.75 / 1 / 1.25 km) x the three ageing forecasts instead."""
    rng = np.random.default_rng(seed)
    last = a.horizon[-1]
    ageing = [k for k in ("low", "base", "high") if k in cubes]
    TG, Z = {}, {}
    for ag in ageing:  # population uncertainty: each draw also picks one of the ageing scenarios
        tg = area_targets(cubes[ag], rates, [last], a, False)
        z = zones.merge(tg, on="pa", how="left").fillna(0)
        z["adm"] = z.adm * z.s_p65
        z["p75_hsg"] = z.p75_hsg * z.s_p75
        z["p65"] = z.p65 * z.s_p65
        TG[ag], Z[ag] = tg, z
    z = Z["base"]
    elig = sorted(eligible)
    res = []
    for sv in ("community_hospital", "nursing_home", "day_care"):
        fl = open_facilities(facs, sv, last, "base").dropna(subset=["capacity"]).reset_index(drop=True)
        tcol = "adm" if sv == "community_hospital" else "p75_hsg"
        D = hc.haversine_km(z.lat.values, z.lon.values, fl.lat.values, fl.lon.values)
        W = hc.gauss_w(D, SERVICES[sv]["catchment_km"])
        counts = pd.Series(0, index=elig, dtype=float)
        for _ in range(draws):
            ag = ageing[rng.integers(len(ageing))]
            need = TG[ag].set_index("pa")[tcol] * ratio[sv]
            dem = Z[ag][tcol].values
            denom = (dem[:, None] * W).sum(0)
            cap = fl.capacity.values.copy()
            est = fl.estimated.values
            if est.any():
                fixed = cap[~est].sum()
                cap[est] = cap[est] * rng.lognormal(0, 0.35, est.sum())
                cap[est] = cap[est] / cap[est].sum() * (fl.capacity.values[est].sum())
            Rj = np.divide(cap, denom, out=np.zeros_like(cap), where=denom > 0)
            reached = pd.Series((W * Rj[None, :]).sum(1) * dem, index=z.pa).groupby(level=0).sum()
            gap = (need - reached.reindex(need.index).fillna(0)).clip(lower=0)
            top = gap[gap.index.isin(elig)].sort_values(ascending=False).index[:5]
            counts[counts.index.isin(top)] += 1
        res.append(pd.DataFrame({"service": sv, "pa": counts.index, "stability_share": counts.values / draws}))
    # primary: vary "far" threshold 2.5 / 3 / 3.5 km
    fl = pd.concat([open_facilities(facs, "primary", last, "base"), facs[facs.service == "primary_gp"]])
    counts = pd.Series(0, index=elig, dtype=float)
    combos = [(km, ag) for km in (0.75, 1.0, 1.25) for ag in ageing]
    for km, ag in combos:
        far = far_seniors(Z[ag], fl, km, "p65")
        top = far[far.index.isin(elig)].sort_values(ascending=False).index[:5]
        counts[counts.index.isin(top)] += 1
    res.append(pd.DataFrame({"service": "primary", "pa": counts.index, "stability_share": counts.values / len(combos)}))
    return pd.concat(res, ignore_index=True)


def next_step(r, facs):
    """Suggested next step for planners. Cautious by design: the model compares need with today's average provision,
    so it can only point to where expansion should be ASSESSED, not prove an unmet need."""
    return _next_step(r, facs)[0]


def next_step_reason(r, facs):
    return _next_step(r, facs)[1]


def _next_step(r, facs):
    if not r.top5 and r.gap_2031 <= 0:
        return "No action needed now", "Reachable capacity keeps up with need through 2031."
    planned_here = facs[(facs.pa == r.pa) & (facs.status != "existing") & (facs.service == r.service)]
    if r.service == "primary":
        if len(planned_here):
            return "Check planned polyclinic timing", "A polyclinic is announced here; confirm when it opens."
        if r.top5:
            return "Study primary care access", "Many seniors live more than 1 km from a polyclinic or CHAS GP; check walking routes and current GP list."
        return "Monitor access", "Fewer seniors live far from care than in the top areas."
    if len(planned_here):
        return "Check planned capacity & timing", "An announced project here may close the gap; confirm its beds/places and opening year."
    stable = (r.presets_in_top5 or 0) >= 3
    share = r.stability_share or 0
    if r.top5 and stable and share >= 0.8:
        return "Assess expansion", "Need keeps growing and the area stays in the top 5 in every test; verify nearby operating capacity, then assess expansion."
    if r.top5 and share < 0.6:
        return "Verify current capacity", "The ranking depends on estimated capacities; confirm how many beds/places nearby facilities actually run."
    if r.top5:
        return "Verify capacity, then assess", "Top 5 in most tests; confirm nearby operating capacity before assessing expansion."
    return "Monitor demand growth", "A gap is projected, but smaller than in the top areas."
