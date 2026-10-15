"""Step 3 (revised analysis): is there forecast skill once the 2020 regime shift is respected?

Differences with analyse.py:
  * flood extent is log-transformed (log1p of percent): spikes matter less, and ridge can extrapolate
  * expanding-window validation: for every test year Y the models are trained ONLY on earlier years
  * regime-aware baselines: besides climatology / persistence there is 'trail12_anom' = seasonal
    climatology + the mean anomaly of the last 12 months (knows about a slow regime change)
  * feature groups isolate where skill comes from:
        ar            own recent values + season                      (autoregressive reference)
        ar+lake       + lake levels and their changes
        ar+lakechg    + lake changes only (no absolute level)
        ar+rain       + upstream/local rain and runoff windows
        ar+lake+rain  everything
    The value of upstream information = skill of (ar+X) over (ar) and over the baselines.
  * regime summary, a spike check for the flood extent series, and a forecast with an error band.

Outputs go to flood_drivers/results/v2/.
"""
import warnings

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from joblib import Parallel, delayed  # noqa: E402
from sklearn.ensemble import HistGradientBoostingRegressor  # noqa: E402
from sklearn.impute import SimpleImputer  # noqa: E402
from sklearn.linear_model import RidgeCV  # noqa: E402
from sklearn.pipeline import make_pipeline  # noqa: E402
from sklearn.preprocessing import FunctionTransformer, StandardScaler  # noqa: E402

import fd_config as C  # noqa: E402

warnings.filterwarnings("ignore")
OUT = C.RES / "v2"
OUT.mkdir(parents=True, exist_ok=True)

df = pd.read_csv(C.OUT / "monthly_dataset.csv", index_col="month", parse_dates=True).asfreq("MS")
cov = df.filter(regex="^(rain_|ro_|lake_)").notna().mean()
bad = cov[cov < 0.6]
if len(bad):
    print("WARNING: dropping drivers with <60% coverage:", list(bad.index))
    df = df.drop(columns=list(bad.index))
TARGETS = [t for t in C.TARGETS if t in df.columns]
LAKES = [c for c in df.columns if c.startswith("lake_")]
RAIN = [c for c in df.columns if c.startswith(("rain_", "ro_"))]

# ------------------------------------------------------------------ transformed targets
Y = pd.DataFrame(index=df.index)
for t in TARGETS:
    Y[t] = np.log1p(df[t] * C.EXT_SCALE) if t.startswith("ext_") else df[t]


def inv(target, v):
    return np.expm1(v) / C.EXT_SCALE if target.startswith("ext_") else np.maximum(v, 0)  # discharge cannot be < 0


# =========================================================== 1. regime summary
def changepoint(s):
    s = s.dropna()
    best = (None, np.inf)
    for k in range(3, len(s) - 3):
        sse = ((s.iloc[:k] - s.iloc[:k].mean()) ** 2).sum() + ((s.iloc[k:] - s.iloc[k:].mean()) ** 2).sum()
        if sse < best[1]:
            best = (k, sse)
    k, sse = best
    sse0 = ((s - s.mean()) ** 2).sum()
    return s.index[k], s.iloc[:k].mean(), s.iloc[k:].mean(), 1 - sse / sse0


annual = df[["q_mean"] + [t for t in TARGETS if t.startswith("ext_")] + LAKES].resample("YS").mean()
rows = []
for c in annual.columns:
    d, m0, m1, r2 = changepoint(annual[c])
    rows.append(dict(series=c, split_year=d.year, mean_before=m0, mean_after=m1,
                     ratio_after_before=m1 / m0 if m0 else np.nan, variance_explained_by_step=r2))
reg = pd.DataFrame(rows)
reg.to_csv(OUT / "regime_summary.csv", index=False)
print("\nRegime summary (best single step change in annual means):\n", reg.round(3).to_string(index=False))

fig, axs = plt.subplots(3, 1, figsize=(11, 9), sharex=True)
panels = [("lakes (level, m)", LAKES), ("q_mean (m3/s)", ["q_mean"]),
          ("flood extent (% of area)", [t for t in TARGETS if t.startswith("ext_")])]
for ax, (ttl, cols) in zip(axs, panels):
    for c in cols:
        s = df[c] * 100 if c.startswith("ext_") else df[c]
        ax.plot(s.index, s.rolling(3, min_periods=1).mean(), label=c, lw=1)
    ax.axvline(pd.Timestamp(f"{C.REGIME_SPLIT}-01-01"), c="k", ls="--", lw=0.8)
    ax.set_ylabel(ttl)
    ax.legend(fontsize=7, ncol=3)
fig.suptitle("Regime check: 3-month means, dashed line = %d" % C.REGIME_SPLIT)
fig.tight_layout()
fig.savefig(OUT / "fig_regimes.png", dpi=130)
plt.close(fig)

# =========================================================== 2. spike check on flood extent
try:
    fd = pd.read_csv(C.OUT / "flood_daily.csv", parse_dates=["date"])
    fd["px"] = fd["recurring_px"] + fd["unusual_px"]
    fd["month"] = fd["date"].dt.to_period("M").dt.to_timestamp()
    g = fd.groupby(["region", "month"])["px"].agg(max_px="max", median_px="median", n_days="count").reset_index()
    g["spike_ratio"] = g["max_px"] / g["median_px"].clip(lower=1)
    top = g.sort_values("max_px", ascending=False).groupby("region").head(6)
    top.to_csv(OUT / "spike_check.csv", index=False)
    print("\nLargest flood-extent months (spike_ratio >> 3 with few days = likely single-day artefact):\n",
          top.round(1).to_string(index=False))
except Exception as e:
    print("spike check skipped:", repr(e))

# =========================================================== 3. features
def build_X(target, lead, groups):
    X = {}
    tm = df.index.month.values
    tgt_m = (tm - 1 + lead) % 12
    X["season_sin"], X["season_cos"] = np.sin(2 * np.pi * tgt_m / 12), np.cos(2 * np.pi * tgt_m / 12)
    y = Y[target]
    for k in (0, 1, 3):
        X[f"own__lag{k}"] = y.shift(k)
    X["own__tr12"] = y.rolling(12, min_periods=12).mean()
    if "lake" in groups or "lakechg" in groups:
        for c in LAKES:
            if "lake" in groups:  # absolute level: can fall outside the training range after a regime shift
                X[f"{c}__lvl"] = df[c]
            X[f"{c}__d3"] = df[c] - df[c].shift(3)
            X[f"{c}__d12"] = df[c] - df[c].shift(12)
    if "rain" in groups:
        for c in RAIN:
            for w in (1, 3, 6):
                X[f"{c}__sum{w}"] = df[c].rolling(w, min_periods=w).sum()
    return pd.DataFrame(X, index=df.index)


FSETS = {"ar": (), "ar+lake": ("lake",), "ar+lakechg": ("lakechg",), "ar+rain": ("rain",), "ar+lake+rain": ("lake", "rain")}


def _clip(x):
    return np.clip(x, -3, 3)  # limits damage when a feature leaves its training range (regime shift)


def ridge():
    return make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), FunctionTransformer(_clip),
                         RidgeCV(alphas=np.logspace(-1, 3.5, 15)))


def hgb():
    return HistGradientBoostingRegressor(max_depth=3, learning_rate=0.05, max_iter=100, min_samples_leaf=8,
                                         l2_regularization=1.0, random_state=C.RANDOM_STATE)


def run_target(target):
    out = []
    last_year = df.index[-1].year
    for lead in C.LEADS:
        y_fut = Y[target].shift(-lead)
        valid = y_fut.notna() & (np.arange(len(df)) >= 12)
        tgt_year = (df.index + pd.DateOffset(months=lead)).year
        Xs = {fs: build_X(target, lead, g) for fs, g in FSETS.items()}
        for yr in range(C.FIRST_TEST_YEAR, last_year + 1):
            tr = valid.values & (tgt_year < yr)
            te = valid.values & (tgt_year == yr)
            if te.sum() == 0 or tr.sum() < 36:
                continue
            idx = df.index[te]
            tmonth = (idx + pd.DateOffset(months=lead)).month
            cutoff = pd.Timestamp(f"{yr}-01-01")
            clim_obs = Y[target][Y.index < cutoff].groupby(Y.index[Y.index < cutoff].month).mean()
            anom = Y[target] - clim_obs.reindex(Y.index.month).values
            base = {
                "clim": clim_obs.reindex(tmonth).values,
                "persist": Y[target][te].values,
                "persist_anom": clim_obs.reindex(tmonth).values + anom[te].values,
                "trail12_anom": clim_obs.reindex(tmonth).values + anom.rolling(12, min_periods=12).mean()[te].values,
            }
            obs = y_fut[te].values
            recs = [("baseline", b, v) for b, v in base.items()]
            for fs, X in Xs.items():
                m = ridge().fit(X[tr], y_fut[tr])
                recs.append((fs, "ridge", m.predict(X[te])))
            m = hgb().fit(Xs["ar+lake+rain"][tr], y_fut[tr])
            recs.append(("ar+lake+rain", "hgb", m.predict(Xs["ar+lake+rain"][te])))
            for fs, mname, pred in recs:
                out.append(pd.DataFrame(dict(
                    target=target, lead=lead, test_year=yr, featureset=fs, model=mname, issue_month=idx,
                    target_month=idx + pd.DateOffset(months=lead), observed_t=obs, predicted_t=pred,
                    observed=inv(target, obs), predicted=inv(target, pred))))
    return pd.concat(out, ignore_index=True)


print("\nRunning expanding-window validation (all targets, leads, feature sets)...")
pred = pd.concat(Parallel(n_jobs=-1)(delayed(run_target)(t) for t in TARGETS), ignore_index=True)
pred.to_csv(OUT / "predictions_v2.csv", index=False)

# =========================================================== 4. skill table
key = ["target", "lead", "issue_month"]
bw = pred[pred.featureset == "baseline"].pivot_table(index=key, columns="model", values="predicted_t").reset_index()
bw.columns = [c if c in key else f"b_{c}" for c in bw.columns]
mod = pred.merge(bw, on=key, how="left")
mod["period"] = np.where(mod.test_year >= C.REGIME_SPLIT, f"from{C.REGIME_SPLIT}", f"pre{C.REGIME_SPLIT}")


def summarise(g):
    e = (g.observed_t - g.predicted_t) ** 2
    mse = e.mean()
    out = dict(n=len(g), rmse=np.sqrt(mse),
               r2=1 - mse / g.observed_t.var() if g.observed_t.var() > 0 else np.nan)
    for b in ("clim", "persist_anom", "trail12_anom"):
        mb = ((g.observed_t - g[f"b_{b}"]) ** 2).mean()
        out[f"skill_vs_{b}"] = 1 - mse / mb if mb > 0 else np.nan
    return pd.Series(out)


rows = []
for scope, sub in (("all", mod), ("pre", mod[mod.period.str.startswith("pre")]), ("post", mod[mod.period.str.startswith("from")])):
    s = sub.groupby(["target", "lead", "featureset", "model"]).apply(summarise).reset_index()
    s["scope"] = scope
    rows.append(s)
skill = pd.concat(rows, ignore_index=True)
skill.to_csv(OUT / "skill_v2.csv", index=False)

head = skill[(skill.scope == "post") & (skill.featureset.isin(["baseline", "ar", C.HEADLINE_SET])) & (skill.model.isin(["ridge", "persist_anom", "trail12_anom"]))]
print(f"\nTest years from {C.REGIME_SPLIT} (trained only on earlier years). skill_vs_trail12_anom > 0 = beats the regime-aware baseline:")
print(head[["target", "lead", "featureset", "model", "r2", "skill_vs_clim", "skill_vs_persist_anom", "skill_vs_trail12_anom"]]
      .round(2).to_string(index=False))

# figure: skill vs lead, post-regime scope, per target
fig, axs = plt.subplots(1, len(TARGETS), figsize=(4.2 * len(TARGETS), 3.8), sharey=True)
axs = np.atleast_1d(axs)
for ax, t in zip(axs, TARGETS):
    s = skill[(skill.target == t) & (skill.scope == "post")]
    for (fs, m), gg in s[(s.featureset != "baseline") & (s.model == "ridge")].groupby(["featureset", "model"]):
        ax.plot(gg.lead, gg.skill_vs_trail12_anom, marker="o", label=fs)
    ax.axhline(0, c="grey", lw=0.8)
    ax.set_title(t)
    ax.set_xlabel("lead (months)")
axs[0].set_ylabel(f"skill vs trail12 baseline (test {C.REGIME_SPLIT}+)")
axs[0].legend(fontsize=7)
fig.tight_layout()
fig.savefig(OUT / "fig_skill_v2.png", dpi=130)
plt.close(fig)

# =========================================================== 5. latest forecast with error band
fc = []
last = df.index[-1]
for t in TARGETS:
    for lead in C.LEADS:
        X = build_X(t, lead, FSETS[C.HEADLINE_SET])
        yf = Y[t].shift(-lead)
        ok = yf.notna().values & (np.arange(len(df)) >= 12)
        m = ridge().fit(X[ok], yf[ok])
        p = float(m.predict(X.loc[[last]])[0])
        e = pred[(pred.target == t) & (pred.lead == lead) & (pred.featureset == C.HEADLINE_SET) &
                 (pred.model == "ridge") & (pred.test_year >= C.INTERVAL_FROM_YEAR)]
        sd = float(np.sqrt(((e.observed_t - e.predicted_t) ** 2).mean())) if len(e) else np.nan
        b = bw[(bw.target == t) & (bw.lead == lead)]
        fc.append(dict(target=t, lead=lead, issue_month=last, target_month=last + pd.DateOffset(months=lead),
                       featureset=C.HEADLINE_SET, predicted=inv(t, p), lo80=inv(t, p - 1.28 * sd),
                       hi80=inv(t, p + 1.28 * sd), err_rmse_transformed=sd,
                       last_observed=float(df[t].iloc[-1])))
pd.DataFrame(fc).to_csv(OUT / "forecast_latest_v2.csv", index=False)
print("\nDone. Results in", OUT)
