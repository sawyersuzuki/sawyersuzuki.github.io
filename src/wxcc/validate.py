"""Independent check: our ERA5 degree days against NOAA CPC's station-based ones.

CPC computes daily population-weighted degree days per census division from
station observations, as (Tmax + Tmin) / 2 against a 65 F base. It shares no
data or code with this pipeline, which makes it a fair sanity check.
"""

from __future__ import annotations

import io

import numpy as np
import pandas as pd
import requests

from . import store
from .regions import CONUS, CPC_NUMBER

CPC_URL = "https://ftp.cpc.ncep.noaa.gov/htdocs/degree_days/weighted/daily_data/{year}/Population.{kind}.txt"


def parse_cpc(text: str) -> pd.DataFrame:
    """CPC pipe-delimited daily file -> long frame (valid_date, region, value)."""
    lines = text.splitlines()
    header = next(i for i, line in enumerate(lines) if line.startswith("Region|"))
    wide = pd.read_csv(io.StringIO("\n".join(lines[header:])), sep="|", dtype={"Region": str})
    number_to_code = {str(n): code for code, n in CPC_NUMBER.items()} | {CONUS: CONUS}
    long = wide.melt("Region", var_name="d")
    long["region"] = long["Region"].map(number_to_code)
    long = long.dropna(subset=["region"])
    long["valid_date"] = pd.to_datetime(long["d"], format="%Y%m%d")
    return long.dropna(subset=["value"])[["valid_date", "region", "value"]]


def fetch_cpc(year: int, kind: str = "Heating") -> pd.DataFrame:
    resp = requests.get(CPC_URL.format(year=year, kind=kind), timeout=120)
    resp.raise_for_status()
    return parse_cpc(resp.text)


def compare(start: str, end: str, method: str, variable: str = "hdd") -> tuple[pd.DataFrame, pd.DataFrame]:
    """Join stored ERA5 against CPC. Returns (daily joined frame, per-region summary)."""
    ours = store.query(model="era5", start=start, end=end, method=method)
    if ours.empty:
        raise ValueError(f"no ERA5 {method} rows stored between {start} and {end}")
    kind = "Heating" if variable == "hdd" else "Cooling"
    years = sorted(pd.DatetimeIndex(ours["valid_date"]).year.unique())
    cpc = pd.concat(fetch_cpc(y, kind) for y in years).rename(columns={"value": "cpc"})
    ours["valid_date"] = ours["valid_date"].astype("datetime64[ns]")
    joined = ours[["valid_date", "region", variable]].merge(cpc, on=["valid_date", "region"])
    joined["diff"] = joined[variable] - joined["cpc"]

    def stats(g: pd.DataFrame) -> pd.Series:
        return pd.Series(
            {
                "days": len(g),
                "ours_mean": g[variable].mean(),
                "cpc_mean": g["cpc"].mean(),
                "bias": g["diff"].mean(),
                "mae": g["diff"].abs().mean(),
                "bias_pct_of_total": 100 * g["diff"].sum() / max(g["cpc"].sum(), 1e-9),
                "corr": np.corrcoef(g[variable], g["cpc"])[0, 1] if g["cpc"].std() > 0 else np.nan,
            }
        )

    summary = joined.groupby("region").apply(stats, include_groups=False)
    return joined, summary
