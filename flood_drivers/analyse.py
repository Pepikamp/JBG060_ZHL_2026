"""Step 2: what drives the floods, and how far ahead can we see them?

Reads processing_data/flood_drivers/monthly_dataset.csv (from build_dataset.py) and writes
tables + figures to flood_drivers/results/.

A. Lag analysis      deseasonalised correlation of each target with each driver at lags 0..12 months
B. Lag map           same, for every ERA5 grid cell (where does rain matter, and with what delay?)
C. Forecast skill    for lead times 1-6 months: does hydromet information beat climatology and
                     persistence? Validated with an expanding window (train on the past, test on the next
                     year, from ROLL_START) and on a fixed recent hold-out (HOLDOUT_FROM+).
D. Importance        which drivers the model actually relies on
E. Latest forecast   demo forecast from the final month in the data (input for the dashboard)
"""
import sys
import warnings

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from sklearn.base import BaseEstimator, TransformerMixin  # noqa: E402
from sklearn.ensemble import HistGradientBoostingRegressor  # noqa: E402
from sklearn.impute import SimpleImputer  # noqa: E402
from sklearn.inspection import permutation_importance  # noqa: E402
from sklearn.linear_model import RidgeCV  # noqa: E402
from sklearn.metrics import roc_auc_score  # noqa: E402
from sklearn.pipeline import make_pipeline  # noqa: E402
from sklearn.preprocessing import StandardScaler  # noqa: E402

import fd_config as C  # noqa: E402

warnings.filterwarnings("ignore")
C.RES.mkdir(parents=True, exist_ok=True)

df = pd.read_csv(C.OUT / "monthly_dataset.csv", index_col="month", parse_dates=True)
df = df.asfreq("MS")
# Drivers with (almost) no data would crash/skew the models: drop them, but say so loudly.
_cov = df.filter(regex="^(rain_|ro_|lake_)").notna().mean()
_bad = _cov[_cov < 0.6]
if len(_bad):
    print("\n" + "!" * 70 + "\nWARNING: dropping drivers with <60% coverage in 2002-2025:\n" + _bad.round(2).to_string()
          + "\n(For lake_victoria / lake_kyoga: rerun build_dataset.py with the new lakes.py and check its printout.)\n"
          + "!" * 70 + "\n")
    df = df.drop(columns=list(_bad.index))
TARGETS = [t for t in C.TARGETS if t in df.columns]
# Flood extent is spiky and skewed: model log1p(extent in per mille). to_orig() converts back to % of area.
for _t in TARGETS:
    if _t.startswith("ext_"):
        df[_t] = np.log1p(df[_t] * 1000.0)


def to_orig(target, v):
    """Back to original units: % of the region for flood extent, m3/s for discharge."""
    return 100.0 * np.expm1(np.asarray(v, float)) / 1000.0 if target.startswith("ext_") else np.asarray(v, float)


DRIVERS = [c for c in df.columns if c.startswith(("rain_", "ro_", "lake_"))]
print(f"{len(df)} months {df.index[0]:%Y-%m}..{df.index[-1]:%Y-%m}; targets {TARGETS}; {len(DRIVERS)} drivers")


def month_anomaly(s, detrend=False):
    """Remove the mean seasonal cycle (and optionally a linear trend) and standardise. Removing the
    seasonal cycle stops shared seasonality from dominating every rain-vs-flood correlation; removing
    the trend stops two slowly rising series (e.g. lake level and flood extent) from correlating at
    every lag."""
    if detrend:
        ok = s.notna().values
        t = np.arange(len(s))
        s = s - np.polyval(np.polyfit(t[ok], s.values[ok], 1), t)
    clim = s.groupby(s.index.month).transform("mean")
    a = s - clim
    return a / a.std()


# =========================================================== A. lag correlations
rows = []
for variant, dt in (("anomaly", False), ("detrended", True)):
    for t in TARGETS:
        ta = month_anomaly(df[t], dt)
        for d in DRIVERS:
            for acc in (1, 3):  # single month, and 3-month accumulation ending at the lag month
                if d.startswith("lake_") and acc == 3:
                    continue
                x = df[d].rolling(acc, min_periods=acc).sum() if d.startswith(("rain_", "ro_")) else df[d]
                xa = month_anomaly(x.dropna(), dt)
                for lag in range(0, C.MAX_LAG + 1):
                    pair = pd.concat([ta, xa.shift(lag)], axis=1).dropna()
                    if len(pair) > 30:
                        rows.append((variant, t, d, acc, lag, pair.iloc[:, 0].corr(pair.iloc[:, 1]), len(pair)))
lagc = pd.DataFrame(rows, columns=["variant", "target", "driver", "accum_months", "lag_months", "r", "n"])
lagc.to_csv(C.RES / "lag_correlations.csv", index=False)

for variant in ("anomaly", "detrended"):
    for t in TARGETS:
        sub = lagc[(lagc.variant == variant) & (lagc.target == t) & (lagc.accum_months == 1)]
        piv = sub.pivot(index="driver", columns="lag_months", values="r")
        fig, ax = plt.subplots(figsize=(8, 0.35 * len(piv) + 1.5))
        im = ax.imshow(piv.values, cmap="RdBu_r", vmin=-0.6, vmax=0.6, aspect="auto")
        ax.set_yticks(range(len(piv)), piv.index)
        ax.set_xticks(range(piv.shape[1]), piv.columns)
        ax.set_xlabel("driver leads target by this many months")
        ax.set_title(f"{t}: correlation with drivers ({variant})")
        fig.colorbar(im, label="Pearson r")
        fig.tight_layout()
        fig.savefig(C.RES / f"fig_lagcorr_{t}_{variant}.png", dpi=130)
        plt.close(fig)
    best = (lagc[lagc.variant == variant].assign(absr=lambda d: d.r.abs()).sort_values("absr", ascending=False)
            .groupby("target").head(5)[["target", "driver", "accum_months", "lag_months", "r"]])
    print(f"\nStrongest lagged relations [{variant}]:\n", best.round(2).to_string(index=False))

# =========================================================== B. lag map on the ERA5 grid
try:
    import xarray as xr
    g = xr.open_dataset(C.OUT / "era5_monthly_grid.nc")
    tp = g["tp"].sel(valid_time=df.index.intersection(g.valid_time.values))
    clim = tp.groupby("valid_time.month").mean("valid_time")
    anom = tp.groupby("valid_time.month") - clim
    anom = anom / anom.std("valid_time").where(anom.std("valid_time") > 0)
    ta = month_anomaly(df["q_mean"]).reindex(tp.valid_time.values)
    maxlag = 9
    R = np.full((maxlag + 1,) + anom.shape[1:], np.nan)
    A = anom.values
    for lag in range(maxlag + 1):
        x = A[: len(A) - lag] if lag else A
        y = ta.values[lag:]
        ok = ~np.isnan(y)
        xm = np.nan_to_num(x[ok])
        yy = y[ok] - y[ok].mean()
        R[lag] = (xm * yy[:, None, None]).mean(0) / (xm.std(0) * yy.std() + 1e-9)
    lagmax = np.nanargmax(np.abs(R), axis=0)
    rmax = np.take_along_axis(R, lagmax[None], 0)[0]
    lat, lon = anom.latitude.values, anom.longitude.values
    xr.Dataset({"r_by_lag": (("lag", "latitude", "longitude"), R)},
               coords={"lag": range(maxlag + 1), "latitude": lat, "longitude": lon}
               ).to_netcdf(C.RES / "lagmap_rain_vs_discharge.nc")
    fig, axs = plt.subplots(1, 2, figsize=(11, 6))
    ext = [lon.min(), lon.max(), lat.min(), lat.max()]
    for ax, arr, cm, vm, ttl in [(axs[0], rmax, "RdBu_r", (-0.6, 0.6), "strongest r (rain -> discharge)"),
                                 (axs[1], np.where(np.isnan(rmax), np.nan, lagmax), "viridis", (0, maxlag),
                                  "lag (months) of strongest r")]:
        im = ax.imshow(arr, extent=ext, cmap=cm, vmin=vm[0], vmax=vm[1], aspect="equal")
        fig.colorbar(im, ax=ax, shrink=0.7)
        ax.set_title(ttl)
        ax.set_xlabel("lon")
    axs[0].set_ylabel("lat")
    fig.suptitle("Where does monthly rain relate to discharge at the South Sudan station?")
    fig.tight_layout()
    fig.savefig(C.RES / "fig_lagmap.png", dpi=130)
    plt.close(fig)
except Exception as e:  # the map is a bonus; never block the rest
    print("lag map skipped:", repr(e))


# =========================================================== C. forecast skill
def make_features(target, lead, fset, all_rows=False):
    """Features known at the end of month t (the issue month); y is the target at t+lead."""
    X = {}
    for c in df.columns:
        if c.startswith(("rain_", "ro_")):
            for w in (1, 3, 6):
                X[f"{c}__sum{w}"] = df[c].rolling(w, min_periods=w).sum()
        elif c.startswith("lake_"):
            X[f"{c}__lvl"] = df[c]
            X[f"{c}__d3"] = df[c] - df[c].shift(3)
            X[f"{c}__d12"] = df[c] - df[c].shift(12)
    tm = df.index.month.values
    tgt_month = ((tm - 1 + lead) % 12)  # calendar month index of target
    X["season_sin"] = np.sin(2 * np.pi * tgt_month / 12)
    X["season_cos"] = np.cos(2 * np.pi * tgt_month / 12)
    if "persist" in fset:
        for k in (0, 1, 3):
            X[f"own__lag{k}"] = df[target].shift(k)
    if "discharge" in fset and target != "q_mean":
        X["q_mean__lag0"] = df["q_mean"]
        X["q_mean__lag1"] = df["q_mean"].shift(1)
        X["q_max__lag0"] = df["q_max"]
    X = pd.DataFrame(X, index=df.index)
    y = df[target].shift(-lead)
    ok = (np.arange(len(df)) >= 12) & (np.ones(len(df), bool) if all_rows else y.notna().values)  # 1st year lacks long windows
    return X[ok], y[ok]


class ColSelect(BaseEstimator, TransformerMixin):
    """Keep only columns whose name starts with one of the prefixes."""

    def __init__(self, prefixes=()):
        self.prefixes = prefixes

    def fit(self, X, y=None):
        self.cols_ = [c for c in X.columns if c.startswith(tuple(self.prefixes))]
        return self

    def transform(self, X):
        return X[self.cols_]


def _ridge(*pre):
    steps = ([ColSelect(pre)] if pre else []) + [SimpleImputer(strategy="median"), StandardScaler(),
                                                 RidgeCV(alphas=np.logspace(-1, 3, 13))]
    return make_pipeline(*steps)


def model_zoo():
    return {
        "ridge": _ridge(),                                           # all drivers
        "ridge_lakes": _ridge("lake_", "season", "own__", "q_mean"),  # lake levels (+season, persistence) only
        "hgb": HistGradientBoostingRegressor(max_depth=3, learning_rate=0.05, max_iter=100,
                                             min_samples_leaf=8, l2_regularization=1.0,
                                             random_state=C.RANDOM_STATE),  # cannot extrapolate beyond training range
    }


def target_year(index, lead):
    return (index + pd.DateOffset(months=lead)).year


def folds(years, scheme):
    if scheme == "rolling":  # expanding window: train on target years <= Y-2, test year Y (1y gap vs lag leakage)
        for yr in range(C.ROLL_START, int(years.max()) + 1):
            yield years <= yr - 2, years == yr
    else:  # fixed hold-out: train before HOLDOUT_FROM-1, test from HOLDOUT_FROM on
        yield years < C.HOLDOUT_FROM - 1, years >= C.HOLDOUT_FROM


def metrics(y, yhat, clim, persist_anom, label, thr):
    mse = lambda a: float(np.mean((y - a) ** 2))
    ev = (y > thr).astype(int)
    auc = roc_auc_score(ev, yhat) if 0 < ev.sum() < len(ev) else np.nan
    return dict(rmse=np.sqrt(mse(yhat)), r2=1 - mse(yhat) / np.var(y) if np.var(y) else np.nan,
                skill_vs_clim=1 - mse(yhat) / mse(clim), skill_vs_persist=1 - mse(yhat) / mse(persist_anom),
                auc_event=auc, n=len(y), label=label)


def skill_for_target(target):
    records, preds = [], []
    thr = np.quantile(df[target].dropna(), C.EVENT_QUANTILE)
    for lead in C.LEADS:
        fsets = ["hydromet", "hydromet+persist"] + (["hydromet+discharge"] if target != "q_mean" else [])
        data = {fs: make_features(target, lead, fs) for fs in fsets}
        X0, y0 = data["hydromet"]
        years = target_year(y0.index, lead)
        for scheme in ("rolling", "holdout"):
            P = {(fs, m): pd.Series(np.nan, index=y0.index) for fs in fsets for m in model_zoo()}
            BL = {k: pd.Series(np.nan, index=y0.index) for k in ("clim", "persist", "persist_anom")}
            for tr, te in folds(years, scheme):
                if te.sum() == 0 or tr.sum() < 36:
                    continue
                tmon = (y0.index[te] + pd.DateOffset(months=lead)).month
                climtab = y0[tr].groupby((y0.index[tr] + pd.DateOffset(months=lead)).month).mean()
                clim = pd.Series(climtab.reindex(tmon).values, index=y0.index[te])
                cur = df[target].reindex(y0.index)
                cur_clim = df[target].groupby(df.index.month).transform("mean").reindex(y0.index)
                BL["clim"][te] = clim.values
                BL["persist"][te] = cur[te].values
                BL["persist_anom"][te] = (clim + (cur[te] - cur_clim[te])).values
                for fs in fsets:
                    X, y = data[fs]
                    for mname, mdl in model_zoo().items():
                        mdl.fit(X[tr], y[tr])
                        P[(fs, mname)][te] = mdl.predict(X[te])
            valid = BL["clim"].notna() & BL["persist_anom"].notna()
            if valid.sum() < 10:
                continue
            yy = y0[valid].values
            cl, pa = BL["clim"][valid].values, BL["persist_anom"][valid].values
            for b in BL:
                records.append(dict(target=target, lead=lead, scheme=scheme, featureset="baseline", model=b,
                                    **metrics(yy, BL[b][valid].values, cl, pa, b, thr)))
            for (fs, mname), s in P.items():
                records.append(dict(target=target, lead=lead, scheme=scheme, featureset=fs, model=mname,
                                    **metrics(yy, s[valid].values, cl, pa, f"{fs}|{mname}", thr)))
                if scheme == "rolling":
                    pv = s[valid].values
                    preds.append(pd.DataFrame(dict(target=target, lead=lead, featureset=fs, model=mname,
                                                   issue_month=y0.index[valid],
                                                   target_month=y0.index[valid] + pd.DateOffset(months=lead),
                                                   observed=to_orig(target, yy), predicted=to_orig(target, pv),
                                                   climatology=to_orig(target, cl),
                                                   persistence=to_orig(target, BL["persist"][valid].values),
                                                   persist_anom=to_orig(target, pa))))
    return records, preds


from joblib import Parallel, delayed  # noqa: E402

res = Parallel(n_jobs=-1)(delayed(skill_for_target)(t) for t in TARGETS)
records = [r for rec, _ in res for r in rec]
preds = [p for _, pr_ in res for p in pr_]

skill = pd.DataFrame(records).drop(columns="label")
skill.to_csv(C.RES / "skill_by_lead.csv", index=False)
pd.concat(preds).to_csv(C.RES / "predictions_rolling.csv", index=False)

show = skill[(skill.scheme == "rolling") & (skill.featureset != "baseline")]
show = show.loc[show.groupby(["target", "lead", "featureset"])["rmse"].idxmin()]
print("\nBest model per target/lead/feature set (expanding-window validation). skill>0 = beats the baseline:")
print(show[["target", "lead", "featureset", "model", "r2", "skill_vs_clim", "skill_vs_persist", "auc_event"]]
      .round(2).to_string(index=False))

# skill-vs-lead figure
fig, axs = plt.subplots(1, len(TARGETS), figsize=(4.2 * len(TARGETS), 3.8), sharey=True)
axs = np.atleast_1d(axs)
for ax, t in zip(axs, TARGETS):
    for fs, grp in show[show.target == t].groupby("featureset"):
        ax.plot(grp.lead, grp.skill_vs_clim, marker="o", label=fs)
    ho = skill[(skill.target == t) & (skill.scheme == "holdout") & (skill.featureset != "baseline")]
    if len(ho):
        ho = ho.loc[ho.groupby("lead")["rmse"].idxmin()]
        ax.plot(ho.lead, ho.skill_vs_clim, ls="--", marker="x", c="k", label=f"best, hold-out {C.HOLDOUT_FROM}+")
    bl = skill[(skill.target == t) & (skill.scheme == "holdout") & (skill.model == "persist_anom")]
    ax.plot(bl.lead, bl.skill_vs_clim, ls=":", marker="s", c="grey", label="persistence (hold-out)")
    ax.axhline(0, c="grey", lw=0.8)
    ax.set_title(t)
    ax.set_xlabel("lead time (months)")
axs[0].set_ylabel("skill vs seasonal climatology")
axs[0].legend(fontsize=7)
fig.tight_layout()
fig.savefig(C.RES / "fig_skill_vs_lead.png", dpi=130)
plt.close(fig)

# observed vs predicted at a 3-month lead
lead_show = 3 if 3 in C.LEADS else C.LEADS[0]
pr = pd.read_csv(C.RES / "predictions_rolling.csv", parse_dates=["issue_month", "target_month"])
fig, axs = plt.subplots(len(TARGETS), 1, figsize=(11, 2.6 * len(TARGETS)), sharex=True)
axs = np.atleast_1d(axs)
for ax, t in zip(axs, TARGETS):
    s = pr[(pr.target == t) & (pr.lead == lead_show) & (pr.featureset == "hydromet+persist") & (pr.model == "ridge")]
    ax.plot(s.target_month, s.observed, c="k", lw=1.2, label="observed")
    ax.plot(s.target_month, s.predicted, c="tab:red", lw=1, label=f"predicted {lead_show} months ahead")
    ax.plot(s.target_month, s.climatology, c="grey", lw=0.8, ls=":", label="climatology")
    ax.set_ylabel(t + (" (% of area)" if t.startswith("ext_") else ""))
axs[0].legend(fontsize=7, ncol=3)
fig.tight_layout()
fig.savefig(C.RES / "fig_obs_vs_pred.png", dpi=130)
plt.close(fig)

# =========================================================== D. importance (no persistence features)
# Grouped permutation importance on the held-out year: shuffle ALL columns of one driver together
# (e.g. every window of rain_sobat) and measure how much the squared error grows.
def importance_for(target, lead, n_rep=3):
    rng = np.random.default_rng(C.RANDOM_STATE)
    X, y = make_features(target, lead, "hydromet")
    years = target_year(y.index, lead)
    groups = pd.Series(X.columns.str.split("__").str[0], index=X.columns)
    acc = {}
    for tr, te in folds(years, "rolling"):
        m = model_zoo()["ridge"].fit(X[tr], y[tr])
        Xt, yt = X[te], y[te].values
        base = np.mean((yt - m.predict(Xt)) ** 2)
        for g, cols in groups.groupby(groups):
            inc = []
            for _ in range(n_rep):
                Xp = Xt.copy()
                Xp[cols.index] = Xt[cols.index].values[rng.permutation(len(Xt))]
                inc.append(np.mean((yt - m.predict(Xp)) ** 2) - base)
            acc.setdefault(g, []).append(np.mean(inc))
    return [dict(target=target, lead=lead, driver=g, importance=float(np.mean(v))) for g, v in acc.items()]


imp_leads = [l for l in (1, 3, 6) if l in C.LEADS] or C.LEADS[:1]
from joblib import Parallel, delayed  # noqa: E402,F811

imp_rows = [r for rr in Parallel(n_jobs=-1)(delayed(importance_for)(t, l) for t in TARGETS for l in imp_leads)
            for r in rr]
grp = pd.DataFrame(imp_rows)
grp.to_csv(C.RES / "importance_by_driver.csv", index=False)
for t in TARGETS:
    piv = grp[grp.target == t].pivot(index="driver", columns="lead", values="importance")
    piv = piv.loc[piv.max(axis=1).sort_values(ascending=False).index[:12]]
    piv = piv.div(piv.max().replace(0, np.nan), axis=1)  # relative per lead
    fig, ax = plt.subplots(figsize=(6, 0.38 * len(piv) + 1.5))
    im = ax.imshow(piv.values, cmap="viridis", aspect="auto", vmin=0, vmax=1)
    ax.set_yticks(range(len(piv)), piv.index)
    ax.set_xticks(range(piv.shape[1]), piv.columns)
    ax.set_xlabel("lead time (months)")
    ax.set_title(f"{t}: driver importance (permutation, relative)")
    fig.colorbar(im)
    fig.tight_layout()
    fig.savefig(C.RES / f"fig_importance_{t}.png", dpi=130)
    plt.close(fig)

# =========================================================== E. latest-month demo forecast
# Fit on all history, then issue a forecast from the final month in the data. (For a live dashboard
# you would append new months to monthly_dataset.csv and rerun.)
out = []
last = df.index[-1]
for target in TARGETS:
    clim_t = df[target].groupby(df.index.month).mean()
    for lead in C.LEADS:
        X, y = make_features(target, lead, "hydromet+persist")
        Xall, _ = make_features(target, lead, "hydromet+persist", all_rows=True)
        Xlast = Xall.loc[[last]]
        tmonth = last + pd.DateOffset(months=lead)
        for mname, mdl in model_zoo().items():
            mdl.fit(X, y)
            out.append(dict(target=target, lead=lead, model=mname, issue_month=last, target_month=tmonth,
                            predicted=float(to_orig(target, mdl.predict(Xlast)[0])),
                            current=float(to_orig(target, df[target].iloc[-1])),
                            climatology=float(to_orig(target, clim_t[tmonth.month]))))
pd.DataFrame(out).to_csv(C.RES / "forecast_latest.csv", index=False)
print("\nDone. Results in", C.RES)
