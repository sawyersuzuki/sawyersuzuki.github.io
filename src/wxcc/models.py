"""The model registry: what each series is, where it comes from, how far back it goes."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .sources import cira, ecmwf, gfs
from .sources.base import Adapter


@dataclass(frozen=True)
class Model:
    id: str
    label: str
    family: str  # "physics" or "AI"
    provider: str
    first_init: str  # earliest run available from the free source
    lead_days: int
    cycles: tuple[int, ...]  # run hours (UTC) we archive
    licence: str
    note: str
    adapter: Adapter | None = None

    @property
    def first(self) -> pd.Timestamp:
        return pd.Timestamp(self.first_init)


FORECAST_MODELS: dict[str, Model] = {
    m.id: m
    for m in [
        Model("gfs", "GFS", "physics", "NOAA", "2021-01-01", 16, (0, 12),
              "Public domain (NOAA)", "NOAA's global physics model, 0.25 deg.", gfs.GFS()),
        Model("ifs", "IFS HRES", "physics", "ECMWF", "2023-01-18", 10, (0, 12),
              "CC BY 4.0 (ECMWF)", "ECMWF's high-resolution physics model. 0.4 deg until Jan 2024.",
              ecmwf.IFS()),
        Model("aifs", "AIFS", "AI", "ECMWF", "2024-03-01", 15, (0, 12),
              "CC BY 4.0 (ECMWF)", "ECMWF's operational machine-learned model, started from IFS analysis.",
              ecmwf.AIFS()),
        Model("aigfs", "AIGFS", "AI", "NOAA", "2024-02-05", 16, (0, 12),
              "Public domain (NOAA)",
              "NOAA's GraphCast-based model started from GFS analysis: GraphCastGFS until Apr 2026, AIGFS since.",
              gfs.AIGFS()),
        Model("graphcast", "GraphCast", "AI", "Google DeepMind, run by NOAA/CIRA", "2022-01-01", 10, (0, 12),
              "NOAA output; model weights CC BY-NC-SA 4.0 (unverified)",
              "GraphCast operational, run by CIRA from GFS initial conditions.",
              cira.CIRA("GRAP_v100_GFS", "GraphCast")),
        Model("pangu", "Pangu-Weather", "AI", "Huawei, run by NOAA/CIRA", "2020-10-01", 10, (0, 12),
              "NOAA output; model weights non-commercial (unverified)",
              "Pangu-Weather, run by CIRA from GFS initial conditions. Trained on 1979-2017, so 2021+ events are out of sample.",
              cira.CIRA("PANG_v100_GFS", "Pangu-Weather")),
        Model("fcnv2", "FourCastNet v2", "AI", "NVIDIA, run by NOAA/CIRA", "2020-10-01", 10, (0, 12),
              "NOAA output; model weights BSD-3 (unverified)",
              "FourCastNet v2-small, run by CIRA from GFS initial conditions.",
              cira.CIRA("FOUR_v200_GFS", "FourCastNet v2")),
        Model("aurora", "Aurora", "AI", "Microsoft, run by NOAA/CIRA", "2025-01-01", 10, (0, 12),
              "NOAA output; model weights MIT (unverified)",
              "Aurora, run by CIRA from GFS initial conditions.",
              cira.CIRA("AURO_v100_GFS", "Aurora")),
    ]
}

ANALYSIS_MODELS: dict[str, Model] = {
    m.id: m
    for m in [
        Model("era5", "ERA5", "reanalysis", "ECMWF / Copernicus", "1940-01-01", 0, (),
              "Copernicus licence (attribution)",
              "Reanalysis used as truth. About 7 days behind real time; recent months are preliminary."),
        Model("gfs_anl", "GFS analysis", "analysis", "NOAA", "2021-01-01", 0, (),
              "Public domain (NOAA)",
              "GFS initial conditions, used as provisional truth for the days ERA5 has not reached."),
    ]
}

ALL_MODELS = FORECAST_MODELS | ANALYSIS_MODELS
DEFAULT_UPDATE_MODELS = tuple(FORECAST_MODELS)
