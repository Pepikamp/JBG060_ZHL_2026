"""Step 1: compress the big raw data into one small monthly table.

Uses the course loaders in processing_data/loading.py (one year at a time, so memory stays low).
Per-year results are cached in processing_data/flood_drivers/cache, so an interrupted run resumes.

Outputs (processing_data/flood_drivers/):
    monthly_dataset.csv     one row per month: discharge, lakes, zone rain/runoff, flood extent per region
    era5_monthly_grid.nc    monthly ERA5 rain/runoff on the full grid (for the lag-correlation map)
    flood_daily.csv         flagged flood pixels per day / region / type
    meta.json               what was used (zones, cell counts, catchment found or not)
"""
import json
import os
import sys
import warnings

import numpy as np
import pandas as pd

import fd_config as C  # noqa: E402

os.chdir(C.ROOT)  # the course loaders use ./raw_data relative paths
sys.path.insert(0, str(C.ROOT))
from processing_data import loading  # noqa: E402

import geopandas as gpd  # noqa: E402
import shapely  # noqa: E402
import xarray as xr  # noqa: E402

warnings.filterwarnings("ignore", category=UserWarning)
C.OUT.mkdir(parents=True, exist_ok=True)
C.CACHE.mkdir(parents=True, exist_ok=True)
meta = {"years": [C.YEARS[0], C.YEARS[-1]]}

# ------------------------------------------------------------------ regions
adm2 = gpd.read_file(C.ADMIN2_FILE).to_crs(4326)
regions = {}
for slug, name in C.REGIONS.items():
    row = adm2[adm2["adm2_name"] == name]
    if row.empty:
        raise SystemExit(f"adm2_name '{name}' not found; options: {sorted(adm2['adm2_name'])[:15]}...")
    regions[slug] = row.iloc[0]
print("Regions:", {k: f"{v['area_sqkm']:.0f} km2" for k, v in regions.items()})


# ------------------------------------------------------------------ upstream catchment (optional)
def upstream_catchment(lon, lat):
    """Union of all HydroBASINS sub-basins upstream of the basin containing (lon, lat)."""
    files = sorted(C.RAW.rglob(C.HYBAS_GLOB))
    if not files:
        print(f"  HydroBASINS file {C.HYBAS_GLOB} not found below raw_data -> using boxes only")
        return None
    b = gpd.read_file(files[0])
    pt = shapely.Point(lon, lat)
    hit = b[b.geometry.contains(pt)]
    if hit.empty:
        hit = b.iloc[[int(b.geometry.distance(pt).values.argmin())]]
    start = int(hit.iloc[0]["HYBAS_ID"])
    ups = {}
    for hid, nd in zip(b["HYBAS_ID"].values, b["NEXT_DOWN"].values):
        ups.setdefault(int(nd), []).append(int(hid))
    seen, stack = {start}, [start]
    while stack:
        for u in ups.get(stack.pop(), []):
            if u not in seen:
                seen.add(u)
                stack.append(u)
    sel = b[b["HYBAS_ID"].isin(seen)]
    print(f"  catchment: {len(sel)} sub-basins, ~{sel['SUB_AREA'].sum():,.0f} km2 upstream of station basin {start}")
    meta["catchment_basins"] = len(sel)
    meta["catchment_km2"] = float(sel["SUB_AREA"].sum())
    return shapely.union_all(sel.geometry.values)


# ------------------------------------------------------------------ discharge
print("\n[1/4] Discharge")
q_all = loading.load_dartmouth_data()
info = pd.read_excel(C.RAW / "Darthmouth Flood Observatory" / "information.xlsx")
st = info[info["area id"] == C.STATION_ID].iloc[0]
station_lon, station_lat = float(st["longitude"]), float(st["latitude"])
q = q_all[C.STATION_ID]
qcol = [c for c in q.columns if "ischarge" in c][0]
q = q[qcol].astype(float).rename("q")
print(f"  station {C.STATION_ID}: {q.index.min().date()} .. {q.index.max().date()}, "
      f"median step {q.index.to_series().diff().median()}, NaN {q.isna().mean():.1%}")
monthly = pd.DataFrame({
    "q_mean": q.resample("MS").mean(),
    "q_max": q.resample("MS").max(),
    "q_n": q.resample("MS").count(),
})

# ------------------------------------------------------------------ lakes
print("\n[2/4] Lake levels")
lakes = loading.load_lake_stations()
from lakes import read_altimetry_txt  # noqa: E402  (course loader drops everything after 2002)
for _name in ("victoria", "Kyoga"):
    lakes[_name] = read_altimetry_txt(C.RAW / "Water levels lakes" / f"water_level_{_name}.txt")
for name, df in lakes.items():
    col = C.LAKE_LEVEL_COLUMN[name]
    s = df[col].astype(float)
    s = s[~s.index.duplicated(keep="first")]
    m = s.resample("MS").mean()
    monthly[f"lake_{name.lower()}"] = m
    print(f"  {name}: {s.index.min().date()} .. {s.index.max().date()}  ({col}); "
          f"months with data: {int(m.notna().sum())}")

# ------------------------------------------------------------------ ERA5
print("\n[3/4] ERA5 rainfall / runoff per year")
catch = upstream_catchment(station_lon, station_lat) if C.USE_CATCHMENT else None
masks, zone_cells = None, {}


def build_masks(lat, lon):
    lon2, lat2 = np.meshgrid(lon, lat)
    out = {}
    in_catch = shapely.contains_xy(catch, lon2, lat2) if catch is not None else None
    if in_catch is not None:
        out["catchment"] = in_catch
    for z, (x0, x1, y0, y1) in C.UPSTREAM_ZONES.items():
        box = (lon2 >= x0) & (lon2 <= x1) & (lat2 >= y0) & (lat2 <= y1)
        m = box & in_catch if in_catch is not None else box
        if m.sum() == 0:
            print(f"  zone {z}: no cells inside catchment, using the whole box")
            m = box
        out[z] = m
    for slug, row in regions.items():
        m = shapely.contains_xy(row.geometry, lon2, lat2)
        if m.sum() == 0:  # small area: use the nearest cell centre
            d = (lon2 - row.geometry.centroid.x) ** 2 + (lat2 - row.geometry.centroid.y) ** 2
            m = d == d.min()
        out[f"local_{slug}"] = m
    return out


daily_parts, grid_parts = [], []
for y in C.YEARS:
    f_d, f_g = C.CACHE / f"era5_daily_{y}.csv", C.CACHE / f"era5_month_{y}.nc"
    if f_d.exists() and f_g.exists():
        daily_parts.append(pd.read_csv(f_d, index_col=0, parse_dates=True))
        grid_parts.append(xr.open_dataset(f_g).load())
        continue
    ds = loading.load_rainfall_runoff(np.array([y]))
    ds = ds[["tp", "ro"]].drop_vars(["number", "expver"], errors="ignore") * 1000.0  # m -> mm per day
    ds = ds.transpose("valid_time", "latitude", "longitude").compute()
    if masks is None:
        masks = build_masks(ds.latitude.values, ds.longitude.values)
        zone_cells = {k: int(v.sum()) for k, v in masks.items()}
        print("  grid cells per zone:", zone_cells)
        meta["zone_cells"] = zone_cells
    cols = {}
    for z, m in masks.items():
        for v in ("tp", "ro"):
            cols[f"{'rain' if v == 'tp' else 'ro'}_{z}"] = ds[v].values[:, m].mean(axis=1)
    d = pd.DataFrame(cols, index=pd.to_datetime(ds.valid_time.values))
    g = ds.resample(valid_time="MS").sum().astype("float32")
    d.to_csv(f_d)
    g.to_netcdf(f_g)
    daily_parts.append(d)
    grid_parts.append(g)
    print(f"  {y}: mean rain {d.filter(like='rain_local').mean().round(2).to_dict()} mm/day")

daily = pd.concat(daily_parts).sort_index()
daily.to_csv(C.OUT / "daily_zone_rain.csv")
rain_m = daily.resample("MS").sum(min_count=1)
monthly = monthly.join(rain_m, how="outer")
xr.concat(grid_parts, dim="valid_time").to_netcdf(C.OUT / "era5_monthly_grid.nc")

# ------------------------------------------------------------------ flood extent
print("\n[4/4] Flood masks per year")
allb = gpd.GeoSeries([r.geometry for r in regions.values()]).total_bounds
bbox = dict(lon_min=allb[0] - 0.05, lat_min=allb[1] - 0.05, lon_max=allb[2] + 0.05, lat_max=allb[3] + 0.05)
fl_parts = []
for y in C.YEARS:
    f = C.CACHE / f"flood_daily_{y}.csv"
    if f.exists():
        fl_parts.append(pd.read_csv(f, parse_dates=["date"]))
        continue
    fm = loading.load_flood_masks(np.array([y]), bbox=bbox)
    rows = []
    for slug, row in regions.items():
        inside = shapely.contains_xy(row.geometry, fm["lon"].values, fm["lat"].values)
        sub = fm[inside]
        cnt = sub.groupby(["date", "flood_type"]).size().unstack(fill_value=0)
        cnt = cnt.reindex(columns=[0, 1], fill_value=0).rename(columns={0: "recurring_px", 1: "unusual_px"})
        cnt["region"] = slug
        rows.append(cnt.reset_index())
    d = pd.concat(rows, ignore_index=True)
    d.to_csv(f, index=False)
    fl_parts.append(d)
    print(f"  {y}: {len(fm):,} pixels in bbox, flagged days per region: "
          f"{d.groupby('region')['date'].nunique().to_dict()}")
fl = pd.concat(fl_parts, ignore_index=True)
fl.to_csv(C.OUT / "flood_daily.csv", index=False)

# pixel ~0.0020833 deg; area shrinks with cos(lat)
for slug, row in regions.items():
    px_km2 = (0.0020833 * 111.32) ** 2 * np.cos(np.radians(row["center_lat"]))
    s = fl[fl["region"] == slug].copy()
    s["total_px"] = s["recurring_px"] + s["unusual_px"]
    s["month"] = s["date"].dt.to_period("M").dt.to_timestamp()
    g = s.groupby("month")
    ext = pd.DataFrame({
        # peak flagged area in the month: robust to cloud-covered days
        f"ext_{slug}": g["total_px"].max() * px_km2 / row["area_sqkm"],
        f"extunusual_{slug}": g["unusual_px"].max() * px_km2 / row["area_sqkm"],
        f"obs_{slug}": g["date"].nunique(),
    })
    monthly = monthly.join(ext, how="outer")
    monthly[[f"ext_{slug}", f"extunusual_{slug}"]] = monthly[[f"ext_{slug}", f"extunusual_{slug}"]].fillna(0.0)
    monthly[f"obs_{slug}"] = monthly[f"obs_{slug}"].fillna(0)  # 0 = no flagged pixel (dry OR cloud/no data)
    print(f"  {slug}: pixel {px_km2*1e6:,.0f} m2, flooded fraction max {monthly[f'ext_{slug}'].max():.2f}")

monthly = monthly.sort_index()
monthly.index.name = "month"
monthly = monthly[(monthly.index.year >= C.YEARS[0]) & (monthly.index.year <= C.YEARS[-1])]
monthly.to_csv(C.OUT / "monthly_dataset.csv")
json.dump(meta, open(C.OUT / "meta.json", "w"), indent=2)
print(f"\nSaved {C.OUT/'monthly_dataset.csv'}  shape {monthly.shape}")
print(monthly.describe().T[["count", "mean", "min", "max"]].round(2).to_string())
