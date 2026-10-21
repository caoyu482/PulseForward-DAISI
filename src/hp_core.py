"""HealthPulse core logic (pure pandas/numpy, runs locally and on Databricks serverless).

Pipeline:
  population (planning area x 5-year age group x sex, 2011-2026)
    -> 3 forecasting models + backtest (train <=2020, test 2021-2025)
    -> 5-year forecast 2027-2031 under ageing scenarios
    -> demand by service line (primary / intermediate / long-term care)
    -> supply accessibility via two-step floating catchment area (2SFCA)
    -> coverage, shortfall, robust priority tiers across 12 scenarios
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

AGE_GROUPS = ["0-4", "5-9", "10-14", "15-19", "20-24", "25-29", "30-34", "35-39", "40-44",
              "45-49", "50-54", "55-59", "60-64", "65-69", "70-74", "75-79", "80-84", "85+"]
AGE_LOWER = {g: i * 5 for i, g in enumerate(AGE_GROUPS)}
SEXES = ["female", "male"]
LINES = ["primary", "intermediate", "longterm"]
LINE_LABEL = {"primary": "Primary care (polyclinics)",
              "intermediate": "Intermediate care (community hospital beds)",
              "longterm": "Long-term care (nursing home beds)"}
LINE_UNIT = {"primary": "polyclinics", "intermediate": "beds", "longterm": "beds"}


@dataclass
class Assumptions:
    base_year: int = 2026
    horizon: list = field(default_factory=lambda: [2027, 2028, 2029, 2030, 2031])
    # ageing scenarios: multiplier on mortality qx, multiplier on 65+ net-migration residual
    ageing: dict = field(default_factory=lambda: {
        "low": {"qx_mult": 1.10, "mig65_mult": 0.5},
        "base": {"qx_mult": 1.00, "mig65_mult": 1.0},
        "high": {"qx_mult": 0.85, "mig65_mult": 1.5}})
    # Healthier SG: illustrative reduction in 65+ intermediate/long-term care need reached by 2031
    hsg_reduction_2031: float = 0.10
    hsg_start_year: int = 2027
    planned_delay_years: int = 2
    undated_nursing_home_open_year: int = 2029
    undated_polyclinic_open_year: int = 2030
    # 2SFCA catchments (km, Gaussian decay)
    catchment_km: dict = field(default_factory=lambda: {"primary": 4.0, "intermediate": 10.0, "longterm": 5.0})
    min_pop65_for_ranking: int = 2000
    top_n: int = 5

    def as_frame(self) -> pd.DataFrame:
        rows = [
            ("base_year", self.base_year, "year", "Latest observed population (SingStat, June 2026)"),
            ("forecast_horizon", f"{self.horizon[0]}-{self.horizon[-1]}", "years", "5-year planning horizon"),
            ("hsg_reduction_2031", self.hsg_reduction_2031, "share", "ILLUSTRATIVE: Healthier SG prevention lowers 65+ community-hospital and nursing-home need, phased linearly from 2027"),
            ("planned_delay_years", self.planned_delay_years, "years", "Delay scenario for announced facilities"),
            ("undated_nursing_home_open_year", self.undated_nursing_home_open_year, "year", "ASSUMPTION: MOH lists these homes as upcoming without a year"),
            ("undated_polyclinic_open_year", self.undated_polyclinic_open_year, "year", "ASSUMPTION: polyclinics announced without a year"),
            ("min_pop65_for_ranking", self.min_pop65_for_ranking, "residents", "Areas with fewer seniors (e.g. CBD, water catchment) are not ranked"),
        ]
        for k, v in self.catchment_km.items():
            rows.append((f"catchment_km_{k}", v, "km", "2SFCA Gaussian catchment radius (straight-line distance)"))
        for s, d in self.ageing.items():
            rows.append((f"ageing_{s}_qx_mult", d["qx_mult"], "x", "Mortality multiplier (lower = people live longer = more seniors)"))
            rows.append((f"ageing_{s}_mig65_mult", d["mig65_mult"], "x", "Shift of observed 65+ net movement per area, as a share of its size (1.5 = 50% more seniors moving in or 50% fewer moving out)"))
        return pd.DataFrame(rows, columns=["key", "value", "unit", "note"]).astype({"value": str})


# ----------------------------------------------------------------------------------------------
# Population
# ----------------------------------------------------------------------------------------------
def pa_key(s: pd.Series) -> pd.Series:
    return s.astype(str).str.strip().str.upper()


def prep_population(pop: pd.DataFrame) -> pd.DataFrame:
    """Return long frame: pa, sex, age_group, year, population."""
    d = pop.rename(columns={"population_rounded": "population"}).copy()
    d["pa"] = pa_key(d["planning_area"])
    d["sex"] = d["sex"].str.lower()
    d = d[d["age_group"].isin(AGE_GROUPS)]
    return d.groupby(["pa", "sex", "age_group", "year"], as_index=False)["population"].sum()


def to_cube(long: pd.DataFrame) -> pd.DataFrame:
    """Wide cube: index (pa, sex, age_group), columns year."""
    c = long.pivot_table(index=["pa", "sex", "age_group"], columns="year", values="population", aggfunc="sum").fillna(0)
    c = c.reindex(pd.MultiIndex.from_product([sorted(long.pa.unique()), SEXES, AGE_GROUPS],
                                             names=["pa", "sex", "age_group"])).fillna(0).astype(float)
    return c


def survival_by_group(lt: pd.DataFrame, year: int, qx_mult: float = 1.0) -> pd.DataFrame:
    """One-year survival probability per (sex, 5-year group) from the single-age life table."""
    t = lt[(lt.reference_year == year) & (lt.sex.isin(SEXES))][["sex", "age_x", "qx", "lx"]].copy()
    t["qx"] = (t["qx"] * qx_mult).clip(0, 1)
    t["age_group"] = pd.cut(t.age_x, bins=[-1] + [a + 4 for a in range(0, 85, 5)] + [200], labels=AGE_GROUPS)
    t["p"] = 1 - t["qx"]
    s = t.groupby(["sex", "age_group"], observed=True).apply(lambda g: np.average(g.p, weights=g.lx)).rename("s")
    return s.reset_index()


def _cohort_step(P: np.ndarray, S: np.ndarray, M: np.ndarray) -> np.ndarray:
    """P, S, M shaped (n_cells_pa_sex, 18). Annual step with 1/5 of each group ageing into the next."""
    out = np.zeros_like(P)
    stay = P * S * 0.8
    move = P * S * 0.2
    out[:, :] = stay
    out[:, 1:] += move[:, :-1]
    out[:, -1] += move[:, -1]  # 85+ is open-ended: movers stay
    out += M
    return np.clip(out, 0, None)


def cohort_forecast(cube: pd.DataFrame, lt: pd.DataFrame, base_year: int, years: list, mig_years: list,
                    lt_year: int, qx_mult: float = 1.0, mig65_mult: float = 1.0) -> pd.DataFrame:
    """Cohort-component projection with area-specific net-migration residuals.

    The residual M (per area x sex x age group) is the average observed change not explained by
    ageing and mortality over `mig_years` transitions (it absorbs births for 0-4 and local
    housing-driven moves). Returns cube with forecast columns for `years`.
    """
    idx = cube.index
    pas = idx.get_level_values(0).unique()
    S = survival_by_group(lt, lt_year, 1.0).set_index(["sex", "age_group"])["s"]
    S_scn = survival_by_group(lt, lt_year, qx_mult).set_index(["sex", "age_group"])["s"]

    def arr(series_by_cell):
        return series_by_cell.values.reshape(len(pas) * len(SEXES), len(AGE_GROUPS))

    s_vec = np.array([S[(sx, g)] for _, sx, g in idx]).reshape(-1, len(AGE_GROUPS))
    s_scn = np.array([S_scn[(sx, g)] for _, sx, g in idx]).reshape(-1, len(AGE_GROUPS))
    resid = []
    for y in mig_years:  # transition y -> y+1
        P0, P1 = arr(cube[y]), arr(cube[y + 1])
        resid.append(P1 - _cohort_step(P0, s_vec, 0))
    M = np.mean(resid, axis=0)
    # Ageing scenarios shift 65+ net movement in ONE direction (more seniors for mig65_mult > 1, fewer for < 1),
    # whether the area currently gains or loses seniors. Multiplying the signed residual would make "faster
    # ageing" remove more seniors from areas with net out-movement (scenario reversal), so we shift by |M|.
    M[:, 13:] = M[:, 13:] + (mig65_mult - 1.0) * np.abs(M[:, 13:])
    out = cube[[c for c in cube.columns if c <= base_year]].copy()
    P = arr(cube[base_year])
    for y in years:
        P = _cohort_step(P, s_scn, M)
        out[y] = P.reshape(-1)
    return out


def trend_forecast(cube: pd.DataFrame, base_year: int, years: list, fit_years: int = 6) -> pd.DataFrame:
    """M1: per-cell linear trend on the last `fit_years` observations."""
    hist = [c for c in cube.columns if base_year - fit_years < c <= base_year]
    X = np.array(hist, dtype=float)
    Y = cube[hist].values
    xm = X.mean()
    b = ((X - xm) * (Y - Y.mean(1, keepdims=True))).sum(1) / ((X - xm) ** 2).sum()
    a = Y.mean(1) - b * xm
    out = cube[[c for c in cube.columns if c <= base_year]].copy()
    for y in years:
        out[y] = np.clip(a + b * y, 0, None)
    return out


def damped_forecast(cube: pd.DataFrame, base_year: int, years: list, window: int = 5, phi: float = 0.8) -> pd.DataFrame:
    """M2: damped-growth time series (Holt-type): average recent log growth, damped by phi each year."""
    hist = [c for c in cube.columns if base_year - window <= c <= base_year]
    Y = cube[hist].values + 1.0
    g = np.diff(np.log(Y), axis=1).mean(1)
    out = cube[[c for c in cube.columns if c <= base_year]].copy()
    level = cube[base_year].values + 1.0
    for h, y in enumerate(years, start=1):
        damp = sum(phi ** k for k in range(1, h + 1))
        out[y] = np.clip(level * np.exp(g * damp) - 1.0, 0, None)
    return out


def bands(cube: pd.DataFrame) -> pd.DataFrame:
    """Aggregate cube to pa x year with total, 65+, 75+, 85+."""
    c = cube.copy()
    lower = np.array([AGE_LOWER[g] for g in c.index.get_level_values("age_group")])
    rows = []
    for name, mask in [("total", lower >= 0), ("pop65", lower >= 65), ("pop75", lower >= 75), ("pop85", lower >= 85)]:
        s = c[mask].groupby(level="pa").sum().stack().rename(name)
        rows.append(s)
    out = pd.concat(rows, axis=1).reset_index().rename(columns={"level_1": "year"})
    out.columns = ["pa", "year", "total", "pop65", "pop75", "pop85"]
    return out


def backtest(cube: pd.DataFrame, lt: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Train on <=2020, forecast 2021-2025, compare with observed. Returns per-area errors and summary."""
    test_years = [2021, 2022, 2023, 2024, 2025]
    models = {
        "M1_linear_trend": trend_forecast(cube, 2020, test_years),
        "M2_damped_growth": damped_forecast(cube, 2020, test_years),
        "M3_cohort_component": cohort_forecast(cube, lt, 2020, test_years, mig_years=[2015, 2016, 2017, 2018, 2019], lt_year=2019),
    }
    obs = bands(cube)
    obs = obs[obs.year.isin(test_years)]
    rows = []
    for m, fc in models.items():
        b = bands(fc)
        b = b[b.year.isin(test_years)].merge(obs, on=["pa", "year"], suffixes=("_fc", "_obs"))
        for metric in ["total", "pop65", "pop75"]:
            b[f"ape_{metric}"] = (b[f"{metric}_fc"] - b[f"{metric}_obs"]).abs() / b[f"{metric}_obs"].replace(0, np.nan)
        b["model"] = m
        rows.append(b)
    err = pd.concat(rows, ignore_index=True)
    big = err[err.pop65_obs >= 2000]
    summary = {}
    for m, g in big.groupby("model"):
        summary[m] = {
            "mae_pop65": float((g.pop65_fc - g.pop65_obs).abs().mean()),
            "mape_pop65": float(g.ape_pop65.mean()),
            "mape_pop75": float(g.ape_pop75.mean()),
            "mape_total": float(g.ape_total.mean()),
            "wape_pop65": float((g.pop65_fc - g.pop65_obs).abs().sum() / g.pop65_obs.sum()),
            "mape_pop65_2025": float(g[g.year == 2025].ape_pop65.mean()),
            "areas_scored": int(g.pa.nunique()),
        }
    return err, summary


def backtest_origins(cube: pd.DataFrame, lt: pd.DataFrame, origins=(2016, 2017, 2018, 2019, 2020), horizon: int = 5,
                     last_obs: int = 2025) -> pd.DataFrame:
    """Rolling-origin backtest: for each origin, train on data up to that year and forecast up to `horizon` years
    ahead (capped at the last observed year). Scored on areas with >= 2,000 residents 65+."""
    obs = bands(cube)
    rows = []
    for o in origins:
        test = [y for y in range(o + 1, o + horizon + 1) if y <= last_obs]
        mig = [y for y in range(o - 5, o)]
        fcs = {"M1_linear_trend": trend_forecast(cube, o, test),
               "M2_damped_growth": damped_forecast(cube, o, test),
               "M3_cohort_component": cohort_forecast(cube, lt, o, test, mig_years=mig, lt_year=o - 1)}
        for m, fc in fcs.items():
            b = bands(fc)
            b = b[b.year.isin(test)].merge(obs[obs.year.isin(test)], on=["pa", "year"], suffixes=("_fc", "_obs"))
            b = b[b.pop65_obs >= 2000]
            ape = (b.pop65_fc - b.pop65_obs).abs() / b.pop65_obs
            rows.append({"origin": o, "model": m, "test_years": f"{test[0]}-{test[-1]}",
                         "mape_pop65": float(ape.mean()), "mae_pop65": float((b.pop65_fc - b.pop65_obs).abs().mean()),
                         "mape_pop65_last": float(ape[b.year == test[-1]].mean()), "areas_scored": int(b.pa.nunique())})
    out = pd.DataFrame(rows)
    out["best_at_origin"] = out.groupby("origin").mape_pop65.transform("min") == out.mape_pop65
    return out


# ----------------------------------------------------------------------------------------------
# Demand
# ----------------------------------------------------------------------------------------------
def ch_rates(rates: pd.DataFrame, year: int = 2025) -> pd.Series:
    r = rates[(rates.rate_year == year) & (rates.hospital_type == "Community Hospital")]
    r = r.set_index(["sex", "age_group"])["rate_per_1000_residents"].fillna(0)
    return r


def hsg_factor(year: int, a: Assumptions, on: bool) -> float:
    if not on or year < a.hsg_start_year:
        return 1.0
    span = a.horizon[-1] - a.hsg_start_year + 1
    k = min(year - a.hsg_start_year + 1, span) / span
    return 1.0 - a.hsg_reduction_2031 * k


def demand_from_cube(cube: pd.DataFrame, rates: pd.Series, ratios: dict, years: list, a: Assumptions, hsg_on: bool) -> pd.DataFrame:
    """Need per pa x year x line, in supply units at today's national provision intensity."""
    lower = np.array([AGE_LOWER[g] for g in cube.index.get_level_values("age_group")])
    rate_vec = np.array([rates.get((sx, g), 0.0) for _, sx, g in cube.index]) / 1000.0
    out = []
    for y in years:
        col = cube[y]
        f = hsg_factor(y, a, hsg_on)
        df = pd.DataFrame({"pa": cube.index.get_level_values("pa"), "p": col.values,
                           "p65": col.values * (lower >= 65), "p75": col.values * (lower >= 75),
                           "adm": col.values * rate_vec * np.where(lower >= 65, f, 1.0)})
        g = df.groupby("pa").sum()
        out.append(pd.DataFrame({
            "pa": g.index, "year": y,
            "target_primary": g.p65, "target_intermediate": g.adm, "target_longterm": g.p75 * f,
            "pop65": g.p65, "pop75": g.p75,
        }))
    d = pd.concat(out, ignore_index=True)
    d["need_primary"] = d.target_primary * ratios["primary"]
    d["need_intermediate"] = d.target_intermediate * ratios["intermediate"]
    d["need_longterm"] = d.target_longterm * ratios["longterm"]
    return d


# ----------------------------------------------------------------------------------------------
# Supply and 2SFCA
# ----------------------------------------------------------------------------------------------
def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1, p2 = np.radians(lat1)[:, None], np.radians(lat2)[None, :]
    dphi = p2 - p1
    dl = np.radians(lon2)[None, :] - np.radians(lon1)[:, None]
    h = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * R * np.arcsin(np.sqrt(h))


def gauss_w(d, d0):
    e = math.exp(-0.5)
    w = (np.exp(-0.5 * (d / d0) ** 2) - e) / (1 - e)
    return np.where(d < d0, w, 0.0)


def two_step_fca(zones: pd.DataFrame, facs: pd.DataFrame, d0: float) -> np.ndarray:
    """zones: lat, lon, demand. facs: lat, lon, capacity. Returns accessibility per zone (capacity per demand unit)."""
    if len(facs) == 0:
        return np.zeros(len(zones))
    D = haversine_km(zones.lat.values, zones.lon.values, facs.lat.values, facs.lon.values)
    W = gauss_w(D, d0)
    denom = (zones.demand.values[:, None] * W).sum(0)
    R = np.divide(facs.capacity.values, denom, out=np.zeros(len(facs)), where=denom > 0)
    return (W * R[None, :]).sum(1)


def build_supply(poly, ch, nh, planned, beds_national: dict, a: Assumptions) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Facility table with line, capacity, open_year (existing = 0), capacity_basis."""
    rows = []
    for _, r in poly.iterrows():
        rows.append(dict(facility=r["name"], line="primary", lat=r.latitude, lon=r.longitude, capacity=1.0,
                         capacity_basis="1 polyclinic", status="existing", open_year=0, pa=str(r.planning_area_mp2019).upper(),
                         cluster=r.get("cluster")))
    known_ch = ch.beds_reported.fillna(0).sum()
    n_missing = int(ch.beds_reported.isna().sum())
    fill_ch = max(beds_national["ch"] - known_ch, 0) / n_missing if n_missing else 0
    for _, r in ch.iterrows():
        est = pd.isna(r.beds_reported)
        rows.append(dict(facility=r["name"], line="intermediate", lat=r.latitude, lon=r.longitude,
                         capacity=float(fill_ch if est else r.beds_reported),
                         capacity_basis="estimated: national total minus published" if est else f"published beds ({r.get('beds_period')})",
                         status="existing", open_year=0, pa=str(r.planning_area_mp2019).upper(), cluster=None))
    known_nh = nh.beds_reported.fillna(0).sum()
    n_nh_missing = int(nh.beds_reported.isna().sum())
    fill_nh = (beds_national["nh"] - known_nh) / n_nh_missing
    for _, r in nh.iterrows():
        est = pd.isna(r.beds_reported)
        rows.append(dict(facility=r["name"], line="longterm", lat=r.latitude, lon=r.longitude,
                         capacity=float(fill_nh if est else r.beds_reported),
                         capacity_basis="estimated: national beds shared equally" if est else "published beds",
                         status="existing", open_year=0, pa=str(r.planning_area_mp2019).upper(), cluster=None))
    avg_nh = beds_national["nh"] / len(nh)
    pa_cent = None
    for _, r in planned.iterrows():
        st = str(r.service_type)
        name = r.project_name
        if "Redeveloped" in name and "Nursing" not in name and "Residence" not in name:
            continue  # redevelopment replaces an existing polyclinic: no net capacity
        lines = []
        if st in ("Polyclinic",) or "polyclinic" in st.lower():
            lines.append("primary")
        if "nursing home" in st.lower() or st == "Nursing home":
            lines.append("longterm")
        if "Redeveloped Jurong" in name:
            lines = ["longterm"]  # polyclinic is a redevelopment, the nursing home is new
        for ln in lines:
            yr = r.target_year if not pd.isna(r.target_year) else (
                a.undated_polyclinic_open_year if ln == "primary" else a.undated_nursing_home_open_year)
            cap = 1.0 if ln == "primary" else (r.reported_capacity_beds if not pd.isna(r.reported_capacity_beds) else avg_nh)
            rows.append(dict(facility=name, line=ln, lat=r.latitude, lon=r.longitude, capacity=float(cap),
                             capacity_basis="1 polyclinic" if ln == "primary" else ("announced beds" if not pd.isna(r.reported_capacity_beds) else "ASSUMED: average nursing home size"),
                             status="planned", open_year=int(yr), pa=str(r.planning_area_mp2019).upper(), cluster=None,
                             timing="announced" if not pd.isna(r.target_year) else "ASSUMED"))
    f = pd.DataFrame(rows)
    return f, pd.DataFrame({"fill_ch_beds": [fill_ch], "fill_nh_beds": [fill_nh], "avg_nh_beds": [avg_nh]})


def fill_missing_coords(f: pd.DataFrame, pa_centroids: pd.DataFrame) -> pd.DataFrame:
    f = f.merge(pa_centroids.rename(columns={"lat": "clat", "lon": "clon"}), on="pa", how="left")
    miss = f.lat.isna()
    f["geo_note"] = np.where(miss, "planning-area centroid (address not announced)", "geocoded")
    f.loc[miss, "lat"] = f.loc[miss, "clat"]
    f.loc[miss, "lon"] = f.loc[miss, "clon"]
    return f.drop(columns=["clat", "clon"])


# ----------------------------------------------------------------------------------------------
# Gap, scenarios, tiers
# ----------------------------------------------------------------------------------------------
def access_gap(demand: pd.DataFrame, zone_share: pd.DataFrame, zones_xy: pd.DataFrame, facs: pd.DataFrame,
               a: Assumptions, delay: int, bench: dict) -> pd.DataFrame:
    """For each year and line: distribute PA target to subzones, run 2SFCA, aggregate to PA."""
    out = []
    for y, dy in demand.groupby("year"):
        for ln in LINES:
            tcol = {"primary": "target_primary", "intermediate": "target_intermediate", "longterm": "target_longterm"}[ln]
            scol = {"primary": "s65", "intermediate": "s65", "longterm": "s75"}[ln]
            z = zone_share.merge(dy[["pa", tcol]], on="pa", how="left").merge(zones_xy, on="subzone")
            z["demand"] = z[scol] * z[tcol].fillna(0)
            fl = facs[(facs.line == ln) & ((facs.status == "existing") | (facs.open_year + delay <= y))]
            z["access"] = two_step_fca(z, fl, a.catchment_km[ln])
            z["supply_reached"] = z.access * z.demand
            g = z.groupby("pa").agg(target=("demand", "sum"), supply_reached=("supply_reached", "sum")).reset_index()
            g["year"], g["line"] = y, ln
            g["access_ratio"] = g.supply_reached / g.target.replace(0, np.nan)
            g["coverage_index"] = g.access_ratio / bench[ln]
            g["need_units"] = g.target * bench[ln]
            g["shortfall_units"] = (g.need_units - g.supply_reached).clip(lower=0)
            out.append(g)
    return pd.concat(out, ignore_index=True)


def priority_tiers(gaps: pd.DataFrame, pop: pd.DataFrame, year: int, a: Assumptions) -> pd.DataFrame:
    """gaps has scenario_id, pa, year, line, coverage_index; pop has pa, year, pop65 (base scenario)."""
    g = gaps[gaps.year == year].copy()
    p65 = pop[pop.year == year].set_index("pa").pop65
    g["pop65"] = g.pa.map(p65)
    g["underserved65"] = g.pop65 * (1 - g.coverage_index.clip(upper=1)).fillna(1)
    comp = g.groupby(["scenario_id", "pa"]).underserved65.mean().rename("composite").reset_index()
    eligible = p65[p65 >= a.min_pop65_for_ranking].index
    comp = comp[comp.pa.isin(eligible)]
    comp["rank"] = comp.groupby("scenario_id").composite.rank(ascending=False, method="first")
    n_scn = comp.scenario_id.nunique()
    freq = comp.assign(top=comp["rank"] <= a.top_n).groupby("pa").top.sum() / n_scn
    base = comp[comp.scenario_id == "base|no_hsg|on_time"].set_index("pa")
    t = pd.DataFrame({"pa": base.index, "composite_base": base.composite.values, "rank_base": base["rank"].values})
    t["top5_share"] = t.pa.map(freq)
    minc = g.groupby("pa").coverage_index.min()
    t["min_coverage_any_scenario"] = t.pa.map(minc)
    t = t.sort_values(["top5_share", "composite_base"], ascending=False).reset_index(drop=True)
    t["tier"] = "Adequate"
    t.loc[t.min_coverage_any_scenario < 0.9, "tier"] = "Watch"
    t.loc[(t.rank_base <= 15), "tier"] = "High"
    t.loc[t.index < a.top_n, "tier"] = "Critical"
    # recommended investment: line with the lowest base coverage
    gb = g[g.scenario_id == "base|no_hsg|on_time"].pivot_table(index="pa", columns="line", values="coverage_index")
    sb = g[g.scenario_id == "base|no_hsg|on_time"].pivot_table(index="pa", columns="line", values="shortfall_units")
    t["priority_line"] = t.pa.map(gb.idxmin(axis=1))
    for ln in LINES:
        t[f"coverage_{ln}"] = t.pa.map(gb[ln])
        t[f"shortfall_{ln}"] = t.pa.map(sb[ln])
    excluded = sorted(set(p65.index) - set(eligible))
    ex = pd.DataFrame({"pa": excluded, "tier": "Not ranked (few residents)"})
    return pd.concat([t, ex], ignore_index=True)


def population_jumps(cube: pd.DataFrame) -> pd.DataFrame:
    """Flag planning areas whose 65+ count jumps at a boundary-version change (2019->2020, 2025->2026)
    much more than in neighbouring years: a sign that the area, not the population, changed."""
    b = bands(cube).pivot(index="pa", columns="year", values="pop65")
    rows = []
    for pa, r in b.iterrows():
        g = r.pct_change()
        for y, lab in ((2020, "MP2014->MP2019"), (2026, "MP2019->MP2025")):
            nb = [g.get(y - 2), g.get(y - 1), g.get(y + 1)] if y + 1 in g.index else [g.get(y - 3), g.get(y - 2), g.get(y - 1)]
            nb = [x for x in nb if pd.notna(x)]
            typical = float(np.median(nb)) if nb else np.nan
            rows.append({"pa": pa, "change": lab, "growth_at_change": float(g.get(y, np.nan)),
                         "typical_growth": typical, "pop65_before": float(r.get(y - 1, np.nan))})
    d = pd.DataFrame(rows)
    d["excess_growth"] = d.growth_at_change - d.typical_growth
    d["flag"] = (d.excess_growth.abs() > 0.05) & (d.pop65_before >= 500)
    return d
