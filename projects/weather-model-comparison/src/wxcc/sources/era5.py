"""ERA5 2 m temperature from Google's ARCO-ERA5 Zarr store.

The store keeps one compressed chunk per hour for the whole globe (about
2.4 MB each). We fetch only the hours we need over plain HTTPS, decode them in
memory, and keep just the CONUS crop, so nothing global ever touches disk.

Licence: Copernicus Climate Change Service (C3S) ERA5, redistributable with
attribution ("Contains modified Copernicus Climate Change Service information").
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import numcodecs
import numpy as np
import pandas as pd
import requests
from requests.adapters import HTTPAdapter, Retry

from .. import grid

STORE = "https://storage.googleapis.com/gcp-public-data-arco-era5/ar/full_37-1h-0p25deg-chunk-1.zarr-v3"
VARIABLE = "2m_temperature"
EPOCH = pd.Timestamp("1900-01-01")  # time axis is "hours since 1900-01-01"
CHUNK_MB = 2.4  # typical compressed size of one hourly global chunk
GLOBAL_SHAPE = (721, 1440)

_ROWS, _COLS = grid.global_slices(lat_first=90.0, lon_first=0.0)
_BLOSC = numcodecs.Blosc()


def _session() -> requests.Session:
    s = requests.Session()
    retry = Retry(total=5, backoff_factor=1.0, status_forcelist=(429, 500, 502, 503, 504))
    s.mount("https://", HTTPAdapter(max_retries=retry, pool_maxsize=32))
    return s


@dataclass
class Availability:
    final_through: pd.Timestamp  # last day of quality-controlled ERA5
    prelim_through: pd.Timestamp  # last day of preliminary ERA5T


def availability(session: requests.Session | None = None) -> Availability:
    """Latest dates in the store, read from its metadata."""
    s = session or _session()
    attrs = json.loads(s.get(f"{STORE}/.zattrs", timeout=60).text)
    return Availability(
        pd.Timestamp(attrs["valid_time_stop"]), pd.Timestamp(attrs["valid_time_stop_era5t"])
    )


def chunk_index(time: pd.Timestamp) -> int:
    return int((pd.Timestamp(time) - EPOCH) // pd.Timedelta(hours=1))


def _fetch_one(s: requests.Session, time: pd.Timestamp) -> np.ndarray | None:
    resp = s.get(f"{STORE}/{VARIABLE}/{chunk_index(time)}.0.0", timeout=120)
    if resp.status_code == 404:
        return None  # not written yet; the store's metadata can run ahead of its data
    resp.raise_for_status()
    field = np.frombuffer(_BLOSC.decode(resp.content), dtype="<f4").reshape(GLOBAL_SHAPE)
    crop = field[_ROWS, _COLS]
    return None if np.isnan(crop).any() else crop.copy()


def fetch_t2m(times: pd.DatetimeIndex, workers: int = 16) -> tuple[pd.DatetimeIndex, np.ndarray]:
    """CONUS 2 m temperature in kelvin for the hours that exist: (times, (n, NLAT, NLON))."""
    s = _session()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        fields = list(pool.map(lambda t: _fetch_one(s, t), times))
    keep = [i for i, f in enumerate(fields) if f is not None]
    if not keep:
        return pd.DatetimeIndex([]), np.empty((0, grid.NLAT, grid.NLON), dtype=np.float32)
    return times[keep], np.stack([fields[i] for i in keep])
