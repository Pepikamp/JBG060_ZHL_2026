# Beyond the Flood Warning: flood dynamics, warning errors and anticipatory action in South Sudan

TU/e Data Challenge (JBG060) | Zero Hunger Lab | ZOA International

## 1. Introduction and overview

**Problem.** Anticipatory Action (AA) acts before a flood arrives, but it needs a warning that can be trusted. A warning can fail in two ways: a *missed flood* leaves communities unprepared, and a *false alarm* wastes scarce resources and erodes trust. We study how flood forecasts behave in three areas of South Sudan (Ayod, Bor South, Malakal) and how the unequal consequences of the two errors should shape their evaluation.

**What the code does.**
1. Builds one monthly dataset (2002-2025) from flood extent, upstream lake levels, river discharge and rainfall/runoff.
2. Detects the change in flood behaviour around 2020 and tests which indicators (lake levels, rain) improve forecasts, area by area.
3. Forecasts flood extent 1-6 months ahead, tested only on years the model has not seen (2010-2025), and compares it with simple rules such as "next month looks like last month".
4. Counts missed floods and false alarms, with uncertainty ranges, and compares options under a chosen cost ratio.
5. Offers an interactive dashboard (Streamlit) where stakeholders can explore the results and set their own cost ratio.

**Main entry point:** `analysis_pipeline.ipynb`. Running it executes the whole analysis and shows every result used in the poster and the reports.

## 2. Installation instructions

Requirements: Python 3.11 or newer (numpy 2.4 needs it). Developed with Python **[fill in: output of `python --version`]**.

```
python -m venv .venv
.venv\Scripts\activate            # Windows   (macOS/Linux: source .venv/bin/activate)
python -m pip install -r requirements.txt
```

The code needs `shapely` 2.1 or newer and the packages in `requirements.txt` at the pinned versions. If you use VS Code, select the `.venv` interpreter as the notebook kernel.

### Input data

Raw data is included in `raw_data/`. Only these parts are used:

| Folder in `raw_data/` | Content | Source |
|---|---|---|
| `Darthmouth Flood Observatory/` | River discharge (station 100205) and station list | Dartmouth Flood Observatory, via the course |
| `Water levels lakes/` | Lake levels (Victoria, Kyoga, Albert) from altimetry | Provided by the course |
| `rainfall and runoff/` | ERA5 rainfall and runoff, one file per year | ERA5 (ECMWF/Copernicus), via the course |
| `flood_masks/` | Daily flood masks (flood extent) | NASA near-real-time flood products, via the course |
| `Administrative boundaries/` | `ssd_admin2.geojson`: the three areas | Provided by the course |
| `hydrobasins/` | `hybas_af_lev06_v1c.shp` and its sibling files | HydroBASINS, Africa, level 6. Lehner, B. & Grill, G. (2013). Hydrological Processes 27(15). https://www.hydrosheds.org |

HydroBASINS restricts the rain and runoff data to the catchment upstream of the station. The code finds the file anywhere below `raw_data/` by the pattern `hybas_af_lev06*.shp` (set in `flood_drivers/fd_config.py`). If it is missing, the run prints "using boxes only" and continues without the catchment restriction, which changes the rain and runoff columns. Keep the `.shp`, `.shx`, `.dbf` and `.prj` files together.

## 3. Usage and examples

Run from the folder that contains this README.

**Notebook (recommended).** Open `analysis_pipeline.ipynb` and choose Run All.
- `RUN_PIPELINE = True`: re-runs every step from the raw data. The first step is slow, because it reads the daily rainfall and flood-mask files year by year. Intermediate results are cached in `processing_data/flood_drivers/cache/`, so a stopped run can be resumed.
- `RUN_PIPELINE = False`: only displays the results already stored in `flood_drivers/results/`.

**Command line (same steps as the notebook).**
```
python flood_drivers/build_dataset.py      # raw data -> monthly table
python flood_drivers/analyse.py            # lag correlations, driver importance
python flood_drivers/analyse_v2.py         # regime summary, forecasts, skill scores
python flood_drivers/indicator_impact.py   # do indicators matter equally in every area?
python flood_drivers/sle_risk_test.py      # missed floods vs false alarms, uncertainty ranges
python flood_drivers/make_poster_figures.py
streamlit run flood_drivers/dashboard/app.py
```
Each step needs the previous ones. If you change the input data, the years, the zones or `USE_CATCHMENT` in `flood_drivers/fd_config.py`, delete `processing_data/flood_drivers/cache/` first, otherwise the cached results are reused.

### Folder structure

```
README.md                      this file (must stay outside the folders)
requirements.txt               packages and versions
analysis_pipeline.ipynb        runs and shows the full analysis
flood_drivers/
    fd_config.py               settings: years, areas, zones, lead times, thresholds
    build_dataset.py           preprocessing: raw data -> monthly_dataset.csv
    lakes.py                   reader for the lake altimetry text files
    analyse.py                 lag correlations and driver importance
    analyse_v2.py              regime summary, forecasts, skill, expanding-window test
    indicator_impact.py        value of each indicator, per area, with uncertainty
    sle_risk_test.py           missed floods vs false alarms, cost ratio tests
    make_poster_figures.py     poster figure: misses vs false alarms
    dashboard/app.py           Streamlit dashboard
    results/                   all tables and figures the scripts write (v2/ holds the final ones)
processing_data/
    loading.py                 course loader (unchanged)
    flood_drivers/             intermediate data written by build_dataset.py
raw_data/                      input data (see above)
```

### Where the poster and report numbers come from

| Poster / report item | Notebook section | File in `flood_drivers/results/v2/` |
|---|---|---|
| Flood extent after vs before the shift (x15, x38, x2.7), lake level change | 2 | `regime_summary.csv` |
| Table 1: lake levels and rain add value? Figure 2 | 3 | `indicator_impact.csv`, `indicator_heterogeneity.csv` |
| Table 1: floods missed and false alarms at 1 month | 4 | `sle_confusion.csv` |
| Figure 3: share of wrong forecasts that are missed floods | 4 | `sle_pooled.csv`, `poster_figures/` |
| Figure 4: cost simulator (ratio of 5) | 4 and dashboard page 6 | `sle_confusion.csv` |
| Model vs simple rules (takeaway 1) | 5 | `skill_v2.csv` |

### Definitions used throughout

- **Flood event:** a month in the top 20% of that area's flood extent.
- **Alert:** issued when the forecast exceeds the same threshold. The alert level is fixed.
- **Missed flood:** a flood without an alert. **False alarm:** an alert without a flood.
- **Cost ratio:** one missed flood counts as this many false alarms (default 5; set by the stakeholder).
- **Test:** every forecast uses only earlier years and is judged on later months (2010-2025).

## 4. Troubleshooting and FAQs

| Message or symptom | Likely cause | Fix |
|---|---|---|
| `HydroBASINS file ... not found ... using boxes only` | The shapefile is missing or named differently | Put `hybas_af_lev06*.shp` and its sibling files below `raw_data/`, or change `HYBAS_GLOB` in `fd_config.py` |
| `ModuleNotFoundError: processing_data` | Run from the wrong folder | Run from the folder containing this README |
| `AttributeError: ... union_all` | `shapely` older than 2.1 | `python -m pip install -r requirements.txt` |
| `FileNotFoundError: ... not found. Set RUN_PIPELINE = True` | A results file is missing | Set `RUN_PIPELINE = True`, or copy `flood_drivers/results/` into place |
| "Missing results ... Run ... first" in the dashboard | A step was skipped | Run the step the message names |
| Numbers unchanged after changing inputs or settings | Old cache reused | Delete `processing_data/flood_drivers/cache/` and re-run |
| The first step takes a long time | It reads the daily files year by year | Wait, or use `RUN_PIPELINE = False` to view the stored results |

## 5. Credits and acknowledgements

- Course loader `processing_data/loading.py`, data and challenge: TU/e JBG060, Zero Hunger Lab and ZOA International.
- Data: Dartmouth Flood Observatory; ERA5 (ECMWF/Copernicus); lake altimetry and flood masks as supplied by the course; HydroBASINS (Lehner & Grill, 2013, https://www.hydrosheds.org).
- Libraries: numpy, pandas, scipy, scikit-learn, xarray, netCDF4, geopandas, shapely, matplotlib, plotly, streamlit (see `requirements.txt`).
- Cost-ratio range used as a starting value: benefit-cost ratios reported for flood early warning by the Global Commission on Adaptation (2019) and the WMO. These are not specific to South Sudan.
- AI assistance: **[confirm and edit to match the course AI-use rules]** parts of the code (the analysis scripts, the dashboard pages and this documentation) were developed with help from an AI assistant (Claude, Anthropic) and reviewed by the team.

## 6. Legal and ethical considerations

- **Not an operational warning system.** The results support discussion of thresholds and trade-offs for ZOA and partners. They need further validation before they are used for decisions. A "no alert" must never be read as "safe".
- **The cost ratio is an assumption.** The default of 5 is a starting value from studies elsewhere. Deciding how bad a missed flood is compared with a false alarm is a social, ethical and governance choice for ZOA, partners and affected communities, not a property of the model.
- **Unequal consequences.** Missed floods can cause irreversible harm, while false alarms cost resources and trust. Areas also differ in how well the data support a forecast; Bor South is not ready for a data trigger.
- **Short record after the change around 2020.** Only about six test years follow the shift, so uncertainty ranges are wide and the shift needs confirming.
- **Data limits.** Flood extent comes from remote-sensing masks and was not checked against local observations. The land-cover data was too poor to say which anticipatory action fits each area. The forecasts have not been validated with communities.
- **Privacy.** The data are aggregated environmental measurements. No personal data are used.