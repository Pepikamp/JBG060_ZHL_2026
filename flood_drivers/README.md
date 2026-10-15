# flood_drivers

Run everything from the repository root (this folder sits next to `processing_data/`).

    python -m pip install -r flood_drivers/requirements_dashboard.txt

    python flood_drivers/build_dataset.py   # raw data -> one small monthly table (cached per year, resumable)
    python flood_drivers/analyse.py         # lag correlations, lag map, driver importance
    python flood_drivers/analyse_v2.py      # regime summary, expanding-window skill vs regime-aware baselines, forecast
    python flood_drivers/indicator_impact.py  # do lake/rain indicators matter equally in every area? (dashboard page 5)
    python flood_drivers/sle_risk_test.py     # missed floods vs false alarms, cost tests (dashboard page 6)
    streamlit run flood_drivers/dashboard/app.py

Settings (years, regions, upstream zones, lead times, test years) are in `fd_config.py`.
If you change zones/years, delete `processing_data/flood_drivers/cache/` first.

Outputs: `flood_drivers/results/` (analyse.py) and `flood_drivers/results/v2/` (analyse_v2.py).
Do not commit `results/` or `processing_data/`.

`regime.py` and the rolling-validation parts of `analyse.py` were edited separately from `analyse_v2.py`; they overlap
in purpose. The dashboard reads `analyse.py` (lag/importance/map) and `analyse_v2.py` (everything else).
