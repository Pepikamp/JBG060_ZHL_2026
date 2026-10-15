# Setup before running flood_drivers

Read this once before the first full run, or before a re-run after adding HydroBASINS.
All commands are run from the **repository root** (the folder that contains `flood_drivers/`, `processing_data/` and `raw_data/`).

---

## 1. Folder layout the code expects

```
<repository root>/
├── raw_data/
│   ├── Administrative boundaries/ssd_admin2.geojson
│   ├── Darthmouth Flood Observatory/information.xlsx      (+ the Dartmouth discharge files)
│   ├── Water levels lakes/water_level_victoria.txt
│   ├── Water levels lakes/water_level_Kyoga.txt           (+ the Albert file the course loader reads)
│   ├── (ERA5 rain/runoff and flood-mask files, in the places the course loaders expect)
│   └── hydrobasins/hybas_af_lev06_v1c.shp (+ .shx .dbf .prj ...)   <- your own download, see section 3
├── processing_data/
│   └── loading.py                                          (course loader, imported by build_dataset.py)
└── flood_drivers/
    ├── fd_config.py, build_dataset.py, analyse.py, analyse_v2.py, regime.py, lakes.py
    ├── indicator_impact.py, sle_risk_test.py               (new)
    └── dashboard/app.py
```

`processing_data/flood_drivers/` and `flood_drivers/results/` are created by the scripts. Do not create them by hand.

---

## 2. Python environment

1. Install the course requirements first (`requirements.txt` in the repository root).
2. Then the extra packages:

```
python -m pip install -r flood_drivers/requirements_dashboard.txt
```

3. `build_dataset.py` uses `geopandas`, `shapely` and `xarray`. It calls `shapely.union_all` and `shapely.contains_xy`, which need **shapely 2.1 or newer**. Check with:

```
python -c "import shapely; print(shapely.__version__)"
```

If it is older: `python -m pip install --upgrade shapely`.

---

## 3. HydroBASINS (your own download)

**What it does here.** `build_dataset.py` finds the basin that contains the Dartmouth station (9.6°N, 31.6°E), walks upstream through the sub-basins, and uses that catchment to restrict the ERA5 rain/runoff cells in every upstream zone. Without it, the code falls back to the plain rectangles in `fd_config.py` (it prints a message and continues).

**Which file to download.** The Africa (`af`) HydroBASINS shapefile at **level 6**, the standard version (not the "lake-buffered" one).

**Where to put it.** Anywhere below `raw_data/`. The code searches all sub-folders for the pattern in `fd_config.py`:

```
HYBAS_GLOB = "hybas_af_lev06*.shp"
```

Rules that follow from that pattern:

- The file name must start with `hybas_af_lev06`. A name starting with `hybas_lake_af_...` is **not** matched.
- Keep the `.shp`, `.shx`, `.dbf` and `.prj` files together in the same folder. A `.shp` alone cannot be read.
- If you downloaded another level (for example level 5 or 7), change `HYBAS_GLOB` in `fd_config.py` to match. Do not leave several levels below `raw_data/` that all match the pattern, because only the first match (alphabetical) is used.
- `HYBAS_LEVEL` in `fd_config.py` is not read by the code. Only `HYBAS_GLOB` matters.

**Check that it is found and valid** (run from the repository root):

```
python - <<'EOF'
import geopandas as gpd, pathlib
f = sorted(pathlib.Path("raw_data").rglob("hybas_af_lev06*.shp"))
print("found:", f)
g = gpd.read_file(f[0])
print(len(g), "basins; crs:", g.crs)
assert {"HYBAS_ID", "NEXT_DOWN", "SUB_AREA"} <= set(g.columns), "missing HydroBASINS columns"
print("OK")
EOF
```

On Windows PowerShell, put that code in a file `check_hybas.py` and run `python check_hybas.py` instead.

**What you should see when `build_dataset.py` runs.** In step 3 (ERA5), a line like

```
  catchment: <N> sub-basins, ~<X> km2 upstream of station basin <ID>
```

If you instead see `HydroBASINS file hybas_af_lev06*.shp not found below raw_data -> using boxes only`, the file was not found: the run still finishes, but without the catchment restriction. Fix the name or location and run again.

---

## 4. HydroRIVERS (your own download)

**None of the scripts reads HydroRIVERS.** I searched all scripts and the dashboard for it and found no use. You can leave it in `raw_data/` (it does no harm) or keep it elsewhere. It is not needed to reproduce any result. If you want river lines on a map or in the poster, that needs new code: ask for it separately.

---

## 5. If you already ran `build_dataset.py` before adding HydroBASINS

The ERA5 results are cached per year, and the cache was built **without** the catchment restriction. The code reuses a cache file whenever it exists, so it would silently keep the old numbers.

Before running again, delete the ERA5 cache files:

```
processing_data/flood_drivers/cache/era5_daily_*.csv
processing_data/flood_drivers/cache/era5_month_*.nc
```

Deleting the whole `cache/` folder (as the README suggests) also works, but then the flood masks are rebuilt too, which is slower. The flood-mask files (`flood_daily_*.csv`) do not depend on HydroBASINS and can stay.

Do the same whenever you change `UPSTREAM_ZONES`, `YEARS`, `REGIONS` or `USE_CATCHMENT` in `fd_config.py`.

---

## 6. Run order (full run)

```
python flood_drivers/build_dataset.py      # raw data -> monthly table (slow; cached per year, can be resumed)
python flood_drivers/analyse.py            # lag correlations, lag map, driver importance
python flood_drivers/analyse_v2.py         # regime summary, skill, predictions_v2.csv, forecast
python flood_drivers/indicator_impact.py   # dashboard page 5: do indicators matter equally in every area?
python flood_drivers/sle_risk_test.py      # dashboard page 6: missed floods vs false alarms
streamlit run flood_drivers/dashboard/app.py
```

Dashboard page 7 needs no extra script: it reads `monthly_dataset.csv` from `build_dataset.py`.

If a step fails, fix it and run from that step on. Every step needs the previous ones.

---

## 7. What changes if HydroBASINS changes the rain data

Adding HydroBASINS changes the `rain_*` and `ro_*` columns. Everything after `build_dataset.py` must then be re-run (the run order above), and some numbers may change:

- Results for feature sets that use rain or runoff (`ar+rain`, `ar+lake+rain`), including the "rain helps at Bor South after 2020" result on dashboard page 5.
- The lag correlations and driver importance on dashboard page 2.

Results for `ar+lake`, which is the headline feature set and the one behind the missed-flood vs false-alarm test (page 6), do not use rain or runoff and are not affected by this change. Still, check the numbers on the poster against the new dashboard after re-running.

---

## 8. Common problems

| Message or symptom | Likely cause | Fix |
|---|---|---|
| `using boxes only` | HydroBASINS not found | Section 3: file name, location, sibling files |
| `AttributeError: module 'shapely' has no attribute 'union_all'` | Old shapely | `python -m pip install --upgrade shapely` |
| `ModuleNotFoundError: processing_data` | Not run from repository root, or course `loading.py` missing | `cd` to the root; check `processing_data/loading.py` exists |
| `Missing results: ... Run ... first` in the dashboard | A step in section 6 was skipped | Run that step |
| Numbers look unchanged after adding HydroBASINS | Old ERA5 cache reused | Section 5 |
