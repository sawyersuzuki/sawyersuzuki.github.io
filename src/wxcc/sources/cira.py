"""AI-model forecasts run and published by NOAA/CIRA (the "MLWP" archive).

CIRA runs open AI weather models twice a day from GFS initial conditions and
publishes each run as one large NetCDF file (about 7 GB). We read the file's
small header remotely, look up where each 2 m temperature time step is stored,
and download only those pieces (about 1.4 MB per step).

Reference: Radford et al. 2025, BAMS, doi:10.1175/BAMS-D-24-0057.1.
NOAA data, provided "as is". The underlying model weights have their own
licences (see DECISIONS.md) which govern the models, not NOAA's output files.
"""

from __future__ import annotations

import zlib

import h5py
import numpy as np
import pandas as pd

from .. import grid
from .base import Adapter, RunData, gather_steps
from .http import NotAvailable, RangeFile, get_range

BUCKET = "https://noaa-oar-mlwp-data.s3.amazonaws.com"
T2M_NAMES = ("t2", "t2m", "2t")


def run_url(code: str, init: pd.Timestamp) -> str:
    return f"{BUCKET}/{code}/{init:%Y}/{init:%m%d}/{code}_{init:%Y%m%d%H}_f000_f240_06.nc"


def _unshuffle(raw: bytes, itemsize: int) -> bytes:
    """Reverse HDF5's byte-shuffle filter."""
    return np.frombuffer(raw, dtype=np.uint8).reshape(itemsize, -1).T.tobytes()


class CIRA(Adapter):
    max_step_h = 240
    mb_per_step = 1.45
    # The HDF5 library reads one remote file header at a time per process, so these runs do not
    # speed up with more threads. To go faster, run one `wxcc backfill` process per model.
    wall_s_per_run = 4.5

    def __init__(self, code: str, label: str):
        self.code, self.label = code, label

    def fetch(self, init: pd.Timestamp) -> RunData:
        url = run_url(self.code, init)
        with h5py.File(RangeFile(url), "r") as h:
            name = next((n for n in T2M_NAMES if n in h), None)
            if name is None:
                raise NotAvailable(f"no 2 m temperature variable in {url}")
            ds = h[name]
            shape, dtype = ds.shape, ds.dtype
            if ds.chunks != (1,) + shape[1:] or ds.compression != "gzip":
                raise ValueError(f"unexpected storage layout in {url}: {ds.chunks}, {ds.compression}")
            shuffle = bool(ds.shuffle)
            chunks = {info.chunk_offset[0]: (info.byte_offset, info.size)
                      for info in map(ds.id.get_chunk_info, range(ds.id.get_num_chunks()))}
            times = pd.to_datetime(h["time"][:], unit="s")
            lat_first = float(h["latitude"][0])
            lon_first = float(h["longitude"][0])
        if abs(lat_first - 90.0) > 1e-6 or abs(lon_first) > 1e-6 or shape[1:] != (721, 1440):
            raise ValueError(f"unexpected grid in {url}")
        rows, cols = grid.global_slices(lat_first=90.0, lon_first=0.0)
        step_of = {int((t - init) / pd.Timedelta(hours=1)): i for i, t in enumerate(times)}

        def step(s: int) -> np.ndarray:
            if s not in step_of or step_of[s] not in chunks:
                raise NotAvailable(f"step {s} missing")
            offset, size = chunks[step_of[s]]
            raw = zlib.decompress(get_range(url, offset, size))
            if shuffle:
                raw = _unshuffle(raw, dtype.itemsize)
            return np.frombuffer(raw, dtype=dtype).reshape(shape[1:])[rows, cols].astype(np.float32)

        return gather_steps(
            init, self.steps(init), step,
            source=f"NOAA/CIRA MLWP archive, {self.label} from GFS initial conditions "
                   f"(s3://noaa-oar-mlwp-data/{self.code})",
            detail={"file": url.replace(BUCKET + "/", "")},
        )
