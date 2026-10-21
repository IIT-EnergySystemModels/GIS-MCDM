# H2VSiting

**GIS-MCDM site selection for green hydrogen and other facilities.** A GIS + Multi-Criteria Decision-Making (MCDM) workflow that maps where a facility could be located in a study area. It was developed for green hydrogen (H2V) production plants in Brazil, and it runs for any study area, layers, constraints and criteria that you define in one configuration file, [config.toml](config.toml).

The workflow runs in four Jupyter notebooks:

1. Every input layer is aligned to a common grid of the study area.
2. Cells that break a hard constraint are excluded, and the decision matrix of the remaining cells is built.
3. Objective weights are computed for the criteria.
4. The criteria are aggregated into suitability maps with five MCDM methods, and the results are compared and benchmarked against existing projects.

## Workflow

| # | Notebook | What it does | Main outputs (in `Data/`) |
|---|----------|--------------|---------------------------|
| 1 | [01_Data_Preprocessing.ipynb](01_Data_Preprocessing.ipynb) | Inventories the raw data, builds the anchor grid of the study area at the chosen resolution and aligns every layer to it: resampled rasters, Euclidean distances, presence masks and gravity surfaces. | `Aligned/*.tif`, `Raw Database/Study Area/anchor_grid_<res>.tif` |
| 2 | [02_Matrix_Preparation.ipynb](02_Matrix_Preparation.ipynb) | Builds the hard-exclusion mask for one scenario and the MCDM decision matrix of the viable cells. Plots the criteria distributions and their correlations. | `Exclusion Mask/*.tif`, `Matrices/MCDM_Matrix_<run>.csv` (+ `.json` with its criteria) |
| 3 | [03_Criteria_Weighting.ipynb](03_Criteria_Weighting.ipynb) | Computes objective weights with the Entropy Weight Method (EWM) and CRITIC. Fits a presence–background logistic regression (Firth-penalised, with bootstrap and spatial cross-validation) against existing projects. | `Weights/Criteria_Weights_<run>.csv`, `Logistic Regression/*` |
| 4 | [04_Criteria_Aggregation.ipynb](04_Criteria_Aggregation.ipynb) | Computes suitability scores with WSM, WASPAS, TOPSIS, MOORA and Compromise Programming, then classifies them into five classes (Jenks). Exports maps, measures method agreement (Spearman, Jaccard) and builds the consensus suitable area. Benchmarks the results against existing projects. | `Suitability Scores/*.csv`, `Suitability Maps/*.tif` |

All four notebooks save their figures to `Data/Figures/` as PNG (600 dpi in notebooks 02–04). [run_workflow.py](run_workflow.py) runs the four notebooks in one go, and the notebooks share the helpers in [h2vsiting.py](h2vsiting.py).

[scripts/solar_wind_complementarity.py](scripts/solar_wind_complementarity.py) is an optional pre-processing step. It builds a *Solar-Wind Complementarity* raster from ERA5 data (see [ERA5 complementarity layer](#era5-complementarity-layer)).

## Installation

You need Python 3.11 or later (`config.toml` is read with the standard-library `tomllib`).

```bash
git clone https://github.com/IIT-EnergySystemModels/H2VSiting.git
cd H2VSiting

python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

The versions in `requirements.txt` are the ones used to produce the results. Recent pip releases install `rasterio`, `pyogrio` and `pyproj` from pre-built wheels that already include GDAL/PROJ, so you don't need to install GDAL separately. If pip fails on your platform, create the environment with conda instead (`conda install -c conda-forge geopandas rasterio ...`).

## Using it for your own study

1. Put your data in `Data/Raw Database/`. 
2. Put the outline of your study area (one polygon file, `.shp`, `.gpkg` or `.geojson`, any name) in `Data/Raw Database/Study Area/`.
3. Edit [config.toml](config.toml). Every option is explained in its comments:

| Section | What it defines |
|---------|-----------------|
| `[study_area]` | Folder of the study-area polygon and the projected CRS of the analysis (see below) |
| `[run]` | Default resolution, gravity α, scenario and weights; `interactive`; `reuse_aligned`; `compare_classifications` |
| `[layers.<name>]` | Each input file (`source`, relative to `Raw Database/`) and how 01 turns it into a grid layer: `raster` (resampled), `distance` (Euclidean distance to the features), `presence` (1 inside the features) or `gravity` (Σ magnitude / (distance + offset)^α) |
| `[[constraints]]` | Exclusion rules on a layer: `min`, `max` (a number or a scenario parameter), `exclude` (values), `buffer_m` |
| `[scenarios.<name>]` | Values of the scenario parameters used by the constraints |
| `[[criteria]]` | The criteria of the MCDM: layer, `cost` or `benefit`, figure `label`, optional `transform = "log"` and `scaled = true` |
| `[validation]` | Point layer of existing projects for the logistic regression (03) and the validation (04) |

4. Run the workflow (see [Running the workflow](#running-the-workflow)).

**Missing layers.** Only the study-area polygon is required. If a layer's source file is missing, 01 skips it, and 02 builds the exclusion mask without its constraints and the matrix without its criteria, listing what it skipped. The MCDM needs at least two criteria. Without gravity criteria, runs are tagged `NA` in place of α (for example `MCDM_Matrix_Reference_NA_500m.csv`). Without a projects layer, or with too few projects, 03 skips the logistic regression and 04 skips the benchmarking.

**Study area and CRS.** All layers are reprojected to one projected CRS in metres, set by `crs` in `[study_area]`:

- `""` (default): the CRS of the study-area polygon if it is projected in metres, otherwise the polygon's UTM zone, with a warning.
- A CRS string such as `"EPSG:5880"`: that CRS. Set one for a large study area, where a single UTM zone distorts distances.

Notebooks 02–04 read the CRS from the anchor grid, so you set it only once. The input layers can be in any CRS.

**Distances and gravity near the edge.** Features outside the bounding box of the study area are not counted. If a port or a substation just across the border matters, extend the input layer and the study-area polygon accordingly.

**Method parameters.** The parameters of the methods themselves (thinning distance, background ratio, bootstrap and cross-validation settings in 03; WASPAS λ and the classification methods in 04) are constants at the top of the cells that use them.

## The paper's data

`config.toml` as distributed reproduces the paper. It expects this layout:

```
Data/
└── Raw Database/
    ├── Study Area/                   Brazil polygon (EPSG:5880)
    ├── Elevation&Slope/              Elevation.tif, Slope.tif
    ├── Solar Resource/               Solar Resource.tif
    ├── Wind Resource/                Wind Resource.tif
    ├── Solar-Wind Complementarity/   Solar-Wind Complementarity.tif
    ├── Land Coverage/                Coverage.tif
    ├── Protected Areas/              Protected Areas.shp
    ├── Ports/                        Ports.shp
    ├── Highways/                     Highways.shp
    ├── Gas Pipelines/                Pipelines.shp
    ├── Water Availability/           Superficial Water.gpkg
    ├── Hosting Capacity/             Hosting Capacity.shp
    ├── Hydrogen Demand/              Hydrogen Demand.shp
    └── Hydrogen Projects/            H2V Projects.shp
```

| Layer | Type | Used as | Requirements |
|-------|------|---------|--------------|
| Study area (Brazil) | Polygon | Study area, anchor grid | — |
| Elevation | Raster (m) | Exclusion (max. elevation) | — |
| Slope | Raster (degrees) | Exclusion (max. slope) | — |
| Solar Resource | Raster | Benefit criterion | — |
| Wind Resource | Raster | Benefit criterion | — |
| Solar-Wind Complementarity | Raster (0–1) | Benefit criterion | Built with `scripts/solar_wind_complementarity.py` |
| Land Coverage | Raster (class codes) | Exclusion (land use) | MapBiomas classes; the excluded codes are listed in `config.toml` |
| Protected Areas | Polygon | Exclusion (+1 km buffer) |
| Ports | Point | Cost criterion (distance) | — |
| Highways | Line | Cost criterion and exclusion (distance) | — |
| Gas Pipelines | Line | Cost criterion (distance) | — |
| Superficial Water | Line/polygon | Cost criterion and exclusion (distance) | — |
| Hosting Capacity | Point (substations) | Cost criterion (distance) | — |
| Hydrogen Demand | Point | Benefit criterion (gravity model) | Numeric column `Estimated` (t/year) |
| H2V Projects | Point | Logistic regression and validation | — |

### ERA5 complementarity layer

The *Solar-Wind Complementarity* layer is built from three ERA5 files (*monthly averaged reanalysis by hour of day*, 2010–2023 in the paper, 0.25°, covering the study area) from the [Copernicus Climate Data Store](https://cds.climate.copernicus.eu/). There is one file per variable, named `*_ssrd.nc` (surface solar radiation downwards), `*_u100.nc` and `*_v100.nc` (100 m wind components), for example `era5_brazil_ssrd.nc`. Put them in `Data/Raw Database/Solar-Wind Complementarity/` and run:

```bash
python scripts/solar_wind_complementarity.py
```

The index is (1 − r) / 2, where r is the Pearson correlation between the solar and wind capacity-factor cycles: 1 = fully complementary, 0 = in phase.

## Running the workflow

### All at once

From the repository root, with the environment activated:

```bash
python run_workflow.py
```

The script asks for every parameter first. Press **Enter** to keep the default from `[run]` in `config.toml`, shown in brackets:

| Question | Example |
|----------|---------|
| Notebooks to run | `1-4` (all), `2-4` (layers already aligned), `4` |
| Grid resolution (m) | `500` |
| Gravity α (only if there are gravity criteria) | `1` |
| Scenario | `Reference`, or `all` |
| Weighting method | `EWM`, or `all` |
| Keep aligned layers that already exist? | `n` |

You can give several values, comma-separated (for example α `0.5, 0.75, 1, 2` and scenario `all`): every combination is run. 01 runs once per resolution and α (after the first α, only the gravity layers are recomputed), 02 and 03 once per scenario, and 04 once per weighting method.

The script then runs the notebooks on its own and reports each one as it finishes. Each executed notebook, with all its outputs, is saved in `Data/Executed/` (for example `02_Matrix_Preparation_Reference_1_500m.ipynb`); the notebooks in the repository are not modified. If a notebook fails, the script stops and saves that notebook with the error in `Data/Executed/`.

`python run_workflow.py --defaults` asks nothing and runs all four notebooks with the `[run]` values of `config.toml`.

### One notebook at a time

You can also open the notebooks in Jupyter (`jupyter lab`) or VS Code and run them in order, **01 → 02 → 03 → 04**. Each asks for its parameters in its second cell (Enter keeps the default from `[run]`); with `interactive = false` in `[run]` they use the `[run]` values without asking.

### Outputs

Each run tags its output files with its parameters, `<scenario>_<alpha>_<resolution>` (for example `MCDM_Matrix_Reference_1_500m.csv`), so several scenarios, α values and resolutions live side by side. 04 also adds the weighting method (for example `EWM_Reference_1_500m`). By default, the comparison of four classification methods in 04 runs only for the baseline run, the one set in `[run]` of `config.toml`.

With `reuse_aligned = true`, 01 keeps the aligned layers that already exist; delete those you want recomputed. Keep it `false` when the inputs or the study area change.

### Hardware

At 500 m resolution, the paper's workflow was run on a laptop with 16 GB of RAM. One decision matrix is 0.8–1.4 GB of CSV, and the inputs plus all generated outputs for 12 scenario/α combinations take about 60 GB of disk space. A coarser resolution (for example 1000 m) cuts both memory and disk use by about 4×. The gravity layers are the slowest step of 01; their run time grows with the number of features × grid cells.

### Fonts

The figures use Palatino (Palatino Linotype / TeX Gyre Pagella) and fall back to DejaVu Serif. If a font is missing, matplotlib warns and substitutes another font, and the results do not change.

## Repository structure

```
├── config.toml                 study area, layers, constraints, scenarios, criteria, run defaults
├── run_workflow.py             runs notebooks 01-04 in one go
├── h2vsiting.py                helpers shared by the notebooks
├── 01_Data_Preprocessing.ipynb
├── 02_Matrix_Preparation.ipynb
├── 03_Criteria_Weighting.ipynb
├── 04_Criteria_Aggregation.ipynb
├── scripts/
│   └── solar_wind_complementarity.py
├── requirements.txt
└── Data/                       (not versioned: inputs and all generated outputs)
```

## Citation

If you use this code, please cite the associated article:

> *TODO: authors, title, journal, year, DOI.*
