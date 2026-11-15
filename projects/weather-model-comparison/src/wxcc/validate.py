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


# ----------------------------------------------------------------------------- station check
# Large-city airport stations (Iowa Environmental Mesonet ids): one or two per major metro.
STATIONS = [
    ("LGA", "NY_ASOS", 40.78, -73.87, "MA"), ("PHL", "PA_ASOS", 39.87, -75.24, "MA"),
    ("BOS", "MA_ASOS", 42.36, -71.01, "NE"), ("BDL", "CT_ASOS", 41.94, -72.68, "NE"),
    ("DCA", "VA_ASOS", 38.85, -77.03, "SA"), ("ATL", "GA_ASOS", 33.64, -84.43, "SA"),
    ("CLT", "NC_ASOS", 35.22, -80.94, "SA"), ("MCO", "FL_ASOS", 28.43, -81.31, "SA"),
    ("ORD", "IL_ASOS", 41.98, -87.90, "ENC"), ("DTW", "MI_ASOS", 42.21, -83.35, "ENC"),
    ("CMH", "OH_ASOS", 39.99, -82.88, "ENC"), ("IND", "IN_ASOS", 39.72, -86.29, "ENC"),
    ("MSP", "MN_ASOS", 44.88, -93.22, "WNC"), ("STL", "MO_ASOS", 38.75, -90.37, "WNC"),
    ("MCI", "MO_ASOS", 39.30, -94.71, "WNC"), ("OMA", "NE_ASOS", 41.30, -95.89, "WNC"),
    ("BNA", "TN_ASOS", 36.12, -86.68, "ESC"), ("BHM", "AL_ASOS", 33.56, -86.75, "ESC"),
    ("DFW", "TX_ASOS", 32.90, -97.02, "WSC"), ("IAH", "TX_ASOS", 29.98, -95.36, "WSC"),
    ("SAT", "TX_ASOS", 29.53, -98.47, "WSC"), ("OKC", "OK_ASOS", 35.39, -97.60, "WSC"),
    ("DEN", "CO_ASOS", 39.85, -104.66, "MTN"), ("PHX", "AZ_ASOS", 33.43, -112.00, "MTN"),
    ("LAS", "NV_ASOS", 36.08, -115.15, "MTN"), ("SLC", "UT_ASOS", 40.77, -111.97, "MTN"),
    ("BUR", "CA_ASOS", 34.20, -118.36, "PAC"), ("SAC", "CA_ASOS", 38.51, -121.49, "PAC"),
    ("SJC", "CA_ASOS", 37.36, -121.92, "PAC"), ("SEA", "WA_ASOS", 47.44, -122.31, "PAC"),
    ("PDX", "OR_ASOS", 45.59, -122.60, "PAC"),
]
IEM_URL = "https://mesonet.agron.iastate.edu/api/1/daily.json?station={station}&network={network}&year={year}&month={month}"


def station_check(year: int, month: int) -> pd.DataFrame:
    """ERA5 at the nearest grid cell vs airport stations, as (Tmax+Tmin)/2 in F.

    Answers one question: is ERA5 itself warmer than observations where people
    live? If yes, the gap to NOAA CPC degree days is an ERA5 bias; if no, it
    comes from how CPC averages stations over climate divisions.
    """
    from . import degree_days as dd
    from . import grid
    from .sources import era5

    first = pd.Timestamp(year=year, month=month, day=1)
    days = pd.date_range(first, first + pd.offsets.MonthEnd(0), freq="D")
    times = pd.DatetimeIndex(sorted({t for d in days for t in dd.required_times(d, "minmax1h")}))
    got_times, t2m = era5.fetch_t2m(times)
    daily = dd.daily_temperature(got_times, t2m, "minmax1h")
    era = pd.DataFrame(index=daily.days)
    rows = []
    for station, network, lat, lon, division in STATIONS:
        r, c, _ = grid.nearest_index(np.array([lat]), np.array([lon]))
        era[station] = daily.t_f[:, r[0], c[0]]
        resp = requests.get(IEM_URL.format(station=station, network=network, year=year, month=month), timeout=120)
        resp.raise_for_status()
        obs = pd.DataFrame(resp.json()["data"])
        if obs.empty:
            continue
        obs["date"] = pd.to_datetime(obs["date"])
        obs["t_f"] = (pd.to_numeric(obs["max_tmpf"], errors="coerce") + pd.to_numeric(obs["min_tmpf"], errors="coerce")) / 2
        joined = obs.set_index("date")[["t_f"]].join(era[[station]], how="inner").dropna()
        if len(joined) < 20:
            continue
        diff = joined[station] - joined["t_f"]
        rows.append({
            "station": station, "division": division, "days": len(joined),
            "station_f": joined["t_f"].mean(), "era5_f": joined[station].mean(),
            "era5_minus_station": diff.mean(), "mae": diff.abs().mean(),
            "corr": np.corrcoef(joined[station], joined["t_f"])[0, 1],
        })
    return pd.DataFrame(rows)
