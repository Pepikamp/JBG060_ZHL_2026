"""Step 3: regime shift + data checks (no models). Writes to flood_drivers/results/.

* regime_summary.csv   best single mean-shift break date per series, before/after means, effect size
* annual_table.csv     yearly means (for report tables / dashboard)
* fig_regime.png       timeline of discharge, flood extent and lake levels with break dates
* bor_south_spikes.csv months where Bor South flood extent is extreme, with the daily pixel counts around them
"""
import sys
import warnings

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

import fd_config as C  # noqa: E402

warnings.filterwarnings("ignore")
C.RES.mkdir(parents=True, exist_ok=True)
df = pd.read_csv(C.OUT / "monthly_dataset.csv", index_col="month", parse_dates=True).asfreq("MS")

series = ["q_mean"] + [f"ext_{r}" for r in C.REGIONS] + [c for c in df.columns if c.startswith("lake_")]
series = [s for s in series if s in df.columns and df[s].notna().mean() > 0.6]
MIN_SEG = 36  # months on each side of a break


def best_break(x, log=False):
    """Single mean-shift change point (least squares) on the monthly seasonal anomalies.
    log=True: detect the break on log1p(extent in per mille) so single spikes do not drive it."""
    x = x.dropna()
    a = np.log1p(x * 1000) if log else x
    a = a - a.groupby(a.index.month).transform("mean")
    v = a.values
    best, k_best = np.inf, None
    for k in range(MIN_SEG, len(v) - MIN_SEG):
        sse = ((v[:k] - v[:k].mean()) ** 2).sum() + ((v[k:] - v[k:].mean()) ** 2).sum()
        if sse < best:
            best, k_best = sse, k
    return x.index[k_best], x.iloc[:k_best], x.iloc[k_best:], a.std()


rows, breaks = [], {}
for s in series:
    d, before, after, sd = best_break(df[s], log=s.startswith("ext_"))
    breaks[s] = d
    unit = 100 if s.startswith("ext_") else 1
    rows.append(dict(series=s, break_month=d.strftime("%Y-%m"), mean_before=before.mean() * unit,
                     mean_after=after.mean() * unit, ratio_after_before=after.mean() / before.mean() if before.mean() else np.nan,
                     shift_in_sd=(np.log1p(after * 1000).mean() - np.log1p(before * 1000).mean() if s.startswith("ext_") else after.mean() - before.mean()) / sd,
                     unit="% of area" if s.startswith("ext_") else "native"))
summ = pd.DataFrame(rows)
summ.to_csv(C.RES / "regime_summary.csv", index=False)
print("Single best mean-shift per series (shift_in_sd = shift relative to seasonally adjusted month-to-month sd):")
print(summ.round(3).to_string(index=False))

ann = df[series + [c for c in df.columns if c.startswith("rain_") and "catchment" in c]].groupby(df.index.year).mean()
ann.index.name = "year"
ann.to_csv(C.RES / "annual_table.csv")

fig, axs = plt.subplots(3, 1, figsize=(11, 8), sharex=True)
for ax, group, ttl in [(axs[0], ["q_mean"], "discharge (station)"),
                       (axs[1], [s for s in series if s.startswith("ext_")], "flood extent (log scale, % of area)"),
                       (axs[2], [s for s in series if s.startswith("lake_")], "lake level (z-score)")]:
    for s in group:
        v = df[s]
        if s.startswith("ext_"):
            v = v * 100
        if s.startswith("lake_"):
            v = (v - v.mean()) / v.std()
        ax.plot(v.index, v, lw=1, label=s)
        ax.axvline(breaks[s], lw=0.8, ls="--", c=ax.lines[-1].get_color())
    if ttl.startswith("flood"):
        ax.set_yscale("symlog", linthresh=0.01)
    ax.set_title(ttl, fontsize=10)
    ax.legend(fontsize=7, ncol=4)
fig.tight_layout()
fig.savefig(C.RES / "fig_regime.png", dpi=130)
plt.close(fig)

# ------------------------------------------------------------ Bor South spike check
if "ext_bor_south" in df.columns and (C.OUT / "flood_daily.csv").exists():
    raw = df["ext_bor_south"]
    med = raw.median()
    mad = (raw - med).abs().median() or raw.std()
    out = df.loc[(raw - med) / (1.4826 * mad) > 8, ["ext_bor_south", "obs_bor_south"]].copy()
    fl = pd.read_csv(C.OUT / "flood_daily.csv", parse_dates=["date"])
    fl = fl[fl.region == "bor_south"].copy()
    fl["px"] = fl.recurring_px + fl.unusual_px
    rows = []
    for m in out.index:
        w = fl[(fl.date >= m - pd.Timedelta(days=15)) & (fl.date < m + pd.offsets.MonthEnd(1) + pd.Timedelta(days=15))]
        rows.append(dict(month=m.strftime("%Y-%m"), monthly_extent=out.loc[m, "ext_bor_south"],
                         days_with_records=int(out.loc[m, "obs_bor_south"]),
                         max_daily_pixels=int(w.px.max()) if len(w) else 0,
                         median_daily_pixels=float(w.px.median()) if len(w) else 0,
                         flagged_days_in_window=int(w.date.nunique())))
    sp = pd.DataFrame(rows)
    sp.to_csv(C.RES / "bor_south_spikes.csv", index=False)
    print("\nBor South extreme months (check if one or two days drive the month = likely artefact):")
    print(sp.to_string(index=False) if len(sp) else "none")
print("\nDone. Results in", C.RES)
