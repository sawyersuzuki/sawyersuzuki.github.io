"""ECMWF IFS (physics) and AIFS (machine-learned) from ECMWF open data on AWS.

Each step is one GRIB2 file with a JSON-lines ``.index`` giving byte offsets, so
only the 2 m temperature message (about 0.3 MB) is downloaded.

The bucket's layout changed over time; ``candidates`` lists them newest first.
IFS was published at 0.4 degrees until January 2024; those fields are
interpolated to the 0.25 degree grid.

Licence: CC BY 4.0, (c) ECMWF. Attribution required; redistribution allowed.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from . import grib
from .base import Adapter, RunData, gather_steps
from .http import NotAvailable, get, get_range

BUCKET = "https://ecmwf-forecasts.s3.eu-central-1.amazonaws.com"


def t2m_range(index_text: str) -> tuple[int, int]:
    for line in index_text.splitlines():
        if '"2t"' in line:
            rec = json.loads(line)
            if rec.get("param") == "2t" and rec.get("type", "fc") in ("fc", "an"):
                return rec["_offset"], rec["_length"]
    raise NotAvailable("no 2t message in index")


def _stream(init: pd.Timestamp) -> str:
    return "oper" if init.hour in (0, 12) else "scda"


def candidates(model: str, init: pd.Timestamp) -> list[str]:
    """Directory prefixes to try for a model and run, newest layout first."""
    base = f"{BUCKET}/{init:%Y%m%d}/{init:%H}z"
    stream = _stream(init)
    if model == "ifs":
        return [f"{base}/ifs/0p25/{stream}", f"{base}/0p25/{stream}", f"{base}/0p4-beta/{stream}"]
    return [f"{base}/aifs-single/0p25/oper", f"{base}/aifs/0p25/oper"]


class _Ecmwf(Adapter):
    model = ""
    label = ""

    def _directory(self, init: pd.Timestamp) -> str:
        stream = "oper" if self.model == "aifs" else _stream(init)
        for directory in candidates(self.model, init):
            try:
                get(f"{directory}/{init:%Y%m%d%H}0000-0h-{stream}-fc.index")
                return directory
            except NotAvailable:
                continue
        raise NotAvailable(f"{self.label} {init:%Y-%m-%d %HZ} not in ECMWF open data")

    def fetch(self, init: pd.Timestamp) -> RunData:
        directory = self._directory(init)
        stream = directory.rsplit("/", 1)[1]

        def step(s: int) -> np.ndarray:
            url = f"{directory}/{init:%Y%m%d%H}0000-{s}h-{stream}-fc"
            offset, length = t2m_range(get(url + ".index").decode())
            return grib.message_to_conus(get_range(url + ".grib2", offset, length))

        resolution = "0.4 deg, interpolated" if "0p4" in directory else "0.25 deg"
        return gather_steps(
            init, self.steps(init), step,
            source=f"ECMWF {self.label} open data, {resolution} (s3://ecmwf-forecasts)",
            detail={"directory": directory.replace(BUCKET + "/", "")},
            workers=5,  # ECMWF's bucket throttles bursts; stay gentle
        )


class IFS(_Ecmwf):
    model, label = "ifs", "IFS HRES"
    max_step_h = 240
    mb_per_step = 0.35

    def steps(self, init: pd.Timestamp) -> list[int]:
        last = 240 if init.hour in (0, 12) else 90
        return list(range(0, last + 1, 6))


class AIFS(_Ecmwf):
    model, label = "aifs", "AIFS Single"
    max_step_h = 360
    mb_per_step = 0.35
