"""Flood dynamics dashboard (Streamlit).

Run from the repository root:
    streamlit run flood_drivers/dashboard/app.py

Needs the outputs of build_dataset.py, analyse.py and analyse_v2.py.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fd_config as C  # noqa: E402

V2 = C.RES / "v2"
st.set_page_config(page_title="South Sudan flood dynamics", layout="wide")

# fixed colour per entity (validated categorical order: blue, orange, aqua, yellow, magenta)
BLUE, ORANGE, AQUA, YELLOW, MAGENTA, INK = "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#52514e"
LAKE_COL = {"lake_victoria": BLUE, "lake_kyoga": ORANGE, "lake_albert": AQUA}
EXT_COL = {"ext_ayod": BLUE, "ext_bor_south": ORANGE, "ext_malakal": AQUA}
FSET_COL = {"ar": BLUE, "ar+lake": ORANGE, "ar+lakechg": AQUA, "ar+rain": YELLOW, "ar+lake+rain": MAGENTA}
LABEL = {"q_mean": "Discharge at station 100205 (m³/s)", "ext_ayod": "Flood extent, Ayod (% of area)",
         "ext_bor_south": "Flood extent, Bor South (% of area)", "ext_malakal": "Flood extent, Malakal (% of area)"}


def nice(t):
    return LABEL.get(t, t)


def scale(t):
    return 100.0 if t.startswith("ext_") else 1.0


@st.cache_data
def read_csv(path, **kw):
    p = Path(path)
    return pd.read_csv(p, **kw) if p.exists() else None


def need(df, what, cmd):
    if df is None:
        st.error(f"Missing results: {what}. Run `{cmd}` first (from the repository root).")
        st.stop()
    return df


def table_view(df, label="Show data table"):
    with st.expander(label):
        st.dataframe(df, use_container_width=True)


def style(fig, title=None, h=380, ytitle=None):
    fig.update_layout(title=title, height=h, margin=dict(l=10, r=10, t=50 if title else 10, b=10),
                      legend=dict(orientation="h", y=-0.18), hovermode="x unified")
    if ytitle:
        fig.update_yaxes(title=ytitle)
    return fig


def vline(fig, year):
    x = pd.Timestamp(f"{year}-01-01")
    fig.add_shape(type="line", x0=x, x1=x, y0=0, y1=1, yref="paper", line=dict(color=INK, width=1, dash="dash"))
    fig.add_annotation(x=x, y=1, yref="paper", text=f"{year}", showarrow=False, yanchor="bottom", font=dict(color=INK))


monthly = need(read_csv(C.OUT / "monthly_dataset.csv", index_col="month", parse_dates=True),
               "monthly_dataset.csv", "python flood_drivers/build_dataset.py")

page = st.sidebar.radio("Page", ["1 · Regime timeline", "2 · What drives it", "3 · Early-warning simulator",
                                 "4 · Skill and limits", "5 · Same indicators everywhere?",
                                 "6 · Cost of wrong calls", "7 · Flood dynamics explained"])
st.sidebar.caption("Historical analysis for learning about flood dynamics. Not an operational forecast.")

# ======================================================================= page 1
if page.startswith("1"):
    st.title("A step change in flooding around 2020")
    st.caption("Monthly data 2002–2025, Ayod, Bor South and Malakal (White Nile).")
    reg = read_csv(V2 / "regime_summary.csv")
    sm = st.checkbox("Smooth with a 3-month mean", value=True)
    if reg is not None:
        cols = st.columns(4)
        for c, s in zip(cols, ["q_mean", "ext_ayod", "ext_malakal", "lake_albert"]):
            r = reg[reg.series == s]
            if len(r):
                r = r.iloc[0]
                ratio = r.ratio_after_before
                c.metric(nice(s) if s in LABEL else "Lake Albert level",
                         f"×{ratio:.1f}" if s.startswith("ext_") else f"{(ratio - 1) * 100:+.0f}%"
                         if s == "q_mean" else f"{r.mean_after - r.mean_before:+.2f} m",
                         f"step in {int(r.split_year)}", delta_color="off", delta_arrow="off")
    for title, cols_, colmap, yt in [("Upstream lake levels (change vs 2002–2012 mean)", list(LAKE_COL), LAKE_COL, "Metres"),
                                     (LABEL["q_mean"], ["q_mean"], {"q_mean": BLUE}, "m³/s"),
                                     ("Flood extent", list(EXT_COL), EXT_COL, "% of area flagged as flooded")]:
        cols_ = [c for c in cols_ if c in monthly.columns]
        fig = go.Figure()
        for c in cols_:
            s = monthly[c] * scale(c)
            if c.startswith("lake_"):  # lakes sit at very different heights: show change vs the 2002-2012 mean
                s = s - s[:"2012"].mean()
            s = s.rolling(3, min_periods=1).mean() if sm else s
            fig.add_scatter(x=s.index, y=s, name=c.replace("ext_", "").replace("lake_", "").replace("_", " ").title()
                            if len(cols_) > 1 else nice(c), line=dict(color=colmap[c], width=2))
        vline(fig, C.REGIME_SPLIT)
        st.plotly_chart(style(fig, title, ytitle=yt), use_container_width=True)
    table_view(monthly[[c for c in monthly.columns if c in list(LAKE_COL) + list(EXT_COL) + ["q_mean"]]],
               "Show data table (monthly)")
    if reg is not None:
        with st.expander("How the step was estimated"):
            st.write("Best single step change in annual means (two-segment mean fit). 'Variance explained' is how much of "
                     "the year-to-year variation one step accounts for.")
            st.dataframe(reg.round(3), use_container_width=True)
    sp = read_csv(V2 / "spike_check.csv")
    if sp is not None:
        with st.expander("Data check: largest flood-extent months (spike ratio ≫ 3 with few days = suspicious)"):
            st.dataframe(sp.round(1), use_container_width=True)
    st.info("**Data caveats.** Flood extent is the number of pixels the satellite product flags as flooded; clouds and "
            "vegetation hide flooding, so Bor South in particular looks too low. Discharge is satellite-derived and its "
            "absolute values look high compared with published gauge flows, so read it as an index.")

# ======================================================================= page 2
elif page.startswith("2"):
    st.title("What relates to flooding, and with what delay")
    lag = need(read_csv(C.RES / "lag_correlations.csv"), "lag_correlations.csv", "python flood_drivers/analyse.py")
    tgt = st.selectbox("Target", [t for t in C.TARGETS if t in set(lag.target)], format_func=nice)
    variant = st.radio("Correlations computed on", ["anomaly", "detrended"], horizontal=True,
                       help="'anomaly' removes the seasonal cycle. 'detrended' also removes a linear trend, so two "
                            "slowly rising series do not correlate at every lag.")
    sub = lag[(lag.target == tgt) & (lag.variant == variant) & (lag.accum_months == 1)]
    piv = sub.pivot(index="driver", columns="lag_months", values="r")
    piv = piv.loc[piv.abs().max(axis=1).sort_values(ascending=False).index[:15]]
    fig = go.Figure(go.Heatmap(z=piv.values, x=piv.columns, y=piv.index, zmid=0, zmin=-0.8, zmax=0.8,
                               colorscale="RdBu_r", colorbar=dict(title="r"),
                               hovertemplate="%{y}<br>lag %{x} months<br>r = %{z:.2f}<extra></extra>"))
    fig.update_xaxes(title="Driver leads target by (months)")
    fig.update_yaxes(autorange="reversed")
    st.plotly_chart(style(fig, f"{nice(tgt)}: correlation with drivers", h=460), use_container_width=True)
    st.caption("Strong values that keep growing at the longest lags usually mean two slow, multi-year series moving "
               "together (for example lake level and the post-2020 flooding), not a 12-month travel time.")
    table_view(piv.round(2))

    imp = read_csv(C.RES / "importance_by_driver.csv")
    if imp is not None and tgt in set(imp.target):
        leads = sorted(imp[imp.target == tgt].lead.unique())
        lead = st.select_slider("Lead time for driver importance (months)", leads, value=leads[min(1, len(leads) - 1)])
        s = imp[(imp.target == tgt) & (imp.lead == lead)].sort_values("importance", ascending=False).head(10)
        fig = go.Figure(go.Bar(x=s.importance[::-1], y=s.driver[::-1], orientation="h", marker_color=BLUE))
        fig.update_xaxes(title="Increase in squared error when the driver is shuffled")
        st.plotly_chart(style(fig, f"Which drivers the model leans on, {lead} months ahead", h=380),
                        use_container_width=True)
        st.caption("Values at or below zero mean shuffling the driver did not hurt the model: no useful information.")
        table_view(s)

    nc = C.RES / "lagmap_rain_vs_discharge.nc"
    if nc.exists():
        try:
            import xarray as xr
            ds = xr.open_dataset(nc).load()
            lg = st.slider("Map: rain leads discharge by (months)", 0, int(ds.lag.max()), 3)
            z = ds["r_by_lag"].sel(lag=lg)
            fig = go.Figure(go.Heatmap(z=z.values, x=z.longitude, y=z.latitude, zmid=0, zmin=-0.6, zmax=0.6,
                                       colorscale="RdBu_r", colorbar=dict(title="r"),
                                       hovertemplate="lon %{x}, lat %{y}<br>r = %{z:.2f}<extra></extra>"))
            fig.add_scatter(x=[31.6], y=[9.6], mode="markers", name="Station 100205",
                            marker=dict(size=10, color="black", line=dict(color="white", width=2)))
            fig.update_yaxes(scaleanchor="x")
            st.plotly_chart(style(fig, "Monthly rain anomaly vs discharge anomaly at the station", h=620),
                            use_container_width=True)
            st.caption("Broad smooth patterns point to a regional wet-year signal, not one source sub-basin.")
        except Exception as e:  # xarray/netCDF4 missing
            st.warning(f"Map unavailable: {e!r}")

# ======================================================================= page 3
elif page.startswith("3"):
    st.title("Early-warning simulator")
    st.caption("Replay what a forecast would have said. Every forecast uses only data from before the test year.")
    pred = need(read_csv(V2 / "predictions_v2.csv", parse_dates=["issue_month", "target_month"]),
                "predictions_v2.csv", "python flood_drivers/analyse_v2.py")
    c1, c2, c3 = st.columns(3)
    tgt = c1.selectbox("Target", [t for t in C.TARGETS if t in set(pred.target)], format_func=nice)
    lead = c2.select_slider("Lead time (months)", sorted(pred.lead.unique()), value=3 if 3 in set(pred.lead) else None)
    sets = c3.multiselect("Models to show", [f for f in FSET_COL if f in set(pred.featureset)],
                          default=[x for x in (C.HEADLINE_SET, "ar") if x in set(pred.featureset)])
    p = pred[(pred.target == tgt) & (pred.lead == lead)]
    k = scale(tgt)
    obs = p[(p.featureset == "baseline") & (p.model == "clim")].sort_values("target_month")
    months = list(obs.issue_month.dt.strftime("%Y-%m"))
    default = "2019-09" if "2019-09" in months else months[len(months) // 2]
    sel = st.select_slider("Forecast issued at the end of", months, value=default)
    selm = pd.Timestamp(sel + "-01")

    fig = go.Figure()
    fig.add_scatter(x=obs.target_month, y=obs.observed * k, name="Observed", line=dict(color="#0b0b0b", width=2))
    for fs in sets:
        r = p[(p.featureset == fs) & (p.model == "ridge")].sort_values("target_month")
        fig.add_scatter(x=r.target_month, y=r.predicted * k, name=f"Model {fs}", line=dict(color=FSET_COL[fs], width=1.5))
    for m, col, dash in (("persist_anom", INK, "dot"), ("trail12_anom", INK, "dash")):
        r = p[(p.featureset == "baseline") & (p.model == m)].sort_values("target_month")
        fig.add_scatter(x=r.target_month, y=r.predicted * k, name={"persist_anom": "Baseline: last anomaly persists",
                                                                  "trail12_anom": "Baseline: 12-month mean anomaly"}[m],
                        line=dict(color=col, width=1.2, dash=dash))
    tm = selm + pd.DateOffset(months=int(lead))
    fig.add_shape(type="line", x0=tm, x1=tm, y0=0, y1=1, yref="paper", line=dict(color=ORANGE, width=1, dash="dot"))
    st.plotly_chart(style(fig, f"{nice(tgt)}: forecasts made {int(lead)} months ahead (plotted at the month they target)",
                          h=430, ytitle=None), use_container_width=True)

    row = p[p.issue_month == selm]
    if len(row):
        o = row[row.model == "clim"].iloc[0].observed * k
        lines = [f"**Issued end of {selm:%b %Y} for {tm:%b %Y}** — observed: **{o:,.2f}**"]
        for _, r in row[row.model == "ridge"].iterrows():
            if r.featureset in sets:
                lines.append(f"- model `{r.featureset}`: {r.predicted * k:,.2f}")
        for m in ("persist_anom", "trail12_anom", "clim"):
            r = row[row.model == m]
            if len(r):
                lines.append(f"- baseline `{m}`: {r.iloc[0].predicted * k:,.2f}")
        st.markdown("\n".join(lines))
    table_view(p[p.model.isin(["ridge", "persist_anom", "trail12_anom", "clim"])]
               .assign(observed=lambda d: d.observed * k, predicted=lambda d: d.predicted * k)
               [["issue_month", "target_month", "featureset", "model", "observed", "predicted"]])

    st.subheader("Latest forecast from the end of the data")
    fc = read_csv(V2 / "forecast_latest_v2.csv", parse_dates=["issue_month", "target_month"])
    if fc is not None:
        f = fc[fc.target == tgt].sort_values("lead")
        h = (monthly[tgt] * k).iloc[-36:]
        fig = go.Figure()
        fig.add_scatter(x=h.index, y=h, name="Observed", line=dict(color="#0b0b0b", width=2))
        fig.add_scatter(x=list(f.target_month) + list(f.target_month[::-1]), y=list(f.hi80 * k) + list(f.lo80[::-1] * k),
                        fill="toself", fillcolor="rgba(42,120,214,0.15)", line=dict(width=0), mode="lines", name="80% error band",
                        hoverinfo="skip")
        fig.add_scatter(x=f.target_month, y=f.predicted * k, name=f"Forecast ({f.featureset.iloc[0]})",
                        line=dict(color=BLUE, width=2), mode="lines+markers")
        st.plotly_chart(style(fig, f"{nice(tgt)}: forecast from {f.issue_month.iloc[0]:%b %Y}", h=380),
                        use_container_width=True)
        st.caption("The band is the typical error of this model for test years "
                   f"{C.INTERVAL_FROM_YEAR}+, not a probability forecast.")
        table_view(f[["lead", "target_month", "predicted", "lo80", "hi80"]].assign(
            predicted=lambda d: d.predicted * k, lo80=lambda d: d.lo80 * k, hi80=lambda d: d.hi80 * k))
    st.warning("Flooding here is very persistent, and a simple 'it stays as it is' rule is hard to beat at 1–3 months. "
               "See page 4 before relying on any lead time.")

# ======================================================================= page 4
elif page.startswith("4"):
    st.title("What the data can and cannot tell us")
    sk = need(read_csv(V2 / "skill_v2.csv"), "skill_v2.csv", "python flood_drivers/analyse_v2.py")
    c1, c2, c3 = st.columns(3)
    tgt = c1.selectbox("Target", [t for t in C.TARGETS if t in set(sk.target)], format_func=nice)
    scope = c2.radio("Test years", ["post", "pre", "all"], horizontal=True,
                     format_func=lambda s: {"post": f"{C.REGIME_SPLIT} and later", "pre": f"before {C.REGIME_SPLIT}",
                                            "all": "all"}[s])
    metric = c3.selectbox("Compared with", ["skill_vs_trail12_anom", "skill_vs_persist_anom", "skill_vs_clim"],
                          format_func=lambda m: {"skill_vs_trail12_anom": "12-month mean anomaly (regime-aware)",
                                                 "skill_vs_persist_anom": "last month's anomaly",
                                                 "skill_vs_clim": "seasonal average"}[m])
    s = sk[(sk.target == tgt) & (sk.scope == scope) & (sk.featureset != "baseline")]
    fig = go.Figure()
    for (fs, m), g in s.groupby(["featureset", "model"]):
        g = g.sort_values("lead")
        fig.add_scatter(x=g.lead, y=g[metric], name=f"{fs} ({m})", mode="lines+markers",
                        line=dict(color=FSET_COL.get(fs, INK), width=2, dash="solid" if m == "ridge" else "dot"))
    fig.add_hline(y=0, line=dict(color=INK, width=1))
    fig.update_xaxes(title="Lead time (months)", dtick=1)
    st.plotly_chart(style(fig, "Skill: above 0 beats the chosen baseline, below 0 is worse", h=420,
                          ytitle="Skill (1 − error / baseline error)"), use_container_width=True)
    st.caption("`ar` uses only the series' own recent history. The value of upstream information is the gap between `ar` "
               "and the `ar+…` lines.")
    table_view(s[["lead", "featureset", "model", "n", "rmse", "r2", "skill_vs_clim", "skill_vs_persist_anom",
                  "skill_vs_trail12_anom"]].round(3))
    st.markdown(
        "### Reading this honestly\n"
        "- **One regime change, 24 years.** Flooding and lake levels stepped up around 2020, so there is effectively one "
        "'wet regime' to learn from. Models trained before it cannot be tested on anything similar.\n"
        "- **Persistence is strong.** Floods here are slow and long-lasting; next month usually looks like this month.\n"
        "- **Rainfall alone adds little** once season and recent history are known; slow storage (lake levels) is the "
        "more consistent signal.\n"
        "- **Data limits.** Flooded-pixel counts miss flooding under cloud and vegetation (Bor South looks too low), the "
        "discharge series is a satellite-derived index, and ERA5 is reanalysis, not gauge data.\n"
        "- **Not included.** An impact layer (cropland, population) is left out because the available crop map "
        "underrepresents reality.\n"
        "- **Not for decisions.** This supports understanding and further work, not operational early warning.")


# shared names for pages 5-7
AREA = {"q_mean": "River discharge", "ext_ayod": "Ayod", "ext_bor_south": "Bor South", "ext_malakal": "Malakal"}
AREA_ORDER = ["ext_ayod", "ext_bor_south", "ext_malakal", "q_mean"]
IND = {"ar+lake": "Lake levels", "ar+rain": "Rain and runoff", "ar+lake+rain": "Lakes + rain",
       "ar+lakechg": "Lake level changes only"}

# ======================================================================= page 5
if page.startswith("5"):
    st.title("Do the indicators work the same way everywhere?")
    st.caption("Question: does adding an indicator make the forecast better, and is that true in every area? "
               "Gain = how much smaller the forecast error becomes when the indicator is added to the area's own recent "
               "history. 0% = no help, negative = it makes things worse. Bars show a 95% range from resampling whole years.")
    imp = need(read_csv(V2 / "indicator_impact.csv"), "indicator_impact.csv", "python flood_drivers/indicator_impact.py")
    het = read_csv(V2 / "indicator_heterogeneity.csv")
    per = st.radio("Test years", list(dict.fromkeys(imp.period)), horizontal=True)
    s5 = imp[(imp.period == per) & (imp.lead == "all")]
    fig = go.Figure()
    for fs, label in IND.items():
        g = s5[s5.featureset == fs].set_index("target").reindex(AREA_ORDER).dropna(subset=["gain"])
        fig.add_bar(x=[AREA[t] for t in g.index], y=g.gain * 100, name=label, marker_color=FSET_COL.get(fs, INK),
                    error_y=dict(type="data", symmetric=False, array=(g.hi - g.gain) * 100, arrayminus=(g.gain - g.lo) * 100))
    fig.add_hline(y=0, line=dict(color=INK, width=1))
    fig.update_layout(barmode="group")
    st.plotly_chart(style(fig, "Forecast error reduction from each indicator (all lead times together)", h=430,
                          ytitle="% smaller error than 'own history only'"), use_container_width=True)

    st.subheader("In plain words")
    for t in AREA_ORDER:
        g = s5[s5.target == t]
        clear = g[g.lo > 0].sort_values("gain", ascending=False)
        if len(clear):
            txt = ", ".join(f"**{IND[r.featureset]}** (about {r.gain * 100:.0f}% smaller error)" for r in clear.itertuples())
            st.markdown(f"- **{AREA[t]}:** clear help from {txt}.")
        else:
            st.markdown(f"- **{AREA[t]}:** no indicator clearly helps. The area's own recent history is as good.")

    if het is not None:
        fs_sel = st.selectbox("Compare areas for indicator", list(IND), format_func=IND.get)
        h = het[(het.period == per) & (het.featureset == fs_sel)].copy()
        h["Areas"] = h.area_a.map(AREA) + " vs " + h.area_b.map(AREA)
        h["Difference in gain (%-points)"] = (h["diff"] * 100).round(0)
        h["95% range"] = [f"{a * 100:.0f} to {b * 100:.0f}" for a, b in zip(h.lo, h.hi)]
        h["Clearly different?"] = np.where(h.p_value < 0.05, "yes", "not shown")
        n_yes = int((h.p_value < 0.05).sum())
        st.markdown(f"**{IND[fs_sel]}:** {n_yes} of {len(h)} pairs of areas respond clearly differently. "
                    + ("Treat the areas separately." if n_yes else "No clear difference between areas in this data."))
        st.dataframe(h[["Areas", "Difference in gain (%-points)", "95% range", "p_value", "Clearly different?"]].round(3),
                     use_container_width=True, hide_index=True)

    with st.expander("Gain by lead time (no uncertainty ranges)"):
        a5 = st.selectbox("Area", AREA_ORDER, format_func=AREA.get, key="a5")
        bl = imp[(imp.period == per) & (imp.lead != "all") & (imp.target == a5)].copy()
        bl["lead"] = bl.lead.astype(int)
        fig = go.Figure()
        for fs, label in IND.items():
            g = bl[bl.featureset == fs].sort_values("lead")
            fig.add_scatter(x=g.lead, y=g.gain * 100, name=label, mode="lines+markers", line=dict(color=FSET_COL.get(fs, INK)))
        fig.add_hline(y=0, line=dict(color=INK, width=1))
        fig.update_xaxes(title="Lead time (months)", dtick=1)
        st.plotly_chart(style(fig, f"{AREA[a5]}: gain by lead time", ytitle="% smaller error"), use_container_width=True)
    st.info("**Read with care.** After 2020 there are only 6 test years, so ranges are wide. Before 2020 the lake indicators "
            "did not help (at Ayod they made forecasts worse): the link between lakes and flooding only shows up in the "
            "wetter regime, so it should be re-checked every year. Rain helping at Bor South shows up only from "
            "2020 on, so treat it as a lead to check, not a rule.")

# ======================================================================= page 6
elif page.startswith("6"):
    st.title("What a wrong call costs: missed floods vs false alarms")
    st.caption("A flood = a month in the top 20% of 2010-2025. A missed flood (false negative) = flood happened, no alert. "
               "A false alarm (false positive) = alert, no flood. Every forecast uses only earlier years.")
    conf = need(read_csv(V2 / "sle_confusion.csv"), "sle_confusion.csv", "python flood_drivers/sle_risk_test.py")
    pool = read_csv(V2 / "sle_pooled.csv")
    if pool is not None:
        a = pool[pool.scope == "all sites, all leads"].iloc[0]
        c1, c2, c3 = st.columns(3)
        c1.metric("Wrong calls that were missed floods", f"{a.miss_share * 100:.0f}%", f"95% range {a.lo * 100:.0f}-{a.hi * 100:.0f}%",
                  delta_color="off", delta_arrow="off")
        c2.metric("Missed floods", int(a.FN))
        c3.metric("False alarms", int(a.FP))
        fig = go.Figure()
        q = pool[pool.scope != "all sites, all leads"].set_index("scope").reindex(AREA_ORDER)
        fig.add_bar(x=[AREA[t] for t in q.index], y=q.miss_share * 100, marker_color=ORANGE, name="Share of wrong calls that were misses",
                    error_y=dict(type="data", symmetric=False, array=(q.hi - q.miss_share) * 100, arrayminus=(q.miss_share - q.lo) * 100))
        fig.add_hline(y=50, line=dict(color=INK, width=1, dash="dash"))
        fig.update_yaxes(range=[0, 100])
        st.plotly_chart(style(fig, "Above the dashed line = misses outnumber false alarms", h=380, ytitle="% of wrong calls"),
                        use_container_width=True)
        st.caption("Ranges come from resampling whole years. A range that crosses 50% means we cannot say which error is more common.")

    st.subheader("Cost simulator: you decide how bad a miss is")
    w = st.select_slider("One missed flood is as bad as ... false alarms", [0.5, 1, 2, 3, 5, 10, 20, 50], value=5)
    lead = st.select_slider("Lead time (months)", sorted(conf.lead.unique()), value=3 if 3 in set(conf.lead) else None)
    cs = conf[conf.lead == lead].copy()
    cs["total_cost"] = cs.FN * w + cs.FP
    best = cs.loc[cs.groupby("target").total_cost.idxmin()].set_index("target").reindex(AREA_ORDER)
    fig = go.Figure()
    for m, g in cs.groupby("method"):
        g = g.set_index("target").reindex(AREA_ORDER)
        fig.add_bar(x=[AREA[t] for t in g.index], y=g.total_cost, name=m)
    fig.update_layout(barmode="group")
    st.plotly_chart(style(fig, f"Total cost (false-alarm units) at {int(lead)} months ahead, miss = {w:g} false alarms",
                          h=400, ytitle="misses x ratio + false alarms"), use_container_width=True)
    st.dataframe(pd.DataFrame({"Area": [AREA[t] for t in best.index], "Cheapest option": best.method.values,
                               "Misses": best.FN.astype(int).values, "False alarms": best.FP.astype(int).values}),
                 use_container_width=True, hide_index=True)
    st.caption("There is no right ratio in the data: it is a judgement about people, livestock, food and trust. "
               "The point of this page is to make that judgement explicit before an alert level is fixed.")

    st.subheader("Confusion table")
    a6 = st.selectbox("Area", AREA_ORDER, format_func=AREA.get, key="a6")
    mm = st.selectbox("Method", list(dict.fromkeys(conf.method)), key="m6")
    r = conf[(conf.target == a6) & (conf.lead == lead) & (conf.method == mm)]
    if len(r):
        r = r.iloc[0]
        st.dataframe(pd.DataFrame({"Alert issued": [int(r.TP), int(r.FP)], "No alert": [int(r.FN), int(r.TN)]},
                                  index=["Flood happened", "No flood"]), use_container_width=True)
        st.caption(f"Missed {r.miss_rate * 100:.0f}% of floods (95% range {r.miss_rate_lo * 100:.0f}-{r.miss_rate_hi * 100:.0f}%); "
                   f"false alarm in {r.false_alarm_rate * 100:.0f}% of non-flood months.")

# ======================================================================= page 7
elif page.startswith("7"):
    st.title("How flooding works here, in plain language")
    st.caption("What the data shows, with a note on what is explanation rather than proof. Made to be explained to others.")
    tgt = st.selectbox("Area", [t for t in AREA_ORDER if t in monthly.columns], format_func=AREA.get)
    ser = monthly[tgt] * scale(tgt)

    st.subheader("1. There is a flood season, and it moved up after 2020")
    cal = ser.groupby([ser.index.year >= C.REGIME_SPLIT, ser.index.month]).mean().unstack(0)
    fig = go.Figure()
    for flag, name, col in ((False, f"before {C.REGIME_SPLIT}", BLUE), (True, f"{C.REGIME_SPLIT} and later", ORANGE)):
        if flag in cal.columns:
            fig.add_scatter(x=["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], y=cal[flag],
                            name=name, line=dict(color=col, width=3))
    st.plotly_chart(style(fig, f"{AREA[tgt]}: average by calendar month", h=360,
                          ytitle="% of area flooded" if tgt.startswith("ext_") else "m3/s (index)"), use_container_width=True)
    st.markdown("**Say it like this:** every year has a wetter and a drier part, and since about 2020 the wet part has been "
                "bigger. Plans based on the old pattern may now be too small.")

    st.subheader("2. Floods last: next month usually looks like this month")
    y = np.log1p(ser) if tgt.startswith("ext_") else ser
    anom = y - y.groupby(y.index.month).transform("mean")
    rm = st.checkbox(f"Also remove the {C.REGIME_SPLIT} step (shows persistence on top of the step)", value=False)
    if rm:
        anom = anom - anom.groupby(anom.index.year >= C.REGIME_SPLIT).transform("mean")
    acf = [anom.autocorr(k) for k in range(1, 13)]
    fig = go.Figure(go.Bar(x=list(range(1, 13)), y=acf, marker_color=BLUE))
    fig.update_xaxes(title="Months later", dtick=1)
    fig.update_yaxes(range=[-0.2, 1])
    st.plotly_chart(style(fig, "If a month is above normal, how likely is a later month also above normal?", h=340,
                          ytitle="similarity (0 none, 1 identical)"), use_container_width=True)
    st.markdown("**Say it like this:** floods here are slow. Water that is high now is usually still high next month, which is "
                "why the best short-term forecast is often just 'last month's situation'.")

    st.subheader("3. What to watch differs by area")
    imp7 = read_csv(V2 / "indicator_impact.csv")
    if imp7 is not None:
        g = imp7[(imp7.period == "all") & (imp7.lead == "all") & (imp7.target == tgt)]
        clear = g[g.lo > 0]
        if len(clear):
            st.markdown(f"For **{AREA[tgt]}**, the indicators that clearly improve the forecast: "
                        + ", ".join(f"**{IND[f]}**" for f in clear.featureset) + ".")
        else:
            st.markdown(f"For **{AREA[tgt]}**, none of our indicators clearly beat looking at the area's own recent history. "
                        "Local observation is the best guide.")
    st.caption("Likely explanation, not proven by this data: big lakes release water slowly, so a high lake level now can mean "
               "high flows downstream for months. Rain adds little once the season and recent flooding are known.")

    st.subheader("4. Five messages to pass on")
    st.markdown(
        "1. **Flooding has a yearly rhythm, and it has grown since about 2020.**\n"
        "2. **Floods are slow and long-lasting.** Last month's flood is the best first guess for next month.\n"
        "3. **Lake levels upstream are worth watching, but not everywhere.** See page 5 for which areas.\n"
        "4. **A forecast can miss a flood.** 'No alert' is not 'safe'. Check with local reports (page 6).\n"
        "5. **Local knowledge is part of the system.** Where people see something different from the forecast, write it down: "
        "it is the data we are missing.")
    st.info("Questions to ask people on the ground: Did the flood season start earlier or last longer in recent years? "
            "Which warning signs do communities already use? Where did floods come as a surprise?")
