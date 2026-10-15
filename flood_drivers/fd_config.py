"""Central settings for the flood-driver analysis. Edit here, not in the scripts.

Run all scripts from the repository root (like the course loaders), e.g.
    python flood_drivers/build_dataset.py
    python flood_drivers/analyse.py
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "raw_data"
OUT = ROOT / "processing_data" / "flood_drivers"      # intermediate data
RES = ROOT / "flood_drivers" / "results"              # tables + figures for report/dashboard
CACHE = OUT / "cache"

# ---------------------------------------------------------------- period
# MODIS/VIIRS flood masks and lake altimetry start ~2002, so 2002-2025 is the
# common period. Shorten (e.g. 2010) if you want to test recency effects.
YEARS = list(range(2002, 2026))

# ---------------------------------------------------------------- targets
# Dartmouth station in South Sudan (information.xlsx: area id 100205, 9.6N 31.6E)
STATION_ID = 100205
ADMIN2_FILE = RAW / "Administrative boundaries" / "ssd_admin2.geojson"
REGIONS = {            # slug -> adm2_name in ssd_admin2.geojson
    "ayod": "Ayod",
    "bor_south": "Bor South",
    "malakal": "Malakal",
}

# ---------------------------------------------------------------- ERA5 zones
# (lon_min, lon_max, lat_min, lat_max). Rough, editable source areas along the
# White Nile system. The ERA5 file only reaches 3S, so Lake Victoria's southern
# part is cut off. The data-driven correlation map in analyse.py is the check on
# whether these boxes are sensible.
UPSTREAM_ZONES = {
    "victoria":    (30.0, 35.5, -3.0, 0.5),    # Lake Victoria basin (north of 3S)
    "kyoga_ug":    (30.0, 34.5, 0.5, 3.5),     # Uganda: Lake Kyoga, Albert Nile
    "bahr_jebel":  (29.0, 34.0, 3.5, 6.5),     # Equatoria, upstream of Bor/Mongalla
    "bahr_ghazal": (24.0, 30.0, 6.0, 10.0),    # western tributaries
    "sobat":       (33.5, 37.0, 5.5, 10.0),    # Baro-Akobo-Sobat, Ethiopian highlands
}
# If HydroBASINS is found, restrict zone cells to the catchment upstream of the station.
USE_CATCHMENT = True
HYBAS_LEVEL = 6
HYBAS_GLOB = "hybas_af_lev06*.shp"   # searched anywhere below raw_data/

# ---------------------------------------------------------------- lakes
# load_lake_stations() returns keys 'victoria', 'Kyoga', 'Albert'
LAKE_LEVEL_COLUMN = {"victoria": "height_egm2008", "Kyoga": "height_egm2008", "Albert": "water_level"}

# ---------------------------------------------------------------- modelling
LEADS = [1, 2, 3, 4, 6]          # forecast lead in months
TARGETS = ["q_mean"] + [f"ext_{r}" for r in REGIONS]
EVENT_QUANTILE = 0.80            # "flood event" = target above this quantile (for AUC)
HOLDOUT_FROM = 2018              # fixed recency test: train < 2017, test >= 2018
ROLL_START = 2010                # expanding-window validation: first test year
MAX_LAG = 12                     # months, for lag-correlation analysis
RANDOM_STATE = 0

# ---------------------------------------------------------------- v2 analysis / dashboard
FIRST_TEST_YEAR = 2010     # expanding-window validation: train on years < Y, test on year Y
REGIME_SPLIT = 2020        # reporting split (pre / from this year); data-driven change points are also reported
EXT_SCALE = 100            # extent (fraction) -> percent before log1p transform
HEADLINE_SET = "ar+lake"   # feature set used for the dashboard forecast
INTERVAL_FROM_YEAR = 2018  # error spread for the forecast interval is taken from test years >= this
