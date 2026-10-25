"""Poster-ready figure: missed floods vs false alarms (white background, large text).

Run after sle_risk_test.py, from the repository root OR from inside flood_drivers/:
    python flood_drivers/make_poster_figures.py      (or)      python make_poster_figures.py
Input : flood_drivers/results/v2/sle_pooled.csv
Output: flood_drivers/results/v2/poster_figures/fig_misses_vs_false_alarms.png (300 dpi) and .svg
"""
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import fd_config as C  # noqa: E402  (works because this file sits next to fd_config.py)

V2 = C.RES / "v2"
OUT = V2 / "poster_figures"
OUT.mkdir(parents=True, exist_ok=True)
AREA = {"q_mean": "River discharge", "ext_bor_south": "Bor South", "ext_ayod": "Ayod", "ext_malakal": "Malakal"}
MISS, ALARM, INK = "#c2410c", "#1d5fb8", "#14213d"

pool = pd.read_csv(V2 / "sle_pooled.csv").set_index("scope")
order = [t for t in ("q_mean", "ext_bor_south", "ext_ayod", "ext_malakal") if t in pool.index]
rows = [(AREA[t], pool.loc[t]) for t in order] + [("All areas", pool.loc["all sites, all leads"])]
ypos = list(range(len(order), 0, -1)) + [-0.3]        # extra gap before "All areas"

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 15})
fig, ax = plt.subplots(figsize=(8, 4.6), dpi=300)
for y, (name, r) in zip(ypos, rows):
    m, a = r.miss_share * 100, (1 - r.miss_share) * 100
    ax.barh(y, m, color=MISS, height=0.62)
    ax.barh(y, a, left=m, color=ALARM, height=0.62)
    if m > 6:
        ax.text(m / 2, y, f"{m:.0f}%", ha="center", va="center", color="white", fontweight="bold")
    if a > 6:
        ax.text(m + a / 2, y, f"{a:.0f}%", ha="center", va="center", color="white", fontweight="bold")
    ax.errorbar(m, y + 0.43, xerr=[[m - r.lo * 100], [r.hi * 100 - m]], fmt="o", color=INK, ms=4, capsize=3, lw=1.3)
ax.axvline(50, color=INK, ls="--", lw=1.2)
ax.set_yticks(ypos)
ax.set_yticklabels([f"{n}\n({int(r.FN)} missed, {int(r.FP)} false alarms)" if n != "All areas" else f"All areas\n({int(r.FN)} vs {int(r.FP)})"
                    for n, r in rows], fontsize=12)
ax.set_xlim(0, 100)
ax.set_xlabel("Share of wrong calls (%)")
for s in ("top", "right", "left"):
    ax.spines[s].set_visible(False)
ax.tick_params(axis="y", length=0)
ax.legend(handles=[plt.Rectangle((0, 0), 1, 1, color=MISS), plt.Rectangle((0, 0), 1, 1, color=ALARM)],
          labels=["Missed floods", "False alarms"], loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=2, frameon=False)
fig.tight_layout()
fig.savefig(OUT / "fig_misses_vs_false_alarms.png", dpi=300, facecolor="white")
fig.savefig(OUT / "fig_misses_vs_false_alarms.svg", facecolor="white")
print("saved:", OUT / "fig_misses_vs_false_alarms.png")
