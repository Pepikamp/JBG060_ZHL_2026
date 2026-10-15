"""SLE evidence: which error is worse here, a false alarm (FP) or a missed flood (FN)?

Run from the repository root, AFTER analyse_v2.py:
    python flood_drivers/sle_risk_test.py
Input : flood_drivers/results/v2/predictions_v2.csv  (month-by-month observed vs predicted, expanding window)
Output: flood_drivers/results/v2/sle_confusion.csv, sle_cost_sweep.csv, sle_tests.csv

Definitions
  flood event  = observed value above the EVENT_Q quantile of that target's whole record (same 0.80 as fd_config)
  alert        = forecast above the same threshold
  FN = flood happened, no alert (missed flood)      FP = alert, no flood (false alarm)
Tests (all per target x lead x method):
  1. Exact binomial test: among the wrong calls, is the share of FN different from 50%?
  2. Block bootstrap over test YEARS (months in a year are not independent): 95% CI for FN rate and FP rate.
  3. Cost sweep: total cost = FN*w + FP*1. Break-even w* = the miss-to-false-alarm cost ratio at which the model and a
     simple rule cost the same (direction given in 'verdict'). This is the number to debate with stakeholders.
"""
import numpy as np, pandas as pd
from scipy.stats import binomtest
import fd_config as C  # noqa: E402

EVENT_Q, SEED, NBOOT = C.EVENT_QUANTILE, 0, 2000
V2 = C.RES / "v2"
pred = pd.read_csv(V2 / "predictions_v2.csv", parse_dates=["issue_month", "target_month"])
METHODS = {"model (ar+lake)": ("ar+lake", "ridge"), "rule: last anomaly persists": ("baseline", "persist_anom"),
           "rule: 12-mo mean anomaly": ("baseline", "trail12_anom"), "rule: seasonal average": ("baseline", "clim")}
rng = np.random.default_rng(SEED)
conf, tests, sweep = [], [], []

for tgt, gt in pred.groupby("target"):
    ref = gt[(gt.featureset == "baseline") & (gt.model == "clim") & (gt.lead == gt.lead.min())]
    thr_t = np.quantile(ref.observed_t.dropna(), EVENT_Q)                # threshold in transformed space
    for lead, gl in gt.groupby("lead"):
        for name, (fs, m) in METHODS.items():
            g = gl[(gl.featureset == fs) & (gl.model == m)].dropna(subset=["observed_t", "predicted_t"])
            if g.empty:
                continue
            ev, al = g.observed_t.values > thr_t, g.predicted_t.values > thr_t
            tp, fp, fn, tn = (ev & al).sum(), (~ev & al).sum(), (ev & ~al).sum(), (~ev & ~al).sum()
            fnr, fpr = fn / max(ev.sum(), 1), fp / max((~ev).sum(), 1)
            # 1. binomial test on the wrong calls
            p = binomtest(int(fn), int(fn + fp), 0.5).pvalue if fn + fp > 0 else np.nan
            # 2. block bootstrap over years
            yrs = g.test_year.values; uy = np.unique(yrs); bf, bp, bs = [], [], []
            for _ in range(NBOOT):
                pick = rng.choice(uy, len(uy)); idx = np.concatenate([np.where(yrs == y)[0] for y in pick])
                e, a = ev[idx], al[idx]
                bf.append((e & ~a).sum() / max(e.sum(), 1)); bp.append((~e & a).sum() / max((~e).sum(), 1))
                fn_b, fp_b = (e & ~a).sum(), (~e & a).sum()
                bs.append(fn_b / (fn_b + fp_b) if fn_b + fp_b else np.nan)
            conf.append(dict(target=tgt, lead=lead, method=name, n=len(g), events=int(ev.sum()), TP=tp, FP=fp, FN=fn, TN=tn,
                             miss_rate=fnr, false_alarm_rate=fpr, share_of_errors_that_are_misses=fn / max(fn + fp, 1),
                             miss_rate_lo=np.percentile(bf, 2.5), miss_rate_hi=np.percentile(bf, 97.5),
                             fa_rate_lo=np.percentile(bp, 2.5), fa_rate_hi=np.percentile(bp, 97.5)))
            bs = np.array(bs, float); bs = bs[~np.isnan(bs)]
            p_blk = min(1.0, 2 * min((bs <= 0.5).mean(), (bs >= 0.5).mean())) if len(bs) else np.nan
            tests.append(dict(target=tgt, lead=lead, method=name, FN=fn, FP=fp, p_value_misses_vs_false_alarms=p,
                              p_value_year_bootstrap=p_blk, miss_share_lo=np.percentile(bs, 2.5), miss_share_hi=np.percentile(bs, 97.5)))
            for w in (1, 2, 5, 10, 20, 50):
                sweep.append(dict(target=tgt, lead=lead, method=name, cost_ratio_miss_to_false_alarm=w, total_cost=fn * w + fp))

conf, tests, sweep = pd.DataFrame(conf), pd.DataFrame(tests), pd.DataFrame(sweep)
# break-even w*: model total cost = FN*w + FP. Compare with each simple rule.
#   model has FEWER misses, more false alarms -> model wins only if a miss is worth MORE than w* false alarms
#   model has MORE misses, fewer false alarms -> model wins only if a miss is worth LESS than w* false alarms
#   fewer of both -> model always wins; more of both -> model never wins
rows = []
for (t, l), g in conf.groupby(["target", "lead"]):
    mo = g[g.method.str.startswith("model")]
    if mo.empty:
        continue
    mo = mo.iloc[0]
    for _, r in g[g.method.str.startswith("rule")].iterrows():
        dfn, dfp = r.FN - mo.FN, r.FP - mo.FP          # >0 means the model is better on that error
        if dfn >= 0 and dfp >= 0:
            verdict, w = "model better at any cost ratio", np.nan
        elif dfn <= 0 and dfp <= 0:
            verdict, w = "rule better at any cost ratio", np.nan
        elif dfn > 0:
            verdict, w = "model better if a miss costs MORE than w* false alarms", -dfp / dfn
        else:
            verdict, w = "model better if a miss costs LESS than w* false alarms", dfp / -dfn
        rows.append(dict(target=t, lead=l, vs=r.method, model_FN=mo.FN, rule_FN=r.FN, model_FP=mo.FP, rule_FP=r.FP,
                         breakeven_w=w, verdict=verdict))
be = pd.DataFrame(rows)
# where do the errors happen? before / from REGIME_SPLIT
per = []
for (t, l), g in pred[(pred.featureset == "ar+lake") & (pred.model == "ridge")].groupby(["target", "lead"]):
    thr_t = np.quantile(pred[(pred.target == t) & (pred.featureset == "baseline") & (pred.model == "clim") &
                             (pred.lead == pred.lead.min())].observed_t.dropna(), EVENT_Q)
    for per_name, gg in (("before", g[g.test_year < C.REGIME_SPLIT]), ("from", g[g.test_year >= C.REGIME_SPLIT])):
        ev, al = gg.observed_t > thr_t, gg.predicted_t > thr_t
        per.append(dict(target=t, lead=l, period=f"{per_name} {C.REGIME_SPLIT}", months=len(gg), events=int(ev.sum()),
                        FN=int((ev & ~al).sum()), FP=int((~ev & al).sum())))
pd.DataFrame(per).to_csv(V2 / "sle_by_period.csv", index=False)
conf.round(3).to_csv(V2 / "sle_confusion.csv", index=False)
sweep.to_csv(V2 / "sle_cost_sweep.csv", index=False)
tests.merge(be, on=["target", "lead"], how="left").round(3).to_csv(V2 / "sle_tests.csv", index=False)

# pooled over all targets and leads (model only): share of wrong calls that are misses, resampling years
yc = []
for (t, l), g in pred[(pred.featureset == "ar+lake") & (pred.model == "ridge")].groupby(["target", "lead"]):
    thr_t = np.quantile(pred[(pred.target == t) & (pred.featureset == "baseline") & (pred.model == "clim") &
                             (pred.lead == pred.lead.min())].observed_t.dropna(), EVENT_Q)
    ev, al = g.observed_t > thr_t, g.predicted_t > thr_t
    yc.append(g.assign(FN=(ev & ~al).astype(int), FP=(~ev & al).astype(int)).groupby("test_year")[["FN", "FP"]].sum()
              .assign(target=t, lead=l).reset_index())
yc = pd.concat(yc)
yy = yc.groupby("test_year")[["FN", "FP"]].sum(); years = yy.index.values
share = lambda d: d.FN.sum() / (d.FN.sum() + d.FP.sum())
bsh = [share(yy.loc[rng.choice(years, len(years))]) for _ in range(NBOOT)]
pool = [dict(scope="all sites, all leads", FN=int(yy.FN.sum()), FP=int(yy.FP.sum()), miss_share=share(yy),
             lo=np.percentile(bsh, 2.5), hi=np.percentile(bsh, 97.5), p_year_bootstrap=min(1, 2 * min((np.array(bsh) <= .5).mean(), (np.array(bsh) >= .5).mean())))]
for t, gt in yc.groupby("target"):
    d = gt.groupby("test_year")[["FN", "FP"]].sum(); ys = d.index.values
    b = [share(d.loc[rng.choice(ys, len(ys))]) for _ in range(NBOOT)]; b = np.array(b)[~np.isnan(b)]
    pool.append(dict(scope=t, FN=int(d.FN.sum()), FP=int(d.FP.sum()), miss_share=share(d), lo=np.percentile(b, 2.5),
                     hi=np.percentile(b, 97.5), p_year_bootstrap=min(1, 2 * min((b <= .5).mean(), (b >= .5).mean()))))
pool = pd.DataFrame(pool); pool.round(3).to_csv(V2 / "sle_pooled.csv", index=False)
print("\nPOOLED (share of wrong calls that are misses, 95% CI from resampling years):\n", pool.round(3).to_string(index=False))

m = conf[conf.method.str.startswith("model")]
print("MODEL: misses vs false alarms (alert = forecast above the %.0f%% quantile)\n" % (EVENT_Q * 100))
print(m.merge(tests, on=["target", "lead", "method", "FN", "FP"])[["target", "lead", "events", "FN", "FP", "miss_rate",
      "false_alarm_rate", "p_value_misses_vs_false_alarms"]].round(3).to_string(index=False))
print("\nBreak-even cost ratio w* vs simple rules:")
print(be.round(2).to_string(index=False))
