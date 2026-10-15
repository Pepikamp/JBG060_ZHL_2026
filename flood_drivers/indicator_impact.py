"""Do the indicators (lake levels, rain/runoff) matter equally in every area?

Run from the repository root, AFTER analyse_v2.py:
    python flood_drivers/indicator_impact.py
Input : flood_drivers/results/v2/predictions_v2.csv
Output: flood_drivers/results/v2/indicator_impact.csv        gain of each indicator set over 'own history only' (ar)
        flood_drivers/results/v2/indicator_heterogeneity.csv  are two areas' gains different? (paired, years resampled)

gain = 1 - (squared error with the indicator set) / (squared error of 'ar', same months). 0.20 = 20% smaller error.
Uncertainty: whole test years are resampled (months within a year are not independent). Few years after 2020 => wide ranges.
"""
import numpy as np, pandas as pd
import fd_config as C  # noqa: E402

NBOOT, SEED = 4000, 0
V2 = C.RES / "v2"
p = pd.read_csv(V2 / "predictions_v2.csv")
p = p[p.model == "ridge"].assign(se=lambda d: (d.observed_t - d.predicted_t) ** 2)
SETS = ["ar+lake", "ar+lakechg", "ar+rain", "ar+lake+rain"]
PERIODS = {"all": lambda y: y >= 0, "from %d" % C.REGIME_SPLIT: lambda y: y >= C.REGIME_SPLIT, "before %d" % C.REGIME_SPLIT: lambda y: y < C.REGIME_SPLIT}
rng = np.random.default_rng(SEED)
rows, het = [], []
targets = sorted(p.target.unique())

for pname, f in PERIODS.items():
    q = p[f(p.test_year)]
    years = np.sort(q.test_year.unique())
    draws = [rng.integers(0, len(years), len(years)) for _ in range(NBOOT)]        # same draws for every target/set (paired)
    boot = {}
    for t in targets:
        yt = q[q.target == t]
        tab = yt.pivot_table(index="test_year", columns="featureset", values="se", aggfunc="sum").reindex(years)
        for fs in SETS:
            gain = lambda d: 1 - tab[fs].values[d].sum() / tab["ar"].values[d].sum()
            b = np.array([gain(d) for d in draws])
            boot[(t, fs)] = b
            rows.append(dict(target=t, featureset=fs, period=pname, lead="all", gain=gain(np.arange(len(years))),
                             lo=np.percentile(b, 2.5), hi=np.percentile(b, 97.5), n_years=len(years)))
        for lead, yl in yt.groupby("lead"):                                             # per-lead point estimates
            s = yl.groupby("featureset").se.sum()
            for fs in SETS:
                rows.append(dict(target=t, featureset=fs, period=pname, lead=str(lead), gain=1 - s[fs] / s["ar"],
                                 lo=np.nan, hi=np.nan, n_years=len(years)))
    for fs in SETS:
        for i, a in enumerate(targets):
            for b_ in targets[i + 1:]:
                d = boot[(a, fs)] - boot[(b_, fs)]
                het.append(dict(period=pname, featureset=fs, area_a=a, area_b=b_, gain_a=np.mean(boot[(a, fs)]),
                                gain_b=np.mean(boot[(b_, fs)]), diff=np.median(d), lo=np.percentile(d, 2.5), hi=np.percentile(d, 97.5),
                                p_value=min(1.0, 2 * min((d <= 0).mean(), (d >= 0).mean()))))
imp = pd.DataFrame(rows); hh = pd.DataFrame(het)
imp.round(4).to_csv(V2 / "indicator_impact.csv", index=False)
hh.round(4).to_csv(V2 / "indicator_heterogeneity.csv", index=False)
pd.set_option("display.width", 220)
print(imp[imp.lead == "all"].pivot_table(index=["period", "target"], columns="featureset", values="gain").round(2))
print("\nPairs of areas whose gain from lake levels differs (95% range excludes 0):")
print(hh[(hh.featureset == "ar+lake")].round(2).to_string(index=False))
