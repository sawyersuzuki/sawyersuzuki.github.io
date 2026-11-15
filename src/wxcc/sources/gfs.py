"""NOAA GFS and NOAA's operational AI model, read from NOAA's public S3 buckets.

Both publish GRIB2 files with a text ``.idx`` listing each field's byte offset,
so we download only the 2 m temperature message (about 0.5-0.9 MB) per step.

Licence: US Government work, public domain (NOAA Open Data Dissemination).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import grib
from .base import Adapter, RunData, gather_steps
from .http import NotAvailable, get, get_range

GFS_BUCKET = "https://noaa-gfs-bdp-pds.s3.amazonaws.com"
AI_BUCKET = "https://noaa-nws-graphcastgfs-pds.s3.amazonaws.com"
T2M = ":TMP:2 m above ground:"
GFS_ATMOS_DIR_FROM = pd.Timestamp("2021-03-23")  # GFS v16 moved files under atmos/
AIGFS_FROM = pd.Timestamp("2026-04-16")


def t2m_range(idx_text: str) -> tuple[int, int | None]:
    """Byte offset and length of the 2 m temperature message from a wgrib2 index."""
    lines = idx_text.strip().splitlines()
    for i, line in enumerate(lines):
        if T2M in line:
            start = int(line.split(":")[1])
            if i + 1 < len(lines):
                return start, int(lines[i + 1].split(":")[1]) - start
            return start, None
    raise NotAvailable("no 2 m temperature message in index")


def _fetch_message(url: str) -> np.ndarray:
    offset, length = t2m_range(get(url + ".idx").decode())
    return grib.message_to_conus(get_range(url, offset, length))


def gfs_url(init: pd.Timestamp, step: int) -> str:
    sub = "atmos/" if init >= GFS_ATMOS_DIR_FROM else ""
    return f"{GFS_BUCKET}/gfs.{init:%Y%m%d}/{init:%H}/{sub}gfs.t{init:%H}z.pgrb2.0p25.f{step:03d}"


class GFS(Adapter):
    max_step_h = 384
    mb_per_step = 0.85

    def fetch(self, init: pd.Timestamp) -> RunData:
        return gather_steps(
            init, self.steps(init), lambda s: _fetch_message(gfs_url(init, s)),
            source="NOAA GFS 0.25 deg (s3://noaa-gfs-bdp-pds)",
        )


def fetch_gfs_analysis(times: pd.DatetimeIndex) -> tuple[pd.DatetimeIndex, np.ndarray]:
    """GFS analysis (the f000 field of each 6-hourly cycle) at the given valid times."""
    from concurrent.futures import ThreadPoolExecutor

    def one(t: pd.Timestamp):
        try:
            return _fetch_message(gfs_url(t, 0))
        except NotAvailable:
            return None

    with ThreadPoolExecutor(max_workers=12) as pool:
        fields = list(pool.map(one, times))
    keep = [i for i, f in enumerate(fields) if f is not None]
    if not keep:
        return pd.DatetimeIndex([]), np.empty((0,))
    return times[keep], np.stack([fields[i] for i in keep])


def ai_url(init: pd.Timestamp, step: int) -> str:
    if init >= AIGFS_FROM:
        return (f"{AI_BUCKET}/aigfs.{init:%Y%m%d}/{init:%H}/model/atmos/grib2/"
                f"aigfs.t{init:%H}z.sfc.f{step:03d}.grib2")
    return (f"{AI_BUCKET}/graphcastgfs.{init:%Y%m%d}/{init:%H}/forecasts_13_levels/"
            f"graphcastgfs.t{init:%H}z.pgrb2.0p25.f{step:03d}")


class AIGFS(Adapter):
    """NOAA's GraphCast-based global model: GraphCastGFS until April 2026, AIGFS since."""

    max_step_h = 384
    mb_per_step = 0.5

    def steps(self, init: pd.Timestamp) -> list[int]:
        # the model has no analysis step of its own in the early archive; f000 exists in both
        return super().steps(init)

    def fetch(self, init: pd.Timestamp) -> RunData:
        version = "AIGFS" if init >= AIGFS_FROM else "GraphCastGFS"
        return gather_steps(
            init, self.steps(init), lambda s: _fetch_message(ai_url(init, s)),
            source=f"NOAA {version} (s3://noaa-nws-graphcastgfs-pds)", detail={"version": version},
        )
