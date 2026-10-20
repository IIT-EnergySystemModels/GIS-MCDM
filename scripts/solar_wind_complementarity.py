"""
solar_wind_complementarity.py

Builds the Solar-Wind Complementarity layer used by 01_Data_Preprocessing from three ERA5 NetCDF files
(monthly averaged reanalysis by hour of day: ssrd, u100, v100) and writes a single 0-1 Complementarity
Index GeoTIFF.

Run from the repository root:
    python scripts/solar_wind_complementarity.py
"""

from __future__ import annotations

from pathlib import Path
import numpy as np
import xarray as xr
import rioxarray  # noqa: F401  (registers the .rio accessor)


# --- CONFIGURATION (paths relative to the repository root) ---
REPO_DIR = Path(__file__).resolve().parent.parent
LAYER_DIR = REPO_DIR / "Data" / "Raw Database" / "Solar-Wind Complementarity"

NC_VARIABLES = ("u100", "v100", "ssrd")  # one NetCDF per variable, named *_<variable>.nc (e.g. era5_brazil_u100.nc)
OUTPUT_TIF = LAYER_DIR / "Solar-Wind Complementarity.tif"

# Physical constants for Capacity Factor conversions
V_CUTIN = 3.0    # m/s
V_RATED = 12.0   # m/s
V_CUTOUT = 25.0  # m/s
G_STC = 1000.0   # W/m^2 (PV Standard Test Condition)


# --- PHYSICAL CONVERSIONS ---
def wind_capacity_factor(v):
    """Convert wind speed (m/s) to capacity factor (0-1)."""
    cubic_ramp = (v**3 - V_CUTIN**3) / (V_RATED**3 - V_CUTIN**3)
    in_ramp = (v >= V_CUTIN) & (v < V_RATED)
    at_rated = (v >= V_RATED) & (v < V_CUTOUT)

    cf = xr.zeros_like(v) if isinstance(v, xr.DataArray) else np.zeros_like(v, dtype=float)
    cf = xr.where(in_ramp, cubic_ramp, cf) if isinstance(v, xr.DataArray) else np.where(in_ramp, cubic_ramp, cf)
    cf = xr.where(at_rated, 1.0, cf) if isinstance(v, xr.DataArray) else np.where(at_rated, 1.0, cf)

    return cf.clip(0, 1)


def solar_capacity_factor(ssrd_joules):
    """Convert accumulated SSRD (J/m^2 over 1h) to PV capacity factor (0-1)."""
    ghi = ssrd_joules / 3600.0  # W/m^2
    cf = ghi / G_STC
    return cf.clip(0, 1)


# --- COMPLEMENTARITY INDEX (0 to 1) ---
def compute_complementarity_index(a: xr.DataArray, b: xr.DataArray, dim: str) -> xr.DataArray:
    """
    Computes Pearson correlation (r) and maps it to a 0-1 Complementarity Index:
        CI = (1 - r) / 2

    1.0 = Maximum complementarity (perfect anti-correlation, r = -1)
    0.5 = Uncorrelated (r = 0)
    0.0 = Minimum complementarity (in-phase generation, r = +1)
    """
    a_anom = a - a.mean(dim)
    b_anom = b - b.mean(dim)
    cov = (a_anom * b_anom).mean(dim)
    denom = a.std(dim) * b.std(dim)

    # Handle zero-variance pixels safely (assigned neutral r=0 -> CI=0.5)
    r = xr.where(denom == 0, 0.0, cov / denom)

    ci = (1.0 - r) / 2.0
    return ci.clip(0.0, 1.0)


# --- CLIMATOLOGY BUILDING ---
def _time_dim_name(ds: xr.Dataset) -> str:
    for candidate in ("valid_time", "time"):
        if candidate in ds.coords or candidate in ds.dims:
            return candidate
    raise KeyError("No valid time coordinate found in dataset.")


def build_climatology(ds: xr.Dataset) -> xr.Dataset:
    if "expver" in ds.dims:
        ds = ds.sel(expver=1) if 1 in ds["expver"].values else ds.isel(expver=0)

    time_dim = _time_dim_name(ds)
    # Integer key month*100 + hour (e.g. 113 = January 13h), one group per month-hour
    month_hour = ds[time_dim].dt.month.values * 100 + ds[time_dim].dt.hour.values
    ds = ds.assign_coords(month_hour=(time_dim, month_hour))

    return ds.groupby("month_hour").mean(time_dim)


def find_nc(var: str) -> Path:
    """The single NetCDF file in LAYER_DIR whose name ends in _<var>.nc."""
    found = sorted(LAYER_DIR.glob(f"*_{var}.nc"))
    if len(found) != 1:
        raise FileNotFoundError(f"Expected one *_{var}.nc file in {LAYER_DIR}, found {len(found)}.")
    return found[0]


def load_local_data() -> xr.Dataset:
    """Find the three NetCDF files and build the month-hour climatology of each."""
    paths = [find_nc(var) for var in NC_VARIABLES]

    print("Loading local NetCDF files and building climatology cycle...")
    # Load each file fully into memory first: the files are compressed in large time chunks, so grouping
    # lazily would decompress the same chunks again for every month-hour group (extremely slow).
    climatologies = []
    for path in paths:
        with xr.open_dataset(path) as ds:
            climatologies.append(build_climatology(ds.load()))
    return xr.merge(climatologies, compat="override", join="exact")


# --- EXPORT & MAIN PIPELINE ---
def to_geotiff(da: xr.DataArray, path: Path) -> None:
    da = da.rio.set_spatial_dims(x_dim="longitude", y_dim="latitude")
    da = da.rio.write_crs("EPSG:4326")
    da.rio.to_raster(str(path))


def main() -> None:
    clim = load_local_data()

    print("Calculating wind and solar capacity factors...")
    v100 = np.sqrt(clim["u100"] ** 2 + clim["v100"] ** 2)
    cf_wind = wind_capacity_factor(v100)
    cf_solar = solar_capacity_factor(clim["ssrd"])

    print("Calculating 0-1 Complementarity Index...")
    ci_0_to_1 = compute_complementarity_index(cf_solar, cf_wind, dim="month_hour")

    to_geotiff(ci_0_to_1, OUTPUT_TIF)
    print(f"Done! Saved raster to: {OUTPUT_TIF}")


if __name__ == "__main__":
    main()
