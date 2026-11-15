"""The common CONUS grid every model is cropped to.

All global models used here publish on a regular 0.25 degree lat/lon grid whose
points sit on multiples of 0.25, so cropping needs no interpolation. Latitude
runs north to south (as in ERA5, IFS and GFS files) and longitude west to east
in the -180..180 convention.
"""

from __future__ import annotations

import numpy as np

RES = 0.25
LAT_N, LAT_S = 50.0, 24.0
LON_W, LON_E = -125.0, -66.5

LATS = np.arange(LAT_N, LAT_S - RES / 2, -RES)  # 50.0 ... 24.0
LONS = np.arange(LON_W, LON_E + RES / 2, RES)  # -125.0 ... -66.5
NLAT, NLON = LATS.size, LONS.size
SHAPE = (NLAT, NLON)


def global_slices(lat_first: float = 90.0, lon_first: float = 0.0) -> tuple[slice, slice]:
    """Row/column slices that crop a global 0.25 degree field to the CONUS grid.

    Assumes the global field is north-to-south starting at ``lat_first`` and
    west-to-east starting at ``lon_first`` (0 for the 0..360 convention, -180
    for -180..180). CONUS does not straddle either seam, so one slice suffices.
    """
    row0 = round((lat_first - LAT_N) / RES)
    col0 = round(((LON_W - lon_first) % 360) / RES)
    return slice(row0, row0 + NLAT), slice(col0, col0 + NLON)


def nearest_index(lat: np.ndarray, lon: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Nearest grid row/col for points, plus a mask of points inside the grid."""
    row = np.rint((LAT_N - np.asarray(lat)) / RES).astype(int)
    col = np.rint((np.asarray(lon) - LON_W) / RES).astype(int)
    inside = (row >= 0) & (row < NLAT) & (col >= 0) & (col < NLON)
    return row, col, inside
