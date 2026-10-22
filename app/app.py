"""HealthPulse — plan community care where it matters.
Team PulseForward · DAISI Challenge Singapore 2026 · Track A3

Two pages for regional health planners, plus an evidence page:
  1. Investment overview — where should we prioritise this service?
  2. Area planning      — what should we plan for this area?
  3. View evidence      — sources, method, checks and assumptions
"""
import json

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import backend

st.set_page_config(page_title="HealthPulse", page_icon="💗", layout="wide", initial_sidebar_state="expanded")


def safe_first_row(df: pd.DataFrame | None, default_dict: dict) -> pd.Series:
    if df is None or df.empty:
        return pd.Series(default_dict)
    return pd.Series({**default_dict, **df.iloc[0].to_dict()})


def safe_first_value(values, default=None):
    if values is None or len(values) == 0:
        return default
    return values.iloc[0] if isinstance(values, (pd.Series, pd.Index)) else values[0]


def safe_last_value(values, default=None):
    if values is None or len(values) == 0:
        return default
    return values.iloc[-1] if isinstance(values, (pd.Series, pd.Index)) else values[-1]


# ------------------------------------------------------------------ design tokens
NAVY, INK, MUTED = "#13254B", "#1F2A44", "#6B7280"
CREAM, CARD, LINE = "#FFF9F1", "#FFFFFF", "#F0E9DF"
CORAL, CORAL_BG = "#EF5B4C", "#FFE7E2"
MINT, MINT_BG = "#1FAE84", "#DDF5EC"
BLUE, BLUE_BG = "#2F6FED", "#E3EEFF"
YELLOW, YELLOW_BG = "#E7B416", "#FFF4CC"
LAV, LAV_BG = "#7C6AE6", "#EEEBFF"
GAP_COLORS = {"Larger gap": "#F27360", "Medium gap": "#F7A86B", "Smaller gap": "#F6D77E",
              "No gap": "#A9E3CB", "Not ranked": "#ECEAE6"}
SERVICE_ORDER = ["community_hospital", "nursing_home", "day_care", "primary"]
SERVICE_ICON = {"community_hospital": "hospital", "nursing_home": "home", "day_care": "users", "primary": "stetho"}
PRESET_LABEL = {"optimistic": "Optimistic", "base": "Base", "pessimistic": "Pessimistic"}

ICONS = {  # simple line icons (stroke = currentColor)
    "bed": '<path d="M3 7v11M3 14h18v4M21 14v-2a3 3 0 0 0-3-3h-7v5"/><circle cx="7" cy="11" r="2"/>',
    "hospital": '<rect x="4" y="3" width="16" height="18" rx="2"/><path d="M12 7v6M9 10h6M9 21v-4h6v4"/>',
    "heart": '<path d="M12 20s-7-4.4-9.2-8.6C1.2 8.3 3 5 6.3 5c2 0 3.3 1.1 3.7 2.2C10.4 6.1 11.7 5 13.7 5 17 5 18.8 8.3 17.2 11.4 15 15.6 12 20 12 20z" transform="translate(1 0)"/>',
    "home": '<path d="M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"/>',
    "users": '<circle cx="9" cy="8" r="3.2"/><path d="M3 20c0-3.3 2.7-5.5 6-5.5s6 2.2 6 5.5"/><circle cx="17" cy="9" r="2.5"/><path d="M15.5 14.6c3 .1 5.5 2 5.5 5.4"/>',
    "stetho": '<path d="M6 3v6a4 4 0 0 0 8 0V3"/><path d="M10 13v2a5 5 0 0 0 10 0v-2"/><circle cx="20" cy="11" r="2"/>',
    "pin": '<path d="M12 21s-7-6.2-7-11.5A7 7 0 0 1 19 9.5C19 14.8 12 21 12 21z"/><circle cx="12" cy="9.5" r="2.5"/>',
    "trend": '<path d="M3 17l6-6 4 4 8-8M15 7h6v6"/>',
    "target": '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="4"/><circle cx="12" cy="12" r="1"/>',
    "check": '<rect x="4" y="4" width="16" height="16" rx="3"/><path d="M8 12l3 3 5-6"/>',
    "calendar": '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.5"/>',
    "alert": '<circle cx="12" cy="12" r="9"/><path d="M12 7v6M12 16.5v.5"/>',
    "doc": '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4M9 12h6M9 16h6"/>',
    "bars": '<path d="M5 20V10M12 20V4M19 20v-7"/>',
}


def icon(name, color=INK, size=20):
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" '
            f'stroke-linecap="round" stroke-linejoin="round">{ICONS[name]}</svg>')


LOGO = (f'<svg width="44" height="40" viewBox="0 0 44 40"><path d="M22 37S3 25.5 3 13.5C3 7 7.8 3 13 3c4 0 7 2.2 9 5 2-2.8 5-5 9-5 '
        f'5.2 0 10 4 10 10.5C41 25.5 22 37 22 37z" fill="{CORAL}"/><path d="M22 37S8 26 8 15c0-4 2.6-7 6-7" fill="none" stroke="#7FB7FF" '
        f'stroke-width="4" stroke-linecap="round"/><path d="M9 21h7l3-6 4 11 3-5h9" fill="none" stroke="white" stroke-width="2.6" '
        f'stroke-linecap="round" stroke-linejoin="round"/></svg>')

st.markdown(f"""
<link href="https://fonts.googleapis.com/css2?family=Nunito:wght@600;700;800;900&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
html, body, [data-testid="stAppViewContainer"], [data-testid="stApp"], [data-testid="stMain"] {{ background:{CREAM}; }}
[data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"], [data-testid="stSidebarCollapseButton"],
[data-testid="stSidebarCollapsedControl"], [data-testid="stSidebarHeader"] {{ display:none !important; }}
* {{ font-family:'Inter', sans-serif; }}
h1, h2, h3, h4, .nun {{ font-family:'Nunito', sans-serif !important; color:{NAVY}; }}
.block-container {{ padding:.85rem 1.4rem .8rem 1.4rem !important; max-width:none !important; }}
[data-testid="stMainBlockContainer"] > div > [data-testid="stVerticalBlock"] {{ gap:14px; }}
[data-testid="stHorizontalBlock"] {{ gap:16px !important; }}
/* slim icon rail */
[data-testid="stSidebar"] {{ min-width:84px !important; max-width:84px !important; width:84px !important; background:white;
   border-right:1px solid {LINE}; }}
[data-testid="stSidebar"] > div {{ width:84px !important; }}
[data-testid="stSidebarContent"] {{ padding:14px 10px !important; }}
[data-testid="stSidebarUserContent"] {{ padding:0 !important; }}
[data-testid="stSidebar"] .stButton > button {{ width:58px; height:52px; border-radius:16px; border:none; background:transparent; color:{MUTED};
   font-size:22px; padding:0; margin:0 auto; display:flex; }}
[data-testid="stSidebar"] .stButton > button:hover {{ background:{BLUE_BG}; color:{BLUE}; }}
[data-testid="stSidebar"] .stButton > button[kind="primary"] {{ background:{BLUE_BG}; color:{BLUE}; }}
[data-testid="stSidebar"] .stButton > button p {{ font-size:24px; }}
.rail-cap {{ font-size:10.5px; color:{MUTED}; text-align:center; margin:-8px 0 6px; }}
/* cards */
[data-testid="stVerticalBlockBorderWrapper"]:has(> div > div[class*="st-key-card"]),
[data-testid="stVerticalBlockBorderWrapper"]:has(> div[class*="st-key-card"]) {{ background:white; border-radius:20px !important;
   border:1px solid {LINE} !important; box-shadow:0 1px 8px rgba(31,42,68,.05); }}
div[class*="st-key-card"] {{ gap:.55rem !important; }}
div[class*="st-key-cardmap"] {{ position:relative; }}
div[class*="st-key-pop"] [data-testid="stElementContainer"], div[class*="st-key-pop"] .stButton, div[class*="st-key-pop"] [data-testid="stMarkdown"] {{ width:100% !important; }}
div[class*="st-key-pop"] {{ position:absolute !important; top:78px; left:18px; width:250px !important; z-index:20; background:white;
   border-radius:16px; border:1px solid {LINE}; box-shadow:0 8px 24px rgba(31,42,68,.12); padding:14px 16px; gap:.4rem !important; }}
.ct {{ display:flex; justify-content:space-between; align-items:flex-start; gap:10px; }}
.ct h3 {{ display:flex; align-items:center; gap:8px; font-weight:800; font-size:19px; margin:0; padding:0; color:{NAVY}; }}
.ct .cap {{ color:{MUTED}; font-size:13px; margin:2px 0 0; line-height:1.35; }}
.ct {{ margin-bottom:2px; padding-bottom:4px; }}
.chip {{ display:inline-flex; align-items:center; gap:6px; border-radius:999px; padding:3px 11px; font-size:12.5px; font-weight:600; white-space:nowrap; }}
.pill {{ display:inline-flex; align-items:center; gap:6px; border-radius:999px; padding:3px 11px; font-size:12.5px; font-weight:600; }}
.lg {{ display:flex; gap:14px; flex-wrap:wrap; font-size:12.5px; color:{INK}; }}
.lg i {{ display:inline-block; width:12px; height:12px; border-radius:4px; margin-right:6px; vertical-align:-1px; }}
/* header */
.hp-title {{ font-family:'Nunito'; font-weight:900; font-size:26px; color:{NAVY}; line-height:1.15; letter-spacing:-.3px; margin:0; }}
.hp-sub {{ font-size:14.5px; color:{MUTED}; margin-top:2px; }}
.crumb {{ color:{MUTED}; font-size:13.5px; }} .crumb b {{ color:{BLUE}; }}
/* KPI tiles */
.kgrid {{ display:grid; grid-template-columns:repeat(2, minmax(0,1fr)); grid-template-rows:repeat(2, minmax(0,1fr)); gap:16px; }}
.kt {{ background:white; border:1px solid {LINE}; border-radius:20px; padding:12px 16px; overflow:hidden; box-shadow:0 1px 8px rgba(31,42,68,.05);
   display:flex; flex-direction:column; justify-content:space-between; min-width:0; }}
.kt .top {{ display:flex; align-items:center; gap:10px; }}
.kt .mid {{ display:flex; align-items:flex-end; justify-content:space-between; gap:8px; min-width:0; }}
.kt .mid .strip {{ width:70px; max-width:70px; flex:0 0 70px; margin:0 0 4px; }}
.kt .ic {{ width:32px; height:32px; border-radius:12px; display:flex; align-items:center; justify-content:center; flex:none; }}
.kt .l {{ font-weight:600; font-size:14px; color:{INK}; line-height:1.2; }}
.kt .v {{ flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; font-family:'Nunito'; font-weight:900; font-size:30px; line-height:1; color:{NAVY}; white-space:nowrap; }}
.kt .v small {{ font-size:16px; font-weight:800; color:{MUTED}; margin-left:4px; }}
.kt .d {{ font-size:12.5px; color:{MUTED}; margin-top:0; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
.kt .d b {{ font-weight:700; }}
.strip {{ display:flex; align-items:flex-end; gap:5px; height:24px; margin-top:6px; }}
.strip span {{ flex:1; border-radius:4px 4px 2px 2px; }}
.strip-l {{ display:flex; justify-content:space-between; font-size:10.5px; color:{MUTED}; margin-top:3px; }}
/* tables */
.tb {{ width:100%; border-collapse:collapse; }}
.tb, .tb td, .tb th, .tb tr {{ border:none !important; }}
.tb th {{ text-align:left; color:{MUTED}; font-weight:500; font-size:12.5px; padding:7px 8px; border-bottom:1px solid {LINE} !important; background:#FFFCF8; }}
.tb td {{ padding:10px 8px; border-bottom:1px solid #F5F1EA !important; font-size:14px; color:{INK}; vertical-align:middle; }}
.tb tr.first td {{ background:#FFF4F1; }}
.tb .num {{ display:inline-flex; width:26px; height:26px; border-radius:50%; background:{CORAL}; color:white; align-items:center; justify-content:center; font-weight:800; font-family:'Nunito'; font-size:13px; }}
.tb .area {{ font-family:'Nunito'; font-weight:800; font-size:15px; color:{NAVY}; }}
.tb .gap {{ font-family:'Nunito'; font-weight:900; color:{CORAL}; font-size:15px; }}
.tb .r {{ text-align:right; }}
/* key/value rows in small cards */
.kv {{ display:flex; justify-content:space-between; align-items:center; font-size:13.5px; padding:6px 0; border-top:1px solid #F5F1EA; }}
.kv span:first-child {{ color:{MUTED}; }} .kv b {{ color:{NAVY}; font-weight:700; text-align:right; }}
/* progress bars */
.pb {{ margin:2px 0 11px; }} .pb .h {{ display:flex; justify-content:space-between; font-size:13.5px; color:{INK}; margin-bottom:6px; }}
.pb .h b {{ font-family:'Nunito'; font-weight:900; color:{NAVY}; }}
.pb .bar {{ height:10px; border-radius:999px; background:#F3EEE6; overflow:hidden; }} .pb .bar span {{ display:block; height:100%; border-radius:999px; }}
.pb .n {{ font-size:11.5px; color:{MUTED}; margin-top:4px; }}
.check {{ display:flex; gap:12px; align-items:flex-start; margin:4px 0 10px; }}
.check .ic {{ width:36px; height:36px; border-radius:12px; display:flex; align-items:center; justify-content:center; flex:none; }}
.note {{ border-radius:14px; padding:10px 14px; font-size:13.5px; }}
.foot {{ color:{MUTED}; font-size:12.5px; display:flex; gap:6px; align-items:center; }}
div[data-testid="stSegmentedControl"] button[aria-checked="true"], div[data-testid="stSegmentedControl"] button[kind="segmented_controlActive"] {{ background:{BLUE} !important; color:white !important; border-color:{BLUE} !important; }}
div[data-testid="stSelectbox"] > div > div {{ border-radius:12px; background:white; }}
.stButton > button {{ border-radius:12px; font-weight:600; }}
.stButton > button[kind="primary"] {{ background:{BLUE}; border-color:{BLUE}; }}
[data-testid="stWidgetLabel"] p {{ font-size:12.5px !important; color:{MUTED} !important; }}
/* tabs as pills */
div[class*="st-key-card"] [data-baseweb="tab-list"] {{ gap:6px; background:#F7F3EC; padding:4px; border-radius:14px; width:fit-content; max-width:100%; }}
div[class*="st-key-card"] button[data-baseweb="tab"] {{ border-radius:10px; padding:6px 14px; height:auto; background:transparent; }}
div[class*="st-key-card"] button[data-baseweb="tab"] p {{ font-size:13.5px; font-weight:600; color:{MUTED}; }}
div[class*="st-key-card"] button[data-baseweb="tab"][aria-selected="true"] {{ background:white; box-shadow:0 1px 4px rgba(31,42,68,.10); }}
div[class*="st-key-card"] button[data-baseweb="tab"][aria-selected="true"] p {{ color:{BLUE}; }}
div[class*="st-key-card"] [data-baseweb="tab-highlight"], div[class*="st-key-card"] [data-baseweb="tab-border"] {{ display:none; }}
div[class*="st-key-svcrow"] {{ border:1px solid {LINE}; border-radius:16px; padding:10px 14px; background:#FFFCF8; }}
div[class*="st-key-card_ctl"] {{ gap:0 !important; }}
div[class*="st-key-open_"] button {{ padding:4px 8px !important; min-height:34px !important; }}
div[class*="st-key-open_"] button p {{ font-size:13px !important; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
@media (max-width: 1500px) {{
  div[class*="st-key-hdr"] > div[data-testid="stHorizontalBlock"] {{ flex-wrap:wrap; }}
  div[class*="st-key-hdr"] > div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] {{ width:100% !important; flex:1 1 100% !important; }}
}}
</style>""", unsafe_allow_html=True)


# ------------------------------------------------------------------ data
@st.cache_data(ttl=3600, show_spinner="Loading governed Gold tables from Unity Catalog…")
def data():
    d = backend.load_all()
    for k in ("area_year",):
        d[k]["year"] = d[k]["year"].astype(int)
    d["geom"] = {r.pa_key: json.loads(r.geometry_json) for r in d["geo"].itertuples()}
    # The browser receives the boundaries on every interaction, so ship a light copy (~80 KB instead of 1.6 MB):
    # simplify to ~90 m tolerance and round coordinates. The full geometry stays in Unity Catalog.
    d["geojson"] = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "id": k, "geometry": _light(g)} for k, g in d["geom"].items()]}
    return d


def _light(geom):
    try:
        from shapely.geometry import mapping, shape
        geom = mapping(shape(geom).simplify(0.0008, preserve_topology=True))
    except Exception:
        pass

    def rnd(c):
        return [round(c[0], 4), round(c[1], 4)] if isinstance(c[0], (int, float)) else [rnd(x) for x in c]
    return {"type": geom["type"], "coordinates": rnd(json.loads(json.dumps(geom["coordinates"])))}


D = data()
SVC = D["services"].set_index("service")
META = D["meta"].set_index("pa_key")
NAME = META.planning_area

ss = st.session_state
ss.setdefault("page", "Investment overview")
ss.setdefault("service", "community_hospital")
ss.setdefault("preset", "base")
ss.setdefault("year", 2031)
ss.setdefault("area", None)
ss.setdefault("prevention", False)
ss.setdefault("cluster", "All Singapore")


def preset():
    return ss.get("preset") or "base"


def sid():
    return f"{preset()}|{'hsg' if ss.get('prevention') else 'no_hsg'}"


def fmt(v, unit):
    if v is None or pd.isna(v):
        return "—"
    return f"{v:,.0f}"


def unit_short(sv):
    return {"community_hospital": "beds", "nursing_home": "beds", "day_care": "places", "primary": "seniors"}[sv]


def waits():
    w = D.get("waits")
    return None if w is None or len(w) == 0 else w


def facilities_data():
    f = D.get("facilities")
    if f is None:
        return pd.DataFrame(columns=["pa_key", "service", "status", "facility", "lat", "lon"])
    return f


def facilities_for_area(pa):
    f = facilities_data()
    if f.empty or "pa_key" not in f.columns:
        return f.iloc[0:0]
    return f[f.pa_key == pa]


def waits_for_area(pa):
    w = waits()
    if w is None or "pa_key" not in w.columns:
        return pd.DataFrame() if w is None else w.iloc[0:0]
    return w[w.pa_key == pa]


def nearest_polyclinics(pa, n=2):
    w = waits()
    if w is None or pa not in META.index:
        return pd.DataFrame()
    lat, lon = META.lat[pa], META.lon[pa]
    d = np.hypot((w.lat - lat) * 111, (w.lon - lon) * 111 * np.cos(np.radians(lat)))
    return w.assign(km=d).sort_values("km").head(n)


def wait_text(r):
    return (f"<b>{r.polyclinic}</b> ({r.km:.1f} km): usually <b>{int(r.consult_p50_min)} min</b> to see a doctor, "
            f"up to {int(r.consult_p95_min)} min at busy times")


def in_cluster(df):
    if ss.cluster == "All Singapore":
        return df
    return df[df.pa_key.map(META.cluster) == ss.cluster]


# ------------------------------------------------------------------ navigation rail
PAGES = [("Investment overview", ":material/space_dashboard:", "Overview"),
         ("Area planning", ":material/location_on:", "Area"),
         ("View evidence", ":material/fact_check:", "Evidence")]


def go_page(p):
    ss.page = p


with st.sidebar:
    st.markdown(f'<div style="display:flex;justify-content:center;margin:2px 0 18px">{LOGO}</div>', unsafe_allow_html=True)
    for p, ic, cap in PAGES:
        st.button(ic, key=f"nav_{cap}", type="primary" if ss.page == p else "secondary", on_click=go_page, args=(p,))
        st.markdown(f'<div class="rail-cap">{cap}</div>', unsafe_allow_html=True)


# ------------------------------------------------------------------ shared pieces
H_TOP, H_MAIN = 286, 492   # sized so a 1920x1080 browser window (~1900x950 usable) shows a whole page without scrolling


def card_title(ic, col, title, cap="", right=""):
    return (f'<div class="ct"><div><h3>{icon(ic, col, 20)} {title}</h3>' + (f'<div class="cap">{cap}</div>' if cap else "") +
            f'</div>{right}</div>')


def chip(text, bg, fg, ic=None):
    return f'<span class="chip" style="background:{bg};color:{fg}">{icon(ic, fg, 13) if ic else ""}{text}</span>'


def controls(show_area=False):
    with st.container(border=True, key="card_ctl"):
        cols = st.columns([1.25, 1.35, 0.72, 1.75, 1.25], vertical_alignment="bottom")
        if show_area:
            opts = sorted(META.index, key=lambda k: NAME[k])
            if not opts:
                st.info("No planning-area data is available.")
                return
            if ss.area not in opts:
                ss.area = safe_first_row(top_list(), {"pa_key": opts[0]}).pa_key
            cols[0].selectbox("Planning area", opts, key="area", format_func=lambda k: NAME[k])
        else:
            cols[0].selectbox("Service area (approx.)", ["All Singapore", "NHG", "NUHS", "SingHealth"], key="cluster",
                              help="Each planning area is assigned to the cluster of its nearest polyclinic — an approximation, not the official "
                                   "regional health system boundary. In Unity Catalog a row filter enforces this mapping.")
        cols[1].selectbox("Service", SERVICE_ORDER, key="service", format_func=lambda s: SVC.label[s])
        cols[2].selectbox("Year", [2027, 2028, 2029, 2030, 2031], key="year")
        cols[3].segmented_control("Scenario", ["optimistic", "base", "pessimistic"], key="preset",
                                  format_func=lambda p: PRESET_LABEL[p],
                                  help="\n\n".join(f"**{PRESET_LABEL[r.preset]}** — {r.text}" for r in D["presets"].itertuples()))
        cols[4].toggle("Prevention targets met", key="prevention",
                       help="Illustrative assumption: community-hospital, nursing-home and day-care use by people 65+ falls 10% by 2031. Not an official target.")


def header(title, sub, show_area=False, pre=""):
    with st.container(key="hdr"):
        c1, c2 = st.columns([1, 2.35], vertical_alignment="center")
        c1.markdown(f'{pre}<div class="hp-title">{title}</div><div class="hp-sub">{sub}</div>', unsafe_allow_html=True)
        with c2:
            controls(show_area)


def ay_now():
    a = D["area_year"]
    return a[(a.scenario_id == sid()) & (a.service == ss.service)]


def top_list(service=None):
    sv = service or ss.service
    a = D["area_year"]
    a = a[(a.scenario_id == sid()) & (a.service == sv)]
    pr = D["priorities"]
    pr = pr[(pr.scenario_id == sid()) & (pr.service == sv)].set_index("pa_key")
    y = a[(a.year == int(ss.year)) & a.pa_key.isin(pr.index)].copy()
    now = a[(a.year == 2026)].set_index("pa_key").gap
    y["gap_now"] = y.pa_key.map(now)
    y = in_cluster(y).sort_values("gap", ascending=False)
    y["next_step"] = y.pa_key.map(pr.next_step)
    y["reason"] = y.pa_key.map(pr.next_step_reason) if "next_step_reason" in pr.columns else ""
    y["gap_start"] = y.pa_key.map(pr.gap_start)
    y["stability"] = y.pa_key.map(pr.stability_share)
    y["presets_in_top5"] = y.pa_key.map(pr.presets_in_top5)
    return y.reset_index(drop=True)


def gap_classes(y):
    s = y.set_index("pa_key").gap
    pos = s[s > (0.5 if ss.service != "primary" else 50)]
    cls = pd.Series("No gap", index=s.index)
    if len(pos):
        q = pos.rank(pct=True)
        cls[q.index] = np.where(q > 0.66, "Larger gap", np.where(q > 0.33, "Medium gap", "Smaller gap"))
    return cls


def series(sv, area=None, sc=None):
    """need / capacity / gap / pop65 per year 2026-2031 for Singapore, the selected cluster, or one area."""
    sc = sc or sid()
    years = range(2026, 2032)
    if area is None and ss.cluster == "All Singapore":
        n = D["national"]
        n = n[(n.scenario_id == sc) & (n.service == sv)].sort_values("year").set_index("year")
        # gap = sum of area shortfalls (a surplus in one area does not cancel a shortfall elsewhere), the same
        # definition used for clusters and areas; the net Singapore gap is kept separately for reference.
        out = pd.DataFrame({"need": n.need, "capacity": n.capacity, "gap": n.area_gap_sum, "net": n.national_gap,
                            "pop65": n.pop65, "open": n.facilities_open})
        return out.reindex(years)
    a = D["area_year"]
    a = a[(a.scenario_id == sc) & (a.service == sv)]
    a = a[a.pa_key == area] if area is not None else in_cluster(a)
    g = a.groupby("year").agg(need=("need", "sum"), capacity=("capacity", "sum"), gap=("gap", "sum"), pop65=("pop65", "sum"),
                              open=("facilities_open", "sum"))
    g["net"] = (g.need - g.capacity).clip(lower=0)
    return g.reindex(years)


def strip(vals, color, yr):
    v = np.asarray(vals, dtype=float)
    if not v.size or not np.isfinite(v).any():
        return ""
    lo, hi = np.nanmin(v), np.nanmax(v)
    rng = hi - lo if hi - lo > 1e-9 else 1
    bars = "".join(f'<span style="height:{30 + 70 * (x - lo) / rng:.0f}%;background:{color};opacity:{1 if y == yr else .28}"></span>'
                   if np.isfinite(x) else '<span style="height:30%;opacity:.15"></span>'
                   for x, y in zip(v, range(2026, 2032)))
    return f'<div class="strip" title="2026 → 2031">{bars}</div>'


def delta(v1, v0, unit="", pct=True, good_up=False):
    if pd.isna(v1) or pd.isna(v0):
        return '<b style="color:#6B7280">—</b>'
    d = v1 - v0
    if pct and v0:
        txt = f"{d / v0:+.0%}"
    else:
        txt = f"{d:+,.0f}{(' ' + unit) if unit else ''}"
    col = (MINT if (d > 0) == good_up else CORAL) if abs(d) > 1e-9 else MUTED
    return f'<b style="color:{col}">{txt}</b>'


def kpi_tiles(area=None):
    sv, yr = ss.service, int(ss.year)
    s = series(sv, area)
    defaults = {col: np.nan for col in ("need", "capacity", "gap", "net", "pop65", "open")}
    r = safe_first_row(s[s.index == yr], defaults)
    r0 = safe_first_row(s[s.index == 2026], defaults)
    where = NAME[area] if area is not None else ("Singapore" if ss.cluster == "All Singapore" else ss.cluster)
    n_near = 0
    if area is not None and waits() is not None:
        n_near = int((nearest_polyclinics(area, 40).km <= 2).sum())
    if sv == "primary":
        w = waits()
        if area is not None and w is not None:
            nearby = nearest_polyclinics(area, 1)
            q = safe_first_row(nearby, {"consult_p50_min": np.nan, "consult_p95_min": np.nan, "polyclinic": ""})
            if nearby.empty or waits_for_area(area).empty:
                wait_v, wait_n = "—", f"No polyclinic wait-time data for {where}"
            else:
                wait_v = fmt(q.consult_p50_min, "")
                wait_n = f"{q.polyclinic.replace(' Polyclinic', '')} · busy times {fmt(q.consult_p95_min, '')} min"
        elif w is not None:
            ww = in_cluster(w) if "pa_key" in w.columns else w
            wait_v = fmt(ww.consult_p50_min.median(), "")
            wait_n = f"median of {len(ww)} polyclinics · MOH Aug 2026" if len(ww) else "No polyclinic wait-time data"
        else:
            wait_v, wait_n = "—", "waiting times not loaded"
        tiles = [(BLUE_BG, "users", BLUE, f"Residents 65+ in {yr}", fmt(r.pop65, ""), "", f"{delta(r.pop65, r0.pop65)} vs 2026 · {where}", s.pop65, BLUE),
                 (CORAL_BG, "heart", CORAL, "Seniors living far from care", fmt(r.gap, ""), "", f"{delta(r.gap, r0.gap, pct=False)} vs 2026 · > 1 km from polyclinic or CHAS GP", s.gap, CORAL),
                 (MINT_BG, "stetho", MINT, f"Polyclinics in {where}, {yr}", fmt(r.open, ""), "",
                  "plus ~1,050 CHAS GP clinics (2021 list)" if area is None else f"{n_near} within 2 km of the area centre", s.open, MINT),
                 (LAV_BG, "calendar", LAV, "Usual wait to see a doctor", wait_v, "min", wait_n, None, LAV)]
    else:
        u = unit_short(sv)
        tiles = [(CORAL_BG, "bed" if u == "beds" else "users", CORAL, f"Needed in {yr}", fmt(r.need, ""), u, f"{delta(r.need, r0.need)} vs 2026 · at today's average provision", s.need, CORAL),
                 (MINT_BG, SERVICE_ICON[sv], MINT, f"Capacity in {yr}", fmt(r.capacity, ""), u,
                  f"{delta(r.capacity, r0.capacity, good_up=True)} vs 2026 · " + ("existing + confirmed new" if area is None else "share residents can reach"), s.capacity, MINT),
                 (YELLOW_BG, "alert", "#B88A00", "Estimated gap" if area is not None else "Sum of area shortfalls", fmt(max(r.gap, 0) if not pd.isna(r.gap) else np.nan, ""), u,
                  f"{delta(r.gap, r0.gap, u, pct=False)} vs 2026 · " + (f"net Singapore gap {max(r.net, 0):,.0f}" if area is None and ss.cluster == "All Singapore" and not pd.isna(r.net) else "vs today's average provision"),
                  s.gap.clip(lower=0), "#E7B416"),
                 (BLUE_BG, "users", BLUE, f"Residents 65+ in {yr}", fmt(r.pop65, ""), "", f"{delta(r.pop65, r0.pop65)} vs 2026 · {where}", s.pop65, BLUE)]
    html = ""
    for bg, ic, ic_col, label, v, unit, note, vals, sc in tiles:
        st_html = strip(vals.values, sc, yr) if vals is not None else ""
        html += (f'<div class="kt"><div class="top"><div class="ic" style="background:{bg}">{icon(ic, ic_col, 18)}</div>'
                 f'<div class="l">{label}</div></div><div class="mid"><div class="v">{v}<small>{unit}</small></div>{st_html}</div>'
                 f'<div class="d">{note}</div></div>')
    st.markdown(f'<div class="kgrid" style="height:{H_TOP}px">{html}</div>', unsafe_allow_html=True)


# ------------------------------------------------------------------ charts
def base_layout(fig, h, ytitle, r=130):
    fig.update_layout(height=h, margin=dict(l=6, r=r, t=6, b=6), plot_bgcolor="white", paper_bgcolor="white",
                      font=dict(family="Inter", color=INK, size=12), showlegend=False, hovermode="x unified",
                      xaxis=dict(showgrid=False, tickmode="linear", dtick=1, linecolor="#D9D4CC", tickfont=dict(size=12), range=[2025.8, 2031.2]),
                      yaxis=dict(gridcolor="#F1ECE4", zeroline=False, title=ytitle, rangemode="tozero"))
    return fig


def outlook_chart(area=None, h=290):
    sv = ss.service
    hs = "hsg" if ss.prevention else "no_hsg"
    cur = series(sv, area)
    lo, hi = series(sv, area, f"optimistic|{hs}"), series(sv, area, f"pessimistic|{hs}")
    yrs = list(cur.index)
    fig = go.Figure()
    if sv == "primary":
        if not np.isfinite(cur.gap.to_numpy(dtype=float)).any():
            fig.add_annotation(text="No planning data is available for this selection.", showarrow=False)
            return base_layout(fig, h, "seniors 65+")
        fig.add_trace(go.Scatter(x=yrs, y=cur.gap, mode="lines+markers", line=dict(color=CORAL, width=3), marker=dict(size=7),
                                 name="Far from care", hovertemplate="%{y:,.0f} seniors"))
        last_gap = safe_last_value(cur.gap)
        fig.add_annotation(x=yrs[-1], y=last_gap, xanchor="left", xshift=10, showarrow=False, align="left",
                           text=f"<b>{fmt(last_gap, '')}</b><br>seniors far<br>from care", font=dict(color=CORAL, size=12))
        return base_layout(fig, h, "seniors 65+")
    need_values = pd.concat([cur.need, lo.need, hi.need]).dropna()
    capacity_values = cur.capacity.dropna()
    if need_values.empty or capacity_values.empty:
        fig.add_annotation(text="No planning data is available for this selection.", showarrow=False)
        return base_layout(fig, h, unit_short(sv)), np.nan
    fig.add_trace(go.Scatter(x=yrs + yrs[::-1], y=list(hi.need) + list(lo.need[::-1]), fill="toself", mode="lines",
                             fillcolor="rgba(124,106,230,0.10)", line=dict(width=0), hoverinfo="skip", name="Scenario range"))
    fig.add_trace(go.Scatter(x=yrs, y=cur.capacity, mode="lines+markers", line=dict(color=MINT, width=3), marker=dict(size=7),
                             name="Capacity", hovertemplate="%{y:,.0f}"))
    fig.add_trace(go.Scatter(x=yrs, y=cur.need, mode="lines+markers", line=dict(color=CORAL, width=3), marker=dict(size=7),
                             fill="tonexty", fillcolor="rgba(239,91,76,0.10)", name="Need", hovertemplate="%{y:,.0f}"))
    u = unit_short(sv)
    yr = int(ss.year)
    ln, lc, gp = cur.need[yr], cur.capacity[yr], max(cur.gap[yr], 0)
    fig.add_vline(x=yr, line=dict(color="#C9C2B8", width=1, dash="dot"))
    fig.add_annotation(x=yr, y=max(ln, lc), yshift=26, showarrow=False, bgcolor="white", bordercolor=LINE, borderwidth=1, borderpad=6,
                       text=f"<b>{yr}</b>  need <b style='color:{CORAL}'>{ln:,.0f}</b> · capacity <b style='color:{MINT}'>{lc:,.0f}</b>",
                       font=dict(size=12, color=INK), xanchor="right" if yr >= 2030 else "center")
    last_need, last_capacity = safe_last_value(cur.need), safe_last_value(cur.capacity)
    fig.add_annotation(x=yrs[-1], y=last_need, xanchor="left", xshift=10, showarrow=False,
                       text=f"<b>Need {fmt(last_need, '')}</b>", font=dict(color=CORAL, size=12))
    fig.add_annotation(x=yrs[-1], y=last_capacity, xanchor="left", xshift=10, showarrow=False,
                       text=f"<b>Capacity {fmt(last_capacity, '')}</b>", font=dict(color=MINT, size=12))
    lo_v = min(need_values.min(), capacity_values.min())
    hi_v = max(need_values.max(), capacity_values.max())
    pad = (hi_v - lo_v) * 0.12 + 1
    fig = base_layout(fig, h, u)
    fig.update_yaxes(range=[max(0, lo_v - pad * 2), hi_v + pad * 2.2], rangemode="normal")
    return fig, gp


def mini_chart(sv, area=None, h=92):
    s = series(sv, area)
    fig = go.Figure()
    if sv == "primary":
        fig.add_trace(go.Scatter(x=s.index, y=s.gap, mode="lines", line=dict(color=CORAL, width=2.5), fill="tozeroy",
                                 fillcolor="rgba(239,91,76,0.10)", hovertemplate="%{x}: %{y:,.0f}<extra></extra>"))
    else:
        fig.add_trace(go.Scatter(x=s.index, y=s.capacity, mode="lines", line=dict(color=MINT, width=2.5), hovertemplate="%{x}: capacity %{y:,.0f}<extra></extra>"))
        fig.add_trace(go.Scatter(x=s.index, y=s.need, mode="lines", line=dict(color=CORAL, width=2.5), fill="tonexty",
                                 fillcolor="rgba(239,91,76,0.10)", hovertemplate="%{x}: need %{y:,.0f}<extra></extra>"))
    fig.update_layout(height=h, margin=dict(l=0, r=0, t=4, b=0), plot_bgcolor="white", paper_bgcolor="white", showlegend=False,
                      xaxis=dict(visible=False), yaxis=dict(visible=False))
    vals = pd.concat([s.gap] if sv == "primary" else [s.need, s.capacity])
    if vals.dropna().empty:
        fig.add_annotation(text="No planning data is available for this selection.", showarrow=False)
        return fig
    lo, hi = float(vals.min()), float(vals.max())
    pad = (hi - lo) * 0.15 + 1
    fig.update_yaxes(range=[lo - pad, hi + pad])
    if sv == "primary":
        fig.data[0].fill = None
    return fig


def geo_layout(fig, h, lon_range=None, lat_range=None):
    geo = dict(visible=False, projection=dict(type="mercator"), bgcolor="rgba(0,0,0,0)")
    if lon_range:
        geo.update(lonaxis=dict(range=lon_range), lataxis=dict(range=lat_range))
    else:
        geo.update(fitbounds="locations")
    fig.update_layout(geo=geo, height=h, margin=dict(l=0, r=0, t=0, b=0), showlegend=False,
                      paper_bgcolor="rgba(0,0,0,0)", dragmode=False)
    return fig


def priority_map(y, top, h):
    """One choropleth trace (the boundaries are sent once, not once per colour class) + the numbered Top 5."""
    cls = gap_classes(y)
    ranked = set(D["priorities"].pa_key)
    g = y.set_index("pa_key")
    order = list(GAP_COLORS) + ["Outside"]
    colors = list(GAP_COLORS.values()) + ["#F3EFE9"]
    keys, z, txt = [], [], []
    for k in META.index:
        c = cls.get(k, "No gap") if k in ranked else "Not ranked"
        if ss.cluster != "All Singapore" and META.cluster.get(k) != ss.cluster:
            c = "Outside"
        keys.append(k)
        z.append(order.index(c))
        txt.append(f"<b>{NAME[k]}</b><br>" + (f"Gap {g.gap[k]:,.0f} {unit_short(ss.service)} · click to open" if k in g.index
                                              else ("Outside selected cluster" if c == "Outside" else "Not ranked (few residents)")))
    n = len(order) - 1
    scale = [[i / n, col] for i, col in enumerate(colors)]
    fig = go.Figure(go.Choropleth(geojson=D["geojson"], locations=keys, z=z, zmin=0, zmax=n, colorscale=scale, showscale=False,
                                  marker_line_color="white", marker_line_width=1.1, text=txt, hovertemplate="%{text}<extra></extra>"))
    t = top.head(5)
    fig.add_trace(go.Scattergeo(lat=t.pa_key.map(META.lat), lon=t.pa_key.map(META.lon), mode="markers+text",
                                marker=dict(size=25, color="#D93B2B", line=dict(color="white", width=2)),
                                text=[str(i + 1) for i in range(len(t))], textfont=dict(color="white", size=13, family="Nunito"),
                                hovertext=t.planning_area, hoverinfo="text", customdata=t.pa_key.tolist()))
    return geo_layout(fig, h, [103.40, 104.06], [1.225, 1.475])


def legend_html():
    items = "".join(f'<span><i style="background:{c}"></i>{k}</span>' for k, c in GAP_COLORS.items())
    return f'<div class="lg">{items}<span><i style="background:#D93B2B;border-radius:50%"></i>Top 5</span></div>'


def area_map(pa, h):
    sv = ss.service
    f = facilities_data()
    shown = f[
        (f.service == sv)
        | (f.status != "existing")
        | ((sv == "primary") & (f.service == "primary_gp"))
    ]
    geom = D["geom"][pa]
    rings = [geom["coordinates"][0]] if geom["type"] == "Polygon" else [p[0] for p in geom["coordinates"]]
    pts = np.vstack([np.array(r) for r in rings])
    lon_min, lon_max = float(pts[:, 0].min()), float(pts[:, 0].max())
    lat_min, lat_max = float(pts[:, 1].min()), float(pts[:, 1].max())
    lon0, lat0 = (lon_min + lon_max) / 2, (lat_min + lat_max) / 2
    nearby_lon = [lon_min - 0.04, lon_max + 0.04]
    nearby_lat = [lat_min - 0.04, lat_max + 0.04]
    near = shown[shown.lon.between(*nearby_lon) & shown.lat.between(*nearby_lat)]
    map_lon_min = min(lon_min, float(near.lon.min())) if len(near) else lon_min
    map_lon_max = max(lon_max, float(near.lon.max())) if len(near) else lon_max
    map_lat_min = min(lat_min, float(near.lat.min())) if len(near) else lat_min
    map_lat_max = max(lat_max, float(near.lat.max())) if len(near) else lat_max
    lon_pad = max((map_lon_max - map_lon_min) * 0.10, 0.004)
    lat_pad = max((map_lat_max - map_lat_min) * 0.10, 0.004)
    lon_r = [map_lon_min - lon_pad, map_lon_max + lon_pad]
    lat_r = [map_lat_min - lat_pad, map_lat_max + lat_pad]
    lon0 = (map_lon_min + map_lon_max) / 2
    lat0 = (map_lat_min + map_lat_max) / 2
    fig = go.Figure()
    fig.add_trace(go.Choropleth(geojson=D["geojson"], locations=list(META.index), z=[0] * len(META),
                                colorscale=[[0, "#F6F2EC"], [1, "#F6F2EC"]], showscale=False, marker_line_color="#E3DCD1",
                                marker_line_width=0.8, hoverinfo="skip"))
    fig.add_trace(go.Choropleth(geojson=D["geojson"], locations=[pa], z=[1], colorscale=[[0, "#FFD9D2"], [1, "#FFD9D2"]],
                                showscale=False, marker_line_color=CORAL, marker_line_width=3, hoverinfo="skip"))
    styles = {
        "existing": (BLUE, 14),
        "announced with year": ("#F08C28", 17),
        "announced, no year": (LAV, 17),
        "reference only": (YELLOW, 16),
    }
    for stt, (col, size) in styles.items():
        s_ = near[near.status == stt]
        if sv == "primary" and stt == "existing":
            gp = s_[s_.service == "primary_gp"]
            gp_hover = gp.apply(
                lambda r: f"<b>{r.facility}</b><br>Service: {r.service_label}<br>"
                          "Status: Operating<br>Bed/place capacity: location only",
                axis=1,
            )
            fig.add_trace(go.Scattergeo(
                lat=gp.lat, lon=gp.lon, mode="markers",
                marker=dict(size=6, color=BLUE),
                customdata=gp_hover.to_numpy().reshape(-1, 1),
                hovertemplate="%{customdata[0]}<extra></extra>",
            ))
            s_ = s_[s_.service != "primary_gp"]
        if len(s_):
            capacities = pd.to_numeric(s_.capacity, errors="coerce")
            capacity_labels = []
            for row, value in zip(s_.itertuples(), capacities):
                if pd.isna(value):
                    basis = row.capacity_basis if pd.notna(row.capacity_basis) else "Not published"
                    capacity_labels.append(str(basis))
                elif row.service == "primary":
                    capacity_labels.append("1 location")
                elif row.service == "hospital_reference":
                    capacity_labels.append("Not published")
                else:
                    capacity_labels.append(f"{value:,.0f} {unit_short(row.service)}")
            capacity_labels = pd.Series(capacity_labels, index=s_.index)
            hover = s_.apply(
                lambda r: (
                    f"<b>{r.facility}</b><br>Service: {r.service_label}<br>"
                    f"Status: {('Operating' if r.status == 'existing' else 'Hospital project · reference only' if r.status == 'reference only' else r.status.title())}"
                    f"{f' · opens {int(r.open_year)}' if r.status != 'existing' and pd.notna(r.open_year) and r.open_year else ''}<br>"
                    f"Bed/place capacity: {capacity_labels.loc[r.name]}"
                ),
                axis=1,
            )
            fig.add_trace(go.Scattergeo(lat=s_.lat, lon=s_.lon, mode="markers",
                                        customdata=hover.to_numpy().reshape(-1, 1),
                                        hovertemplate="%{customdata[0]}<extra></extra>",
                                        marker=dict(size=size, color=col, line=dict(color="white", width=2),
                                                    symbol="circle" if stt == "existing" else "diamond")))
    fig.add_trace(go.Scattergeo(lat=[lat0], lon=[lon0], mode="text", text=[f"<b>{NAME[pa]}</b>"],
                                textfont=dict(size=16, color=NAVY, family="Nunito"), hoverinfo="skip"))
    return geo_layout(fig, h, lon_r, lat_r), near


def area_facility_legend(facilities):
    styles = [
        ("existing", BLUE, "Existing Facilities"),
        ("announced with year", "#F08C28", "Pipeline (Confirmed Timeline)"),
        ("announced, no year", LAV, "Pipeline (Under Planning)"),
        ("reference only", YELLOW, "Major Hospital Development"),
    ]
    present = set(facilities.status) if not facilities.empty else set()
    items = "".join(
        f'<span><i style="background:{color};{("border-radius:50%;" if status == "existing" else "")}"></i>{label}</span>'
        for status, color, label in styles if status in present
    )
    return f'<div class="lg" style="margin-bottom:4px">{items}</div>' if items else ""


def step_chip(step, reason=""):
    s = str(step)
    l = s.lower()
    if "verify" in l or "check" in l:
        c = chip(s, YELLOW_BG, "#8A6A00")
    elif "assess" in l:
        c = chip(s, CORAL_BG, "#C23B2D")
    elif "study" in l:
        c = chip(s, LAV_BG, "#5B4BC4")
    else:
        c = chip(s, MINT_BG, "#0E7A5B")
    return f'<span title="{reason}">{c}</span>' if reason else c


def short_from(v):
    """year a shortfall first appears (2026 = already today)."""
    if v is None or pd.isna(v):
        return "No gap by 2031"
    return "Already today" if int(float(v)) <= 2026 else f"From {int(float(v))}"


def robust_text(share):
    if share is None or pd.isna(share):
        return "—"
    if share >= 0.95:
        return "Top 5 in all tests"
    if share >= 0.8:
        return "Top 5 in most tests"
    if share >= 0.6:
        return "Top 5 in many tests"
    return "Sensitive to assumptions"


def open_area(k):
    if k in set(D["priorities"].pa_key):
        ss.selected_area = k
        ss.nav_page = "Area"
        ss.area = k
        ss.page = "Area planning"


def select_overview_area(k):
    if k in set(META.index):
        ss.selected_area = k


def on_map_select():
    ev = ss.get("pmap")
    pts = (ev or {}).get("selection", {}).get("points", []) if isinstance(ev, dict) else getattr(getattr(ev, "selection", None), "points", [])
    for p in pts or []:
        k = p.get("location") or (p.get("customdata")[0] if isinstance(p.get("customdata"), list) else p.get("customdata"))
        if k:
            select_overview_area(k)
            return


def service_rows(area=None):
    """compact rows for the services not currently shown: mini chart + key numbers + switch button."""
    yr = int(ss.year)
    pr = D["priorities"]
    for sv in [x for x in SERVICE_ORDER if x != ss.service]:
        s = series(sv, area)
        u = unit_short(sv)
        gap, gap0 = max(s.gap[yr], 0), max(s.gap[2026], 0)
        if area is None:
            t = top_list(sv)
            k2, v2 = "Review first", safe_first_row(t, {"planning_area": "—"}).planning_area
        else:
            p = pr[(pr.scenario_id == sid()) & (pr.service == sv)]
            rk = p.set_index("pa_key")["rank"].get(area)
            k2, v2 = "Rank", (f"{int(rk)} of {len(p)}" if rk is not None and not pd.isna(rk) else "not ranked")
        with st.container(key=f"svcrow_{sv}"):
            c1, c2, c3 = st.columns([1.25, 1, 1.05], vertical_alignment="center")
            c1.markdown(f'<div class="nun" style="font-weight:800;font-size:15.5px;color:{NAVY};display:flex;gap:8px;align-items:center">'
                        f'{icon(SERVICE_ICON[sv], NAVY, 18)} {SVC.label[sv]}</div>'
                        f'<div class="kv" style="border:none;padding:4px 0 0"><span>{"Far from care" if sv == "primary" else f"Gap {yr}"}</span>'
                        f'<b style="color:{CORAL}">{gap:,.0f} {u}</b></div>'
                        f'<div class="kv" style="border:none;padding:2px 0 0"><span>{k2}</span><b>{v2}</b></div>', unsafe_allow_html=True)
            c2.plotly_chart(mini_chart(sv, area, h=70), use_container_width=True, config={"displayModeBar": False, "staticPlot": True},
                            key=f"mc_{sv}_{area}")
            with c3:
                st.markdown(f'<div style="font-size:12.5px;color:{MUTED};text-align:right">vs 2026 {delta(gap, gap0, u, pct=False)}</div>',
                            unsafe_allow_html=True)
                st.button("Show  →", key=f"sw_{sv}", on_click=lambda v=sv: ss.update(service=v), use_container_width=True)


def all_services_html():
    """Areas in the Top 5 of any service, with their rank for every service (2031 outlook, current scenario)."""
    pr = D["priorities"]
    pr = in_cluster(pr[pr.scenario_id == sid()].copy())
    pr["rk"] = pr.groupby("service")["gap_2031"].rank(ascending=False, method="first")
    top = pr[pr.rk <= 5]
    if not len(top):
        return ""
    order = top.groupby("pa_key").agg(n=("rk", "size"), best=("rk", "min")).sort_values(["n", "best"], ascending=[False, True]).head(8)
    rk = pr.set_index(["pa_key", "service"]).rk
    head = "".join(f'<th style="text-align:center">{icon(SERVICE_ICON[sv], NAVY, 15)}<div style="font-size:11px">{SVC.label[sv].split(" ")[0]}</div></th>'
                   for sv in SERVICE_ORDER)
    rows = ""
    for k, r in order.iterrows():
        cells = ""
        for sv in SERVICE_ORDER:
            v = rk.get((k, sv))
            if v is None or pd.isna(v):
                cells += '<td style="text-align:center;color:#C9C2B8">·</td>'
                continue
            bg, fg = (CORAL, "white") if v <= 5 else (("#FBD3C8", "#B4432F") if v <= 10 else ("#F5F1EA", MUTED))
            cells += (f'<td style="text-align:center;padding:5px"><span style="display:inline-block;min-width:26px;border-radius:8px;'
                      f'padding:2px 6px;background:{bg};color:{fg};font-weight:700;font-size:12.5px">{int(v)}</span></td>')
        rows += f'<tr><td class="area" style="font-size:14px;padding:5px 8px">{NAME[k]}</td>{cells}<td class="r" style="font-size:12.5px;color:{MUTED}">{int(r.n)} of 4</td></tr>'
    return (f'<div style="color:{MUTED};font-size:13px;margin-bottom:6px">Areas in the Top 5 of any service — rank per service, 2031 outlook. '
            f'Areas short in several services are candidates for joint planning.</div>'
            f'<table class="tb"><tr><th>Area</th>{head}<th class="r">Top 5 in</th></tr>{rows}</table>')


def coverage_html(area=None):
    yr = int(ss.year)
    html = (f'<div class="cap" style="color:{MUTED};font-size:13px;margin-bottom:10px">Reachable capacity ÷ need in {yr} · '
            f'{NAME[area] if area else ("Singapore" if ss.cluster == "All Singapore" else ss.cluster)}</div>')
    for sv in SERVICE_ORDER:
        s = series(sv, area).loc[yr]
        if sv == "primary":
            pct = 1 - s.gap / s.pop65 if s.pop65 else np.nan
            lab, note = "Seniors within 1 km of care", f"{s.gap:,.0f} of {s.pop65:,.0f} seniors live further"
        else:
            pct = s.capacity / s.need if s.need else np.nan
            lab, note = SVC.label[sv], f"{s.capacity:,.0f} of {s.need:,.0f} {unit_short(sv)} needed"
        p = 0 if pd.isna(pct) else float(np.clip(pct, 0, 1))
        col = MINT if p >= .95 else ("#F2A93B" if p >= .8 else CORAL)
        html += (f'<div class="pb"><div class="h"><span>{lab}</span><b>{"—" if pd.isna(pct) else f"{min(pct, 9.99):.0%}"}</b></div>'
                 f'<div class="bar"><span style="width:{p * 100:.0f}%;background:{col}"></span></div><div class="n">{note}</div></div>')
    return html


def waits_html(area=None):
    w = waits()
    if w is None:
        return f'<div class="note" style="background:#FFFCF8;color:{MUTED}">No polyclinic wait-time data is available.</div>'
    if area is not None:
        if waits_for_area(area).empty:
            return f'<div class="note" style="background:#FFFCF8;color:{MUTED}">No polyclinic wait-time data for {NAME[area]}.</div>'
        w = nearest_polyclinics(area, 5)
        cap = f"Nearest 5 polyclinics to {NAME[area]}"
    else:
        w = (in_cluster(w) if "pa_key" in w.columns else w).sort_values("consult_p95_min", ascending=False).head(6)
        cap = "Busiest polyclinics"
    if w.empty:
        return f'<div class="note" style="background:#FFFCF8;color:{MUTED}">No polyclinic wait-time data is available.</div>'
    mx = float(w.consult_p95_min.max())
    mx = mx if mx > 0 else 1
    rows = "".join(
        f'<tr><td class="area">{q.polyclinic.replace(" Polyclinic", "")}' + (f' <span style="color:{MUTED};font-size:12px">{q.km:.1f} km</span>' if area is not None else "") +
        f'</td><td class="r">{int(q.consult_p50_min)} min</td>'
        f'<td style="width:36%"><div class="pb" style="margin:0"><div class="bar"><span style="width:{100 * q.consult_p95_min / mx:.0f}%;background:{CORAL if q.consult_p95_min >= 60 else "#F2A93B"}"></span></div></div></td>'
        f'<td class="r gap">{int(q.consult_p95_min)} min</td></tr>' for q in w.itertuples())
    return (f'<div style="color:{MUTED};font-size:13px;margin-bottom:6px">{cap} · time to see a doctor, MOH Aug 2026</div>'
            f'<table class="tb"><tr><th>Polyclinic</th><th class="r">Usual</th><th></th><th class="r">Busy times</th></tr>{rows}</table>')


def latest_status(pa, sv):
    rv, _ = current_reviews()
    if not len(rv):
        return None
    m = rv[(rv.pa_key == pa) & (rv.service == sv)]
    if len(m) and "created_at" in m:
        m = m.assign(_created=pd.to_datetime(m.created_at, errors="coerce", utc=True))
        m = m.sort_values("_created", ascending=False).drop(columns="_created")
    return safe_first_row(m, {"status": None})["status"]


def render_top5_rows(top, yr, u, sv):
    rows = top.head(5)
    what = "ranked by seniors living far from care" if sv == "primary" else f"ranked by estimated gap in {yr}"
    st.markdown(
        f'<div style="color:{MUTED};font-size:13px;margin-bottom:6px">{what} · unit: {u} · next step from the 2031 outlook</div>',
        unsafe_allow_html=True,
    )
    for rank, (_, row) in enumerate(rows.iterrows(), start=1):
        status = latest_status(row.pa_key, sv)
        status_pill = (
            f'<span style="display:inline-flex;background:{CORAL_BG};color:#C23B2D;border-radius:999px;'
            f'padding:2px 8px;font-size:11px;font-weight:700;margin-left:7px">{status}</span>'
            if status else ""
        )
        current_gap = fmt(max(row.gap_now, 0) if not pd.isna(row.gap_now) else np.nan, "")
        projected_gap = fmt(max(row.gap, 0) if not pd.isna(row.gap) else np.nan, "")
        st.markdown(
            f'<div style="display:grid;grid-template-columns:34px minmax(0,1fr) auto auto;gap:8px;'
            f'align-items:center;padding:7px 8px;border-bottom:1px solid #F5F1EA;'
            f'{"background:#FFF4F1;" if rank == 1 else ""}">'
            f'<span style="display:inline-flex;width:26px;height:26px;border-radius:50%;background:{CORAL};color:white;'
            f'align-items:center;justify-content:center;font-weight:800;font-family:Nunito;font-size:13px">{rank}</span>'
            f'<div><div style="font-family:Nunito;font-weight:800;font-size:14px;color:{NAVY}">{row.planning_area}{status_pill}</div>'
            f'<div style="font-size:11.5px;color:{MUTED};margin-top:2px">{short_from(row.gap_start)} · '
            f'{step_chip(row.next_step, row.reason)}</div></div>'
            f'<span style="font-size:12px;color:{MUTED};white-space:nowrap">{current_gap} now</span>'
            f'<span style="font-family:Nunito;font-weight:900;font-size:15px;color:{CORAL};white-space:nowrap">{projected_gap}'
            f'<small style="font-size:10.5px;color:{MUTED};font-weight:600">'
            f' {u}</small></span></div>',
            unsafe_allow_html=True,
        )


# ------------------------------------------------------------------ page 1: investment overview
def page_overview():
    header("Where to prioritise community care", "Five-year planning view for regional healthcare teams")
    yr, sv, u = int(ss.year), ss.service, unit_short(ss.service)
    top = top_list()
    if ss.get("selected_area") not in set(META.index):
        ss.selected_area = top.iloc[0].pa_key if not top.empty else None

    c1, c2 = st.columns([5, 7])
    with c1:
        kpi_tiles()
    with c2:
        with st.container(border=True, height=H_TOP, key="card_outlook"):
            title = "How many seniors live far from care?" if sv == "primary" else "When does the gap open up?"
            leg = (f'<div class="lg"><span><i style="background:{CORAL}"></i>Need</span><span><i style="background:{MINT}"></i>Capacity</span>'
                   f'<span><i style="background:rgba(124,106,230,.25)"></i>Scenario range</span></div>') if sv != "primary" else \
                  f'<div class="lg"><span><i style="background:{CORAL}"></i>Seniors 65+ > 1 km from a polyclinic or CHAS GP</span></div>'
            st.markdown(card_title("trend", CORAL, title, f"{SVC.label[sv]} · {'Singapore' if ss.cluster == 'All Singapore' else ss.cluster} · {PRESET_LABEL[preset()]} scenario",
                                   right=leg), unsafe_allow_html=True)
            fig = outlook_chart(h=H_TOP - 78)
            st.plotly_chart(fig[0] if isinstance(fig, tuple) else fig, use_container_width=True, config={"displayModeBar": False})

    c3, c4 = st.columns([7, 5])
    with c3:
        with st.container(border=True, height=H_MAIN, key="cardmap"):
            st.markdown(card_title("pin", CORAL, "Priority map", f"{SVC.label[sv]} · gap in {yr} · {PRESET_LABEL[preset()]} scenario",
                                   right=legend_html()), unsafe_allow_html=True)
            st.plotly_chart(priority_map(top, top, H_MAIN - 78), use_container_width=True, key="pmap",
                            on_select=on_map_select, selection_mode="points",
                            config={"displayModeBar": False, "scrollZoom": False})
            if top.empty:
                st.info(f"No priority data is available for {SVC.label[sv]} in this service area and scenario.")
            else:
                selected_area = ss.get("selected_area")
                area_row = series(sv, selected_area)
                selected_priority = D["priorities"][
                    (D["priorities"].scenario_id == sid())
                    & (D["priorities"].service == sv)
                    & (D["priorities"].pa_key == selected_area)
                ]
                selected_priority_row = safe_first_row(selected_priority, {})
                gap_now = safe_first_value(area_row.gap.reindex([2026]), np.nan)
                gap = safe_first_value(area_row.gap.reindex([yr]), np.nan)
                selected_rank = top.index[top.pa_key == selected_area]
                rank_label = str(int(selected_rank[0]) + 1) if len(selected_rank) else "•"
                next_step = selected_priority_row.get("next_step", "Monitor demand growth")
                reason = selected_priority_row.get("next_step_reason", "")
                gap_start = selected_priority_row.get("gap_start")
                if selected_area is not None and facilities_for_area(selected_area).empty:
                    st.info(f"No facility data for {NAME[selected_area]} in facilities_v2.")
                with st.container(key="pop"):
                    st.markdown(f'<div style="display:flex;align-items:center;gap:8px"><span style="display:inline-flex;width:24px;height:24px;border-radius:50%;background:{CORAL};color:white;align-items:center;justify-content:center;font-weight:800;font-size:12px">{rank_label}</span>'
                                f'<span class="nun" style="font-weight:900;font-size:17px;color:{NAVY}">{NAME[selected_area] if selected_area else "No area selected"}</span></div>'
                                f'<div class="kv"><span>{"Far from care" if sv == "primary" else f"Gap {yr}"}</span><b style="color:{CORAL}">{fmt(max(gap, 0) if not pd.isna(gap) else np.nan, "")} {u}</b></div>'
                                f'<div class="kv"><span>Gap today</span><b>{("—" if pd.isna(gap_now) else f"{max(gap_now, 0):,.0f}")} {u}</b></div>'
                                f'<div class="kv"><span>Short from</span><b>{short_from(gap_start)}</b></div>'
                                f'<div style="margin:6px 0 8px">{step_chip(next_step, reason)}</div>', unsafe_allow_html=True)
                    st.button("Inspect area  →", type="primary", use_container_width=True, on_click=open_area, args=(selected_area,), key="inspect")
                    st.markdown(f'<div style="font-size:11.5px;color:{MUTED};text-align:center">or click any area on the map</div>', unsafe_allow_html=True)
    with c4:
        with st.container(border=True, height=H_MAIN, key="card_tabs"):
            t1, t2, t3, t4 = st.tabs(["Top 5 areas", "All services", "Polyclinic waits", "Coverage"])
            with t1:
                if top.empty:
                    st.info("No ranked areas are available for the current selection.")
                else:
                    render_top5_rows(top, yr, u, sv)
                    st.markdown(f'<div class="foot" style="margin-top:6px">{icon("info", MUTED, 13)} {SVC.confidence[sv]}. Gaps compare need with today\'s '
                                f'Singapore average provision — not observed unmet need.</div>', unsafe_allow_html=True)
            with t2:
                st.markdown(all_services_html(), unsafe_allow_html=True)
            with t3:
                w = waits()
                visible_waits = in_cluster(w) if w is not None and "pa_key" in w.columns else w
                if visible_waits is None or visible_waits.empty:
                    st.info("No polyclinic wait-time data is available for this service area.")
                else:
                    st.markdown(waits_html(), unsafe_allow_html=True)
            with t4:
                st.markdown(coverage_html(), unsafe_allow_html=True)


# ------------------------------------------------------------------ page 2: area planning
def area_services_html(pa):
    """All four services in one area: the cross-service view only the Area page has."""
    yr = int(ss.year)
    pr = D["priorities"]
    pr = pr[pr.scenario_id == sid()]
    rows = ""
    for sv in SERVICE_ORDER:
        s = series(sv, pa)
        u = unit_short(sv)
        p = pr[(pr.service == sv) & (pr.pa_key == pa)]
        p_row = safe_first_row(p, {})
        p = p_row if len(p) else None
        rk = f"{int(p['rank'])}/{len(pr[pr.service == sv])}" if p is not None else "—"
        hot = p is not None and p["rank"] <= 5
        sel = sv == ss.service
        rows += (f'<tr style="{"background:#EEF4FF" if sel else ""}"><td><div style="display:flex;gap:8px;align-items:center" class="area">'
                 f'{icon(SERVICE_ICON[sv], BLUE if sel else NAVY, 17)} {SVC.label[sv]}</div></td>'
                 f'<td class="r" style="color:{MUTED}">{max(s.gap[2026], 0):,.0f}</td>'
                 f'<td class="r gap" style="color:{CORAL if s.gap[yr] > 0.5 else MINT}">{max(s.gap[yr], 0):,.0f} <span style="font-size:11px;color:{MUTED};font-weight:600">{u}</span></td>'
                 f'<td style="font-size:13px">{short_from(p["gap_start"]) if p is not None else "—"}</td>'
                 f'<td class="r"><span class="chip" style="background:{CORAL_BG if hot else "#F5F1EA"};color:{"#C23B2D" if hot else MUTED}">{rk}</span></td>'
                 f'<td>{step_chip(p["next_step"], p.get("next_step_reason", "")) if p is not None else ""}</td></tr>')
    return (f'<table class="tb"><tr><th>Service</th><th class="r">Gap now</th><th class="r">Gap {yr}</th><th>Short from</th>'
            f'<th class="r">2031 rank</th><th>Suggested next step</th></tr>{rows}</table>')


def reviewer():
    try:
        h = st.context.headers
        return h.get("X-Forwarded-Email") or h.get("X-Forwarded-Preferred-Username") or "local tester"
    except Exception:
        return "local tester"


@st.cache_data(ttl=30, show_spinner=False)
def reviews():
    try:
        return backend.load_reviews(), None
    except Exception as e:  # never let the write-back store break the planning view
        return pd.DataFrame(columns=["pa_key", "service", "status", "owner", "note", "reviewer", "created_at"]), str(e)[:160]


def current_reviews():
    decisions, error = reviews()
    in_session = ss.get("decisions", [])
    if in_session:
        store_status = decisions.attrs.get("store_status")
        decisions = pd.concat([decisions, pd.DataFrame(in_session)], ignore_index=True)
        decisions = decisions.drop_duplicates(subset=backend.DECISION_COLUMNS, keep="last")
        decisions.attrs["store_status"] = store_status
    return decisions, error


def policy_recommendation(pa, sv, area_series, population, status=None):
    projected_gap = safe_first_value(area_series["gap"].reindex([2031]), np.nan)
    pop65_now = population.pop65.get(2026, np.nan)
    pop65_future = population.pop65.get(2031, np.nan)
    senior_growth = pop65_future - pop65_now if not pd.isna(pop65_now) and not pd.isna(pop65_future) else np.nan
    growth_pct = senior_growth / pop65_now if not pd.isna(senior_growth) and pop65_now > 0 else np.nan
    unit = unit_short(sv)
    current_gap = max(float(projected_gap), 0.0) if not pd.isna(projected_gap) else np.nan
    current_gap_text = fmt(current_gap, "")
    senior_rate = f"{growth_pct:.0%}" if not pd.isna(growth_pct) else "unavailable"
    status_text = status.strip().lower() if isinstance(status, str) else ""
    area_name = NAME[pa]
    if "expansion" in status_text:
        note = (
            f"[{area_name} - Expansion Proposal] Projected {unit} shortfall reaches "
            f"{current_gap_text} {unit} by 2031 with senior population rising by {senior_rate}. "
            "Recommend prioritizing local facility expansion before 2029 and reserving land parcels "
            "for step-down care."
        )
    elif "verified" in status_text or "assessment" in status_text:
        note = (
            f"[{area_name} - Audit Plan] Estimated gap of {current_gap_text} {unit} requires physical "
            "inventory verification. Recommend field audits across neighboring acute hospitals and "
            "cross-referencing published bed occupancy rates."
        )
    elif "monitor" in status_text or "no action" in status_text:
        note = (
            f"[{area_name} - Routine Monitoring] Current capacity meets baseline criteria through 2031. "
            "Recommend periodic tracking of polyclinic wait times and emergency transfer queues without "
            "capital expansion."
        )
    else:
        note = (
            f"[{area_name} - Baseline Overview] Current data shows a projected gap of "
            f"{current_gap_text} {unit} by 2031. Please select a planning status above to generate "
            "targeted strategic recommendations."
        )
    return note


def review_panel(pa, area_series, population, priority):
    sv = ss.service
    rv, err = current_reviews()
    mine = rv[(rv.pa_key == pa) & (rv.service == sv)] if len(rv) else rv
    if len(mine) and "created_at" in mine:
        mine = mine.assign(_created=pd.to_datetime(mine.created_at, errors="coerce", utc=True))
        mine = mine.sort_values("_created", ascending=False).drop(columns="_created")
    cur_row = safe_first_row(mine, {})
    cur = cur_row if len(mine) else None
    saved_status = cur["status"] if cur is not None else None
    status = saved_status if saved_status in backend.STATUSES else None
    display_status = status or "Not reviewed"
    recorded = cur is not None
    badge = chip("Reviewed & Recorded" if recorded else "Not reviewed", MINT_BG if recorded else "#F5F1EA",
                 "#0E7A5B" if recorded else MUTED)
    store_status = rv.attrs.get("store_status", "")
    offline = bool(err) or (
        isinstance(store_status, str) and store_status.startswith("Local decision cache")
    )
    if cur is not None:
        timestamp = pd.to_datetime(cur.get("created_at"), errors="coerce")
        recorded_at = timestamp.strftime("%Y-%m-%d %H:%M") if pd.notna(timestamp) else "time unavailable"
        owner_label = cur.get("owner") or "Unassigned"
        recorded_line = f"Decision: {display_status} · Recorded at {recorded_at} by {owner_label}"
    else:
        recorded_line = f"Decision: {display_status}"
    st.markdown(
        card_title("check", MINT, "Planning decision", f"{SVC.label[sv]} in {NAME[pa]}", right=badge),
        unsafe_allow_html=True,
    )
    st.caption(recorded_line)
    st.caption("Mode: Local cache (offline)" if offline else "Mode: Databricks + local cache")
    c1, c2 = st.columns([1.3, 1])
    status_index = backend.STATUSES.index(status) if status is not None else None
    new = c1.selectbox("Status", backend.STATUSES, index=status_index, placeholder="Select a status...",
                       key=f"decision_status_{pa}_{sv}")
    owner = c2.text_input("Owner", value="",
                          placeholder="e.g. NHG planning", key=f"decision_owner_{pa}_{sv}")
    note_key = f"note_{pa}_{sv}"
    if note_key not in ss:
        ss[note_key] = (cur.get("note") or "") if cur is not None else ""
    if st.button("✨ Generate AI Policy Proposal", key=f"generate_proposal_{pa}_{sv}_{sid()}"):
        ss[note_key] = policy_recommendation(pa, sv, area_series, population, new)
    note = st.text_area("Note", height=105, key=note_key,
                        placeholder="Add decision context or generate a policy proposal.")
    st.caption("📋 Pre-Action Verification Checklist (Human-in-the-Loop review before sign-off)")
    checklist = [
        "Operating beds / places at nearby facilities",
        "Opening year and size of announced projects",
        "Staffing to run new capacity",
    ]
    confirmations = [
        item for i, item in enumerate(checklist)
        if st.checkbox(item, key=f"decision_confirmation_{pa}_{sv}_{i}")
    ]
    if st.button("💾 Submit & Record Decision", type="primary", key=f"record_decision_{pa}_{sv}"):
        if new is None:
            st.warning("Select a status before recording the decision.")
        else:
            try:
                record = backend.save_review(pa, sv, new, owner, note, sid(), reviewer(), confirmations)
                ss.setdefault("decisions", []).append(record)
                ss["decision_recorded_success"] = True
                reviews.clear()
                st.rerun()
            except Exception as e:
                st.error(f"Could not save: {str(e)[:160]}")
    if ss.pop("decision_recorded_success", False):
        st.success("Planning decision recorded successfully!")
    session_mine = pd.DataFrame(ss.get("decisions", []))
    if not session_mine.empty:
        session_mine = session_mine[(session_mine.pa_key == pa) & (session_mine.service == sv)]
        if "created_at" in session_mine:
            session_mine = session_mine.sort_values("created_at", ascending=False)
    with st.expander("Decision Audit Trail", expanded=False):
        if session_mine.empty:
            st.caption("No decisions submitted for this area and service during this session.")
        else:
            for record in session_mine.head(2).itertuples():
                st.markdown(f"**{str(record.created_at)[:10]} · {record.reviewer}**")
                st.caption(f"{record.status}{(' · ' + record.note) if record.note else ''}")


def page_area():
    opts = list(META.index)
    if not opts:
        st.info("No planning-area data is available.")
        return
    if ss.get("area") not in opts:
        ss.area = safe_first_row(top_list(), {"pa_key": opts[0]}).pa_key
    pa = ss.area
    ss.selected_area = pa
    header(f"{NAME[pa]}: what should we do?", "One area, every service — and the decision you record", show_area=True,
           pre=f'<div class="crumb">Investment overview › <b>{NAME[pa]}</b></div>')
    pa = ss.area
    sv, yr, u = ss.service, int(ss.year), unit_short(ss.service)
    pr = D["priorities"]
    prs = pr[(pr.scenario_id == sid()) & (pr.service == sv)]
    me = prs[prs.pa_key == pa]
    me_row = safe_first_row(me, {})
    me = me_row if len(me) else None
    s = series(sv, pa)
    p = D["pop"]
    p = p[(p.pa_key == pa) & (p.ageing_scenario == {"optimistic": "low", "base": "base", "pessimistic": "high"}[preset()])].set_index("year")
    g65 = p.pop65.get(2031, np.nan) - p.pop65.get(2026, np.nan)
    p65 = p.pop65.get(2026, np.nan)
    growth_pct = g65 / p65 if not pd.isna(p65) and p65 > 0 else np.nan
    growth_text = f"{growth_pct:+.0%}" if not pd.isna(growth_pct) else "unavailable"
    gnow, gy = max(s.gap[2026], 0), max(s.gap[yr], 0)
    if sv == "primary":
        headline = (f"About <b>{gy:,.0f} seniors</b> in {NAME[pa]} live more than 1 km from a polyclinic or CHAS GP, "
                    f"while residents aged 65+ grow by <b>{fmt(g65, '')}</b> ({growth_text}) by 2031.")
    else:
        headline = (f"{NAME[pa]} needs about <b>{gy:,.0f} more {u}</b> of {SVC.label[sv].lower()} by {yr} to keep today's Singapore-average provision"
                    + (f" — it is <b>already {gnow:,.0f} short</b> today." if gnow > 0.5 else ".")
                    + f" Residents aged 65+ grow by <b>{fmt(g65, '')}</b> ({growth_text}) by 2031.")
    reason = me["next_step_reason"] if me is not None and "next_step_reason" in me.index else ""
    facts = [("Short from", short_from(me["gap_start"]) if me is not None else "—"),
             ("2031 rank", f"{int(me['rank'])} of {len(prs)}" if me is not None else "Not ranked"),
             ("Reachable capacity", "locations only" if sv == "primary" else f"{s.capacity[yr]:,.0f} of {s.need[yr]:,.0f} {u}"),
             ("Ranking robustness", robust_text(me["stability_share"]) if me is not None else "—")]

    c1, c2 = st.columns([5, 7])
    with c1:
        with st.container(border=True, height=H_TOP, key="card_decide"):
            st.markdown(card_title("target", CORAL, "What the numbers say", f"{SVC.label[sv]} · {PRESET_LABEL[preset()]} scenario") +
                        f'<div style="font-size:15px;line-height:1.45;color:{INK};margin:4px 0 8px">{headline}</div>'
                        f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:0 16px">' +
                        "".join(f'<div class="kv"><span>{k}</span><b>{v}</b></div>' for k, v in facts) + '</div>'
                        f'<div style="margin-top:8px;display:flex;gap:10px;align-items:flex-start">{step_chip(me["next_step"] if me is not None else "Monitor demand growth")}'
                        f'<span style="font-size:12.5px;color:{INK}">{reason}</span></div>', unsafe_allow_html=True)
    with c2:
        with st.container(border=True, height=H_TOP, key="card_allsvc"):
            st.markdown(card_title("users", BLUE, f"Every service in {NAME[pa]}", f"Gap at today's average provision · {yr} · highlighted = service selected above") +
                        area_services_html(pa), unsafe_allow_html=True)

    c3, c4 = st.columns([7, 5])
    with c3:
        with st.container(border=True, height=H_MAIN, key="card_amap"):
            t1, t2, t3, t4 = st.tabs(["Nearby facilities", "Five-year outlook", "Planned projects", "Polyclinic waits"])
            with t1:
                map_fig, map_facilities = area_map(pa, H_MAIN - 110)
                st.markdown(area_facility_legend(map_facilities), unsafe_allow_html=True)
                if facilities_for_area(pa).empty:
                    st.info(f"No facility data for {NAME[pa]} in facilities_v2.")
                st.plotly_chart(map_fig, use_container_width=True, config={"displayModeBar": False})
            with t2:
                fig = outlook_chart(area=pa, h=H_MAIN - 120)
                st.plotly_chart(fig[0] if isinstance(fig, tuple) else fig, use_container_width=True, config={"displayModeBar": False})
                st.caption("Need (coral) vs the share of nearby capacity residents can reach (green); purple band = optimistic to pessimistic.")
            with t3:
                f = facilities_data()
                f = f[(f.pa_key == pa) & (f.status != "existing")]
                rows = ""
                for name, g in f.groupby("facility", sort=False):
                    for r in g.itertuples():
                        if r.status == "reference only":
                            when, how = "beds not announced", chip("Not counted", "#F5F1EA", MUTED)
                        elif r.status == "announced with year":
                            when, how = f"opens {r.open_year}", chip("All scenarios", MINT_BG, "#0E7A5B")
                        else:
                            when, how = f"no year (assumed {r.open_year})", chip("Optimistic only", LAV_BG, "#5B4BC4")
                        rows += (f'<tr><td><div class="area" style="font-family:Nunito;font-weight:800;color:{NAVY}">{name}</div>'
                                 f'<div style="color:{MUTED};font-size:12.5px">{r.service_label} · {when}</div></td><td class="r">{how}</td></tr>')
                st.markdown(f'<div style="color:{MUTED};font-size:13px;margin-bottom:6px">Announced by MOH · how each one counts in the scenarios</div>'
                            f'<table class="tb">{rows}</table>' if rows else
                            f'<div class="note" style="background:#FFFCF8;color:{MUTED}">No announced projects in {NAME[pa]}.</div>', unsafe_allow_html=True)
            with t4:
                if waits_for_area(pa).empty:
                    st.info(f"No polyclinic wait-time data for {NAME[pa]}.")
                else:
                    st.markdown(waits_html(area=pa), unsafe_allow_html=True)
    with c4:
        with st.container(border=True, height=H_MAIN, key="card_review"):
            review_panel(pa, s, p, me)
    area_brief = build_area_brief(pa, sv, s, p)
    st.download_button(
        "Export Area Brief (Markdown)",
        data=area_brief,
        file_name=f"{pa}_{sv}_brief.md",
        mime="text/markdown",
        key=f"export_area_brief_{pa}_{sv}",
    )


def build_area_brief(pa, sv, area_series, population):
    u = unit_short(sv)
    need = safe_first_value(area_series["need"].reindex([2031]), np.nan)
    capacity = safe_first_value(area_series["capacity"].reindex([2031]), np.nan)
    gap_column = "gap" if sv == "primary" else "net"
    gap = safe_first_value(area_series[gap_column].reindex([2031]), np.nan)
    pop65_2026 = population.pop65.get(2026, np.nan)
    pop65_2031 = population.pop65.get(2031, np.nan)
    pop65_change = pop65_2031 - pop65_2026 if not pd.isna(pop65_2026) and not pd.isna(pop65_2031) else np.nan
    pop65_pct = pop65_change / pop65_2026 if not pd.isna(pop65_change) and pop65_2026 > 0 else np.nan

    facilities = facilities_for_area(pa)
    operating = facilities[facilities.status == "existing"]
    announced = facilities[
        ~facilities.status.isin(["existing", "reference only"])
    ]

    def facility_count(frame):
        if "facility" in frame.columns:
            return int(frame.facility.dropna().nunique())
        return len(frame)

    decisions, _ = current_reviews()
    mine = decisions[(decisions.pa_key == pa) & (decisions.service == sv)] if len(decisions) else decisions
    if len(mine):
        mine = mine.assign(_created=pd.to_datetime(mine.created_at, errors="coerce", utc=True))
        decision = mine.sort_values("_created", ascending=False).iloc[0]
        confirmations = decision.get("confirmations", [])
        if not isinstance(confirmations, list):
            confirmations = []
        confirmation_text = "\n".join(f"- [x] {item}" for item in confirmations) or "- None"
        decision_text = (
            f"- Status: {decision.get('status') or '—'}\n"
            f"- Owner: {decision.get('owner') or '—'}\n"
            f"- Note: {decision.get('note') or '—'}\n"
            f"- Timestamp: {decision.get('created_at') or '—'}\n"
            f"- Checked confirmations:\n{confirmation_text}"
        )
    else:
        decision_text = "Pending Review"

    return (
        f"# {NAME[pa]} Area Brief\n\n"
        f"- **Planning Area:** {NAME[pa]}\n"
        f"- **Service:** {SVC.label[sv]}\n\n"
        "## 2031 Projection\n"
        f"- **Projected Need:** {fmt(need, '')} {u if sv != 'primary' else '(not published for primary care)'}\n"
        f"- **Reachable Capacity:** {fmt(capacity, '')} {u if sv != 'primary' else '(locations only; capacity not published)'}\n"
        f"- **Net Gap:** {fmt(gap, '')} {u if sv != 'primary' else 'seniors living more than 1 km from care'}\n\n"
        "## Resident Population\n"
        f"- **Residents aged 65+ (2026):** {fmt(pop65_2026, '')}\n"
        f"- **Projected residents aged 65+ (2031):** {fmt(pop65_2031, '')}\n"
        f"- **Growth:** {f'{pop65_change:+,.0f}' if not pd.isna(pop65_change) else '—'} "
        f"({f'{pop65_pct:+.0%}' if not pd.isna(pop65_pct) else 'unavailable'})\n\n"
        "## Planning Decision\n"
        f"{decision_text}\n\n"
        "## Nearby Facilities\n"
        f"- **Operating facilities:** {facility_count(operating)}\n"
        f"- **Announced facilities:** {facility_count(announced)}\n"
    )


def evidence_narrative_markdown():
    """Build the original narrative flow using live base-scenario values."""
    area_year = D["area_year"]
    base_area_year = area_year[area_year.scenario_id == "base|no_hsg"]

    def area_total(service, year, column):
        rows = base_area_year[(base_area_year.service == service) & (base_area_year.year == year)]
        values = pd.to_numeric(rows[column], errors="coerce")
        return values.sum(min_count=1)

    pop = D["pop"]
    base_population = pop[(pop.ageing_scenario == "base") & pop.year.isin([2026, 2031])]

    def population_total(year):
        values = pd.to_numeric(base_population.loc[base_population.year == year, "pop65"], errors="coerce")
        return values.sum(min_count=1)

    p65_0 = population_total(2026)
    p65_1 = population_total(2031)
    p65_change = p65_1 / p65_0 - 1 if not pd.isna(p65_0) and p65_0 else np.nan
    p65_change_text = f"{p65_change:+.0%}" if not pd.isna(p65_change) else "unavailable"
    ch_change = area_total("community_hospital", 2031, "need") - area_total("community_hospital", 2026, "need")
    nh_change = area_total("nursing_home", 2031, "need") - area_total("nursing_home", 2026, "need")
    dc_change = area_total("day_care", 2031, "need") - area_total("day_care", 2026, "need")
    far = area_total("primary", 2031, "gap")
    rv, _ = current_reviews()
    pr = D["priorities"]
    done, total_top5 = backend.top5_decision_count(pr, rv)
    bedok_rows = base_area_year[
        (base_area_year.service == "community_hospital") & (base_area_year.pa_key == "BEDOK")
    ]
    bedok_today = safe_first_row(
        bedok_rows[bedok_rows.year == 2026], {"gap": np.nan}
    ).gap
    bedok_2031 = safe_first_row(
        bedok_rows[bedok_rows.year == 2031], {"gap": np.nan}
    ).gap
    if pd.isna(bedok_today) or pd.isna(bedok_2031):
        bedok_impact = "Bedok community-hospital gap data is unavailable."
    elif bedok_today > 0.5:
        bedok_impact = (f"Bedok is already short by about <b>{fmt(bedok_today, '')}</b> community-hospital beds today "
                        f"and needs about <b>{fmt(bedok_2031, '')}</b> more by 2031.")
    else:
        bedok_impact = f"Bedok needs about <b>{fmt(bedok_2031, '')}</b> more community-hospital beds by 2031."
    impact_value = lambda value: f"{value:+,.0f}" if not pd.isna(value) else "—"
    problem = (
        f"Residents aged 65+ grow from **{fmt(p65_0, '')}** to **{fmt(p65_1, '')}** "
        f"({p65_change_text}) between 2026 and 2031. At today's level of provision Singapore would need "
        f"**{impact_value(ch_change)}** community-hospital beds, **{impact_value(nh_change)}** "
        f"nursing-home beds and **{impact_value(dc_change)}** day-care places. Planners know the national "
        "total; what they lack is **where**, **which service** and **from when**."
    )
    approach = (
        "Forecast residents by planning area, age and sex (tested on five past start years) → size each service at today's "
        "Singapore-average provision → share every bed and place among the residents who can reach it → rank areas per service "
        "and test the ranking → suggest a cautious next step. One governed pipeline on Databricks feeds this App, a dashboard and Genie."
    )
    impact = (
        f"A ranked, explainable shortlist instead of a national total: {bedok_impact} "
        f"**{fmt(far, '')}** seniors live more than 1 km from subsidised primary care. Planning can start years before shortfalls show up as waiting lists."
    )
    measurement = (
        f"**Now:** share of Top 5 areas with a recorded decision — **{done} of {total_top5}** so far "
        "(saved to Databricks or the local decision cache from the Area page). **Each year:** re-run with new SingStat/MOH data "
        "and check the forecast error and whether flagged gaps narrow. **With partners:** new beds and places opened in flagged areas, "
        "polyclinic waits (MOH monthly), and acute-hospital patients waiting for step-down care in those areas."
    )
    beneficiaries = (
        "**Regional health planners** get the where / what / when in minutes instead of compiling spreadsheets. "
        "**Seniors and caregivers** get care closer to home, sooner. **Hospitals and MOH** put scarce capital and staff where the gap is "
        "largest and avoid building where capacity already keeps up."
    )
    return (
        f"### The problem\n\n{problem}\n\n"
        f"### How HealthPulse does it\n\n{approach}\n\n"
        f"### The impact\n\n{impact}\n\n"
        f"### How we measure it\n\n{measurement}\n\n"
        f"### Who benefits\n\n{beneficiaries}"
    )


def evidence_pipeline_html():
    steps = [
        ("Population to 2031", "Cohort-survival model + migration",
         "Residents age, survive at SingStat life-table rates, and each area keeps its recent pattern of people moving in or out."),
        ("Need Estimation", "MOH age-sex admission benchmarks",
         "Community-hospital beds follow expected admissions; nursing-home beds and day-care places follow residents aged 75+ at today's Singapore-average provision."),
        ("Capacity Catchment", "2-step floating catchment / Gaussian decay",
         "Share every bed or place among residents who can reach it; nearby facilities across planning boundaries count, and no bed is counted twice."),
        ("Gap Synthesis", "Reachable beds vs local need",
         "Calculate need minus reachable capacity per service and year. Primary care is shown as coverage because clinic capacity is not published."),
        ("Priority & Robustness", "Stress-tested across scenarios",
         "Rank areas within each service and test whether the Top 5 holds across scenarios and when estimated capacities are varied."),
    ]
    cards = []
    for i, (title, method, detail) in enumerate(steps, 1):
        connector = (
            f'<div style="position:absolute;left:19px;top:42px;bottom:-18px;width:2px;background:{LINE};"></div>'
            if i < len(steps) else ""
        )
        cards.append(
            f'<div style="position:relative;display:flex;gap:14px;padding:0 0 16px">'
            f'<div style="position:relative;flex:none;width:40px">{connector}'
            f'<span style="position:relative;z-index:1;display:inline-flex;width:40px;height:40px;border-radius:50%;'
            f'align-items:center;justify-content:center;background:{BLUE_BG};color:{BLUE};font-family:Nunito;font-weight:900">{i}</span></div>'
            f'<div style="flex:1;background:#FFFFFF;border:1px solid {LINE};border-radius:14px;padding:12px 16px;'
            f'box-shadow:0 1px 6px rgba(31,42,68,.04)">'
            f'<div style="font-family:Nunito;font-weight:900;font-size:16px;color:{NAVY}">{title}</div>'
            f'<div style="font-size:12.5px;font-weight:700;color:{BLUE};margin:2px 0 5px">{method}</div>'
            f'<div style="font-size:13.5px;color:{INK};line-height:1.5">{detail}</div></div></div>'
        )
    return "".join(cards)


# ------------------------------------------------------------------ page 3: evidence
def page_evidence():
    st.markdown('<div class="hp-title">View evidence</div><div class="hp-sub">Where the numbers come from and how far to trust them</div>',
                unsafe_allow_html=True)
    with st.container(border=True, height=H_TOP + H_MAIN + 14, key="card_ev"):
      t0, t1, t2, t3, t4, t5 = st.tabs(["Why HealthPulse", "How it works", "What we cannot see", "Checks", "Assumptions", "Sources & platform"])
      with t0:
          st.markdown("""
<style>
.why-section {
    margin-bottom: 22px;
}
.why-header {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 6px;
}
.why-icon {
    width: 26px;
    height: 26px;
    border-radius: 50%;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: 13px;
    font-weight: 700;
    flex-shrink: 0;
}
.why-icon-red { background-color: #FEE2E2; color: #DC2626; }
.why-icon-blue { background-color: #E0F2FE; color: #0284C7; }
.why-icon-green { background-color: #E2E8F0; color: #475569; }
.why-icon-purple { background-color: #EDE9FE; color: #7C3AED; }
.why-icon-amber { background-color: #FEF3C7; color: #D97706; }

.why-title {
    font-size: 16px;
    font-weight: 700;
    color: #111827;
}
.why-body {
    font-size: 13.5px;
    color: #4B5563;
    line-height: 1.6;
    margin-left: 38px;
}
.why-body b {
    color: #111827;
    font-weight: 700;
}
</style>

<div class="why-section">
    <div class="why-header">
        <span class="why-icon why-icon-red">🚨</span>
        <span class="why-title">The problem</span>
    </div>
    <div class="why-body">
        Residents aged 65+ grow from <b>828,720</b> to <b>986,055</b> (+19%) between 2026 and 2031. At today's level of provision Singapore would need <b>+615</b> community-hospital beds, <b>+7,266</b> nursing-home beds and <b>+3,244</b> day-care places. Planners know the national total; what they lack is <b>where</b>, <b>which service</b> and <b>from when</b>.
    </div>
</div>

<div class="why-section">
    <div class="why-header">
        <span class="why-icon why-icon-blue">⚙️</span>
        <span class="why-title">How HealthPulse does it</span>
    </div>
    <div class="why-body">
        Forecast residents by planning area, age and sex (tested on five past start years) → size each service at today's Singapore-average provision → share every bed and place among the residents who can reach it → rank areas per service and test the ranking → suggest a cautious next step. One governed pipeline on Databricks feeds this App, a dashboard and Genie.
    </div>
</div>

<div class="why-section">
    <div class="why-header">
        <span class="why-icon why-icon-green">🎯</span>
        <span class="why-title">The impact</span>
    </div>
    <div class="why-body">
        A ranked, explainable shortlist instead of a national total: Bedok is already short by about <b>63</b> community-hospital beds today and needs about <b>108</b> more by 2031. <b>14,182</b> seniors live more than 1 km from subsidised primary care. Planning can start years before shortfalls show up as waiting lists.
    </div>
</div>

<div class="why-section">
    <div class="why-header">
        <span class="why-icon why-icon-purple">📊</span>
        <span class="why-title">How we measure it</span>
    </div>
    <div class="why-body">
        <b>Now:</b> share of Top 5 areas with a recorded decision — <b>1 of 20</b> so far (saved to Databricks or the local decision cache from the Area page). <b>Each year:</b> re-run with new SingStat/MOH data and check the forecast error and whether flagged gaps narrow. <b>With partners:</b> new beds and places opened in flagged areas, polyclinic waits (MOH monthly), and acute-hospital patients waiting for step-down care in those areas.
    </div>
</div>

<div class="why-section">
    <div class="why-header">
        <span class="why-icon why-icon-amber">🌱</span>
        <span class="why-title">Who benefits</span>
    </div>
    <div class="why-body">
        <b>Regional health planners</b> get the where / what / when in minutes instead of compiling spreadsheets. <b>Seniors and caregivers</b> get care closer to home.
    </div>
</div>
""", unsafe_allow_html=True)
      with t1:
        if True:
            st.markdown(evidence_pipeline_html(), unsafe_allow_html=True)
      with t2:
        if True:
            st.markdown("""
<style>
.limitations-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 14px;
    margin-top: 10px;
    margin-bottom: 12px;
}
.limitations-card {
    background-color: #FAF7F2;
    border: 1px solid #EFEAE2;
    border-radius: 12px;
    padding: 18px 20px;
    box-sizing: border-box;
    display: flex;
    flex-direction: column;
    justify-content: flex-start;
}
.limitations-card-full {
    grid-column: span 2;
    background-color: #FAF7F2;
    border: 1px solid #EFEAE2;
    border-radius: 12px;
    padding: 16px 20px;
    box-sizing: border-box;
}
.limitations-title {
    font-size: 15px;
    font-weight: 700;
    color: #1F2937;
    margin-bottom: 10px;
}
.limitations-card ul {
    margin: 0;
    padding-left: 18px;
    color: #4B5563;
    font-size: 13.5px;
    line-height: 1.6;
}
.limitations-card li,
.limitations-card-full li {
    margin-bottom: 6px;
}
.limitations-card-full ul {
    margin: 0;
    padding-left: 18px;
    color: #4B5563;
    font-size: 13.5px;
    line-height: 1.6;
}
</style>

<div class="limitations-grid">
    <div class="limitations-card">
        <div class="limitations-title">🏥 Patient Flow & Baseline Need</div>
        <ul>
            <li>Gaps are estimates benchmarked against today's national average, not observed unmet need (no public subzone waiting list or patient travel origin data).</li>
            <li>Home care is delivered at residences with no area-level facility capacity, so it is not mapped.</li>
            <li>'Need' reflects beds/places to sustain current average provision, not waiting list forecasts.</li>
        </ul>
    </div>
    <div class="limitations-card">
        <div class="limitations-title">🏛️ Facility Capacity Publishing Gaps</div>
        <ul>
            <li>Nursing-home capacity is published for only 3 of 94 homes; day-care places are shared equally from national totals.</li>
            <li>Pipeline projects without confirmed opening years or capacities count only in the optimistic scenario.</li>
            <li>Acute-hospital operating bed counts and private GP clinic capacities are not published per facility, requiring proxy estimations.</li>
        </ul>
    </div>
    <div class="limitations-card-full">
        <div class="limitations-title">🧭 Workforce & Spatial Modeling</div>
        <ul>
            <li>Healthcare workforce is the primary binding constraint, but available at national aggregate level only.</li>
            <li>Travel accessibility uses straight-line distances; SingStat demographics rounded to nearest 10.</li>
            <li>Healthcare clusters (NHG / NUHS / SingHealth) are approximated by the nearest polyclinic.</li>
        </ul>
    </div>
</div>
""", unsafe_allow_html=True)
      with t3:
        if True:
            st.markdown(
                "<b>Forecast test — trained on 2011-2020, predicted 2021-2025, compared with what happened:</b>",
                unsafe_allow_html=True,
            )
            model_errors = pd.DataFrame(
                {
                    "model": [
                        "Straight-line trend",
                        "Slowing growth",
                        "Ageing & survival",
                    ],
                    "error": [2.5, 3.4, 2.1],
                    "winner": [False, False, True],
                }
            )
            forecast_fig = go.Figure(
                go.Bar(
                    x=model_errors.error,
                    y=model_errors.model,
                    orientation="h",
                    marker_color=[
                        "#E76F51" if winner else "#E2DDD6"
                        for winner in model_errors.winner
                    ],
                    text=[
                        f"{error:.1f}% · Winner" if winner else f"{error:.1f}%"
                        for error, winner in zip(model_errors.error, model_errors.winner)
                    ],
                    textposition="inside",
                    insidetextfont=dict(color="#374151", size=13, family="Inter"),
                    cliponaxis=False,
                    hovertemplate="%{y}<br>Forecast error: %{x:.1f}%<extra></extra>",
                )
            )
            forecast_fig.update_layout(
                height=230,
                margin=dict(l=18, r=36, t=12, b=14),
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                showlegend=False,
                font=dict(family="Inter", color="#374151", size=12),
                xaxis=dict(
                    title="Forecast error, residents aged 65+ (%)",
                    range=[0, 4.0],
                    gridcolor="#EFEAE2",
                    zeroline=True,
                    zerolinecolor="#E5E7EB",
                    tickfont=dict(color="#8C827A"),
                    titlefont=dict(color="#C85A32", size=14, family="Inter"),
                ),
                yaxis=dict(
                    title="",
                    autorange="reversed",
                    showgrid=False,
                    tickfont=dict(color="#8C827A"),
                ),
            )
            st.plotly_chart(
                forecast_fig,
                use_container_width=True,
                config={"displayModeBar": False},
                key="evidence_backtest_error",
            )
            bo = D.get("origins")
            if bo is not None and len(bo):
                piv = bo.assign(err=(bo.mape_pop65 * 100).round(1)).pivot_table(index="origin", columns="model", values="err").rename(columns={
                    "M1_linear_trend": "Straight-line trend %", "M2_damped_growth": "Slowing growth %", "M3_cohort_component": "Ageing & survival %"})
                st.markdown(
                    "<b>Repeated with 5 starting years (2016-2020, each forecasting up to 5 years ahead): "
                    "the ageing &amp; survival model has the smallest error from 5 of 5 starting years. "
                    "Error for residents 65+:</b>",
                    unsafe_allow_html=True,
                )
                piv = piv.reset_index().rename(columns={
                    "origin": "Training start year",
                    "Straight-line trend %": "Straight-line trend",
                    "Slowing growth %": "Slowing growth",
                    "Ageing & survival %": "Ageing & survival (cohort)",
                })
                piv = piv.round(1)
                header_styles = [
                    {"selector": "th", "props": [("background-color", "#F4EFEA"), ("color", "#374151"),
                                                   ("font-weight", "700"), ("border", "1px solid #E5E7EB")]},
                    {"selector": "td", "props": [("color", "#374151"), ("border", "1px solid #E5E7EB")]},
                    {"selector": "th.col3", "props": [("background-color", "#FDF3E7"), ("color", "#C85A32"),
                                                        ("font-weight", "700")]},
                ]
                formatted_piv = (
                    piv.style
                    .format({
                        "Training start year": "{:.0f}",
                        "Straight-line trend": "{:.1f}%",
                        "Slowing growth": "{:.1f}%",
                        "Ageing & survival (cohort)": "{:.1f}%",
                    })
                    .set_table_styles(header_styles)
                    .set_properties(
                        subset=["Ageing & survival (cohort)"],
                        **{
                            "background-color": "#FDF3E7",
                            "font-weight": "700",
                            "color": "#C85A32",
                            "border": "1px solid #E5E7EB",
                        },
                    )
                )
                st.dataframe(formatted_piv, hide_index=True, use_container_width=True)
            st.markdown(
                "**Scenarios in order** — slower ≤ base ≤ faster ageing holds in 275 of 275 area-years "
                "(residents 65+, 2027-2031)."
            )
            st.markdown(
                "**Rankings vs assumptions** — the Top 5 is re-ranked 200 times with population and estimated "
                "capacities varied together; the share of runs an area stays in the Top 5 is its robustness."
            )
      with t4:
        if True:
            st.dataframe(D["assumptions"], hide_index=True, use_container_width=True, height=H_TOP + H_MAIN - 120)
      with t5:
        if True:
            st.markdown(
                f'<section style="background:#FFFFFF;border:1px solid {LINE};border-radius:16px;padding:18px 20px;'
                f'box-shadow:0 1px 8px rgba(31,42,68,.05);margin-bottom:14px">'
                f'<div style="font-family:Nunito;font-size:18px;font-weight:900;color:{NAVY};margin-bottom:8px">Official Data Ingestion</div>'
                f'<div style="font-size:13.5px;color:{INK};line-height:1.55;margin-bottom:10px">SingStat population by planning area/subzone, age, sex (2011-2026) and life tables · '
                f'MOH admission rates by age and sex (2025), beds and day places (2025) · data.gov.sg monthly admissions (live API) · '
                f'AIC eldercare directory · MOH upcoming facilities · CHAS clinics (2021) · MOH polyclinic waiting times (Aug 2026) · '
                f'URA Master Plan boundaries · OneMap geocoding.</div>'
                f'<div style="display:flex;flex-wrap:wrap;gap:7px">'
                f'<span class="chip" style="background:{BLUE_BG};color:{BLUE}">SingStat · population &amp; life tables</span>'
                f'<span class="chip" style="background:{CORAL_BG};color:#B44335">MOH · admissions &amp; facilities</span>'
                f'<span class="chip" style="background:{MINT_BG};color:#0E7A5B">URA · Master Plan</span>'
                f'<span class="chip" style="background:{LAV_BG};color:#5B4BC4">OneMap · geocoding</span>'
                f'<span class="chip" style="background:#F5F1EA;color:{INK}">data.gov.sg · admissions</span>'
                f'<span class="chip" style="background:#F5F1EA;color:{INK}">AIC · eldercare directory</span>'
                f'<span class="chip" style="background:#F5F1EA;color:{INK}">CHAS · clinics</span>'
                f'</div></section>',
                unsafe_allow_html=True,
            )
            st.markdown(
                f'<section style="background:#FFFFFF;border:1px solid {LINE};border-radius:16px;padding:18px 20px;'
                f'box-shadow:0 1px 8px rgba(31,42,68,.05)">'
                f'<div style="font-family:Nunito;font-size:18px;font-weight:900;color:{NAVY};margin-bottom:10px">Governed Data Pipeline</div>'
                f'<div style="display:flex;align-items:center;flex-wrap:wrap;gap:8px">'
                f'<span class="chip" style="background:{BLUE_BG};color:{BLUE}">Lakeflow Ingestion</span>'
                f'<span style="color:{MUTED};font-weight:800">→</span>'
                f'<span class="chip" style="background:{CORAL_BG};color:#B44335">Delta Medallion (Bronze/Silver/Gold)</span>'
                f'<span style="color:{MUTED};font-weight:800">→</span>'
                f'<span class="chip" style="background:{LAV_BG};color:#5B4BC4">MLflow Tracking</span>'
                f'<span style="color:{MUTED};font-weight:800">→</span>'
                f'<span class="chip" style="background:{YELLOW_BG};color:#8A6A00">Unity Catalog Governance</span>'
                f'<span style="color:{MUTED};font-weight:800">→</span>'
                f'<span class="chip" style="background:{MINT_BG};color:#0E7A5B">Executive Planning App</span>'
                f'</div><div style="font-size:13px;color:{MUTED};margin-top:12px">Also serves the Databricks AI/BI dashboard and Genie.</div>'
                f'</section>',
                unsafe_allow_html=True,
            )


if ss.get("page") == "Area planning":
    page_area()
elif ss.get("page") == "View evidence":
    page_evidence()
else:
    page_overview()
