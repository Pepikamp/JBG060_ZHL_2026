# Reproducing Notebook 5: Upstream Rainfall Lead-Time Analysis

This note explains how to obtain the additional hydrography data needed to run
`dashboard_notebooks/05_upstream_rainfall_lead_time_analysis.ipynb`.

## 1. Download the source datasets

1. Open the official [HydroBASINS page](https://www.hydrosheds.org/products/hydrobasins).
2. In the download table, select **Standard → Africa → Download**. Extract the archive.
   HydroBASINS contains nested basin polygons at multiple levels. Keep the original
   downloaded files and filenames; the appropriate level will be selected after
   checking the basin network around the study areas.
3. Open the official [HydroRIVERS page](https://www.hydrosheds.org/products/hydrorivers).
4. In the download table, select **Africa → Shapefile → Download**. Extract the archive.
   Keep all files belonging to the shapefile together (for example, `.shp`, `.shx`,
   `.dbf`, and `.prj`).

Use the official sources above rather than third-party copies. Record the download
date and the version/metadata supplied with each archive so the analysis can be
recreated with the same inputs.

## 2. Place the downloaded files in the repository

From the repository root, create these folders:

```text
raw_data/
└── hydrology/
    ├── hydrobasins_africa/
    │   └── [all extracted HydroBASINS Africa files]
    └── hydrorivers_africa/
        └── [all extracted HydroRIVERS Africa shapefile files]
```

Do not rename individual shapefile components independently. The names of the
files inside the downloaded archives may differ from these examples; the folders
above are recommended locations, not required source filenames.

## 3. Prepare the study-area upstream catchments

The two downloaded datasets are source data; they are **not yet** the final
catchments required by Notebook 5. Before calculating upstream rainfall:

1. Inspect the HydroBASINS basin levels around Ayod, Bor South, and Malakal.
2. Use HydroRIVERS and the HydroBASINS downstream-connectivity attributes to
   check which basin(s) actually drain toward each study area.
3. Document the rule used to associate basin(s) with each study area, including
   the basin level, outlet/location choice, and any manual decisions.
4. Export the validated upstream polygons to:

```text
processed_data/
└── hydrology/
    └── upstream_catchments.geojson
```

The GeoJSON must contain at least these attributes:
- `adm2_name`: exactly one of `Ayod`, `Bor South`, or `Malakal` (or the agreed
  study-area names used in the notebook).
- `geometry`: the selected upstream catchment polygon or polygons.
- `source`: source/provenance description, including HydroBASINS level and how
  the basin was selected.

If a study area has multiple upstream polygons, use a consistent representation
and ensure the notebook's aggregation does not double-count overlapping areas.
Do not create catchments by simply buffering administrative boundaries or
selecting nearby basins: geographic proximity alone does not establish flow
connectivity.

## 4. Run and check Notebook 5

1. Install/use the project's existing Python environment and dependencies.
2. Open `dashboard_notebooks/05_upstream_rainfall_lead_time_analysis.ipynb`.
3. Run the notebook from top to bottom, with the repository root as the working
   directory where required by the existing loading code.
4. Confirm that the catchment GeoJSON is found and that its schema and polygons
   pass the notebook's validation checks.
5. Check the resulting tables and maps before interpreting any lead-time
   correlations.

The notebook's expected output directory is:

```text
processed_data/dashboard/
```

The notebook may write `upstream_weather_lag_correlations.csv` and
`upstream_catchment_weather_daily.csv` there once the catchments are valid.

## 5. Reproducibility and interpretation notes

- Keep the original HydroBASINS and HydroRIVERS downloads unchanged; store derived
  catchments separately in `processed_data/hydrology/`.
- Commit this instruction file and, if licensing and repository size permit, the
  small derived `upstream_catchments.geojson`. If the source archives are too large
  or unsuitable for Git, do not commit them; graders should download them from
  the official links above.
- Include the selected HydroBASINS level, dataset metadata/version, download date,
  catchment-selection method, and any manual corrections in the GeoJSON `source`
  field or a companion methods note.
- A correlation at a given lag is not automatically a usable warning lead time.
  Treat results as exploratory until the signal is checked across years and
  against independent flood/hydrological evidence.
- If `upstream_catchments.geojson` is absent, Notebook 5 cannot calculate
  upstream rainfall lead times; downloading the source datasets alone does not
  complete this preparation step.
