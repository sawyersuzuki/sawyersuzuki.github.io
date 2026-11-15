"""Decode one GRIB2 message from bytes and put it on the CONUS grid."""

from __future__ import annotations

import eccodes
import numpy as np

from .. import grid


def decode(message: bytes) -> tuple[np.ndarray, float, float, float]:
    """Return (field north-to-south, first latitude, first longitude, resolution)."""
    gid = eccodes.codes_new_from_message(message)
    try:
        ni = eccodes.codes_get(gid, "Ni")
        nj = eccodes.codes_get(gid, "Nj")
        lat_first = eccodes.codes_get(gid, "latitudeOfFirstGridPointInDegrees")
        lon_first = eccodes.codes_get(gid, "longitudeOfFirstGridPointInDegrees")
        res = eccodes.codes_get(gid, "iDirectionIncrementInDegrees")
        south_to_north = eccodes.codes_get(gid, "jScansPositively")
        values = eccodes.codes_get_values(gid).reshape(nj, ni)
    finally:
        eccodes.codes_release(gid)
    if south_to_north:
        values = values[::-1]
        lat_first = lat_first + res * (nj - 1)
    return values, float(lat_first), float(lon_first), float(res)


def to_conus(field: np.ndarray, lat_first: float, lon_first: float, res: float) -> np.ndarray:
    """Crop (matching 0.25 degree grids) or bilinearly interpolate a global field to CONUS."""
    nj, ni = field.shape
    y = (lat_first - grid.LATS) / res  # fractional row of each target latitude
    x = ((grid.LONS - lon_first) % 360.0) / res  # fractional column, wraps at the seam
    if abs(res - grid.RES) < 1e-9 and np.allclose(y, np.rint(y)) and np.allclose(x, np.rint(x)):
        rows = np.rint(y).astype(int)
        cols = np.rint(x).astype(int) % ni
        return field[np.ix_(rows, cols)].astype(np.float32)
    y0 = np.clip(np.floor(y).astype(int), 0, nj - 2)
    x0 = np.floor(x).astype(int)
    wy = (y - y0)[:, None]
    wx = (x - x0)[None, :]
    xa, xb = x0 % ni, (x0 + 1) % ni
    top = field[np.ix_(y0, xa)] * (1 - wx) + field[np.ix_(y0, xb)] * wx
    bottom = field[np.ix_(y0 + 1, xa)] * (1 - wx) + field[np.ix_(y0 + 1, xb)] * wx
    return (top * (1 - wy) + bottom * wy).astype(np.float32)


def _reduced_gaussian_to_conus(gid) -> np.ndarray:
    """Interpolate a reduced Gaussian field (rows of varying length) to the CONUS grid.

    Linear in longitude within the two Gaussian rows that bracket each target
    latitude, then linear in latitude between them. Used only for early-2024
    AIFS files.
    """
    values = eccodes.codes_get_values(gid)
    pl = eccodes.codes_get_array(gid, "pl")
    row_lats = np.asarray(eccodes.codes_get_array(gid, "distinctLatitudes"), dtype=float)
    if row_lats[0] < row_lats[-1]:
        row_lats = row_lats[::-1]
    starts = np.concatenate([[0], np.cumsum(pl)])
    lon360 = grid.LONS % 360.0

    def row_on_target_lons(j: int) -> np.ndarray:
        n = int(pl[j])
        row = values[starts[j] : starts[j + 1]]
        x = lon360 / (360.0 / n)
        x0 = np.floor(x).astype(int)
        w = x - x0
        return row[x0 % n] * (1 - w) + row[(x0 + 1) % n] * w

    out = np.empty(grid.SHAPE, dtype=np.float32)
    cache: dict[int, np.ndarray] = {}
    for i, lat in enumerate(grid.LATS):
        j = int(np.clip(np.searchsorted(-row_lats, -lat) - 1, 0, len(row_lats) - 2))
        for k in (j, j + 1):
            if k not in cache:
                cache[k] = row_on_target_lons(k)
        w = (row_lats[j] - lat) / (row_lats[j] - row_lats[j + 1])
        out[i] = cache[j] * (1 - w) + cache[j + 1] * w
    return out


def message_to_conus(message: bytes) -> np.ndarray:
    gid = eccodes.codes_new_from_message(message)
    try:
        if eccodes.codes_get(gid, "gridType") == "reduced_gg":
            return _reduced_gaussian_to_conus(gid)
    finally:
        eccodes.codes_release(gid)
    return to_conus(*decode(message))
