"""Population weights on the CONUS grid, built from 2020 Census tract centres.

Each census tract's population is assigned to the grid point nearest its
population centre. Summing by grid point gives a population field that is used
to average gridded degree days into regional numbers.

Source: US Census Bureau, 2020 Centers of Population by census tract (public
domain).
"""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from . import grid
from .regions import CONUS, REGIONS, STATE_TO_DIVISION

CENSUS_URL = (
    "https://www2.census.gov/geo/docs/reference/cenpop2020/tract/CenPop2020_Mean_TR.txt"
)
DEFAULT_PATH = Path("data/static/pop_weights.parquet")


def fetch_tract_centres(url: str = CENSUS_URL) -> pd.DataFrame:
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    return pd.read_csv(
        io.StringIO(resp.content.decode("utf-8-sig")),
        dtype={"STATEFP": str, "COUNTYFP": str, "TRACTCE": str},
    )


def build_cell_population(tracts: pd.DataFrame) -> pd.DataFrame:
    """Aggregate tract populations to grid cells: one row per (cell, division)."""
    df = tracts[tracts["STATEFP"].isin(STATE_TO_DIVISION)].copy()
    row, col, inside = grid.nearest_index(df["LATITUDE"].to_numpy(), df["LONGITUDE"].to_numpy())
    df["row"], df["col"] = row, col
    df["division"] = df["STATEFP"].map(STATE_TO_DIVISION)
    df = df[inside & (df["POPULATION"] > 0)]
    out = (
        df.groupby(["division", "row", "col"], as_index=False)["POPULATION"]
        .sum()
        .rename(columns={"POPULATION": "population"})
    )
    out["lat"] = grid.LATS[out["row"]]
    out["lon"] = grid.LONS[out["col"]]
    return out.sort_values(["division", "row", "col"]).reset_index(drop=True)


def weight_matrix(cells: pd.DataFrame) -> np.ndarray:
    """(n_regions, NLAT*NLON) matrix; each row sums to 1. Row order = REGIONS."""
    w = np.zeros((len(REGIONS), grid.NLAT * grid.NLON))
    flat = cells["row"].to_numpy() * grid.NLON + cells["col"].to_numpy()
    pop = cells["population"].to_numpy(dtype=float)
    for i, region in enumerate(REGIONS):
        sel = np.ones(len(cells), bool) if region == CONUS else (cells["division"] == region).to_numpy()
        np.add.at(w[i], flat[sel], pop[sel])
        total = w[i].sum()
        if total <= 0:
            raise ValueError(f"no population found for region {region}")
        w[i] /= total
    return w


def regional_mean(field: np.ndarray, w: np.ndarray) -> np.ndarray:
    """Population-weighted regional means of ``field`` (..., NLAT, NLON) -> (..., n_regions)."""
    flat = np.asarray(field, dtype=np.float64).reshape(*field.shape[:-2], -1)
    return flat @ w.T


def load(path: Path = DEFAULT_PATH) -> np.ndarray:
    if not Path(path).exists():
        raise FileNotFoundError(f"{path} not found; run `wxcc weights` to build it")
    return weight_matrix(pd.read_parquet(path))


def build_and_save(path: Path = DEFAULT_PATH) -> pd.DataFrame:
    cells = build_cell_population(fetch_tract_centres())
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    cells.to_parquet(path, index=False)
    return cells
