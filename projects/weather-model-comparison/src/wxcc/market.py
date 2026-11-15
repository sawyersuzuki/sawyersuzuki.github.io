"""Market link: Henry Hub, EIA storage and day-ahead power prices.

Everything here is free, needs no API key, and is stored as small CSV files
under data/market/. Sources and their limits:

- Henry Hub daily spot: EIA series, downloaded from FRED (DHHNGSP). About a week behind.
- Lower 48 working gas in storage: EIA weekly history spreadsheet. Weekly, Thursdays.
- Day-ahead power prices, daily averages:
    NYISO Zone J (New York City)   NYISO public CSV archive
    MISO Indiana and Minnesota hubs MISO market reports
    CAISO SP15                      CAISO OASIS
  ERCOT and PJM publish the same data only behind free API keys, so they are
  not fetched here (see DECISIONS.md).
"""

from __future__ import annotations

import csv
import io
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

from .sources.http import NotAvailable, get

ROOT = Path("data/market")
POWER_START = "2025-11-01"
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DHHNGSP&cosd=2016-01-01"
STORAGE_URL = "https://www.eia.gov/dnav/ng/hist_xls/NW2_EPG0_SWO_R48_BCFw.xls"
NYISO_URL = "https://mis.nyiso.com/public/csv/damlbmp/{month:%Y%m}01damlbmp_zone_csv.zip"
MISO_URL = "https://docs.misoenergy.org/marketreports/{day:%Y%m%d}_da_expost_lmp.csv"
CAISO_URL = ("https://oasis.caiso.com/oasisapi/SingleZip?resultformat=6&queryname=PRC_LMP&version=12"
             "&startdatetime={start:%Y%m%d}T08:00-0000&enddatetime={end:%Y%m%d}T08:00-0000"
             "&market_run_id=DAM&node=TH_SP15_GEN-APND")

ZONES = [
    {"id": "nyiso_nyc", "label": "NYISO Zone J (New York City)", "region": "NY", "source": "NYISO public market data"},
    {"id": "miso_indiana", "label": "MISO Indiana Hub", "region": "ENC", "source": "MISO market reports"},
    {"id": "miso_minn", "label": "MISO Minnesota Hub", "region": "WNC", "source": "MISO market reports"},
    {"id": "caiso_sp15", "label": "CAISO SP15", "region": "CA", "source": "CAISO OASIS"},
]
MISO_NODES = {"INDIANA.HUB": "miso_indiana", "MINN.HUB": "miso_minn"}
NOTES = [
    "Henry Hub: EIA daily spot price via FRED series DHHNGSP; typically published with a lag of about a week.",
    "Storage: EIA Weekly Natural Gas Storage Report, Lower 48 working gas; weeks end on Friday and are matched to Saturday-to-Friday degree days.",
    "Power: daily averages of hourly day-ahead prices. NYISO Zone J, MISO Indiana and Minnesota hubs, CAISO SP15.",
    "Not included: ERCOT and PJM prices. Both are free but need a registered API key; add them once you have keys.",
    "Henry Hub futures are not free in real time; EIA's delayed front-month series could be added the same way as the spot price.",
]


def _read(name: str) -> pd.DataFrame:
    path = ROOT / name
    return pd.read_csv(path) if path.exists() else pd.DataFrame()


def _write(name: str, df: pd.DataFrame) -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    df.to_csv(ROOT / name, index=False, lineterminator="\n")


def update_henry_hub() -> int:
    df = pd.read_csv(io.BytesIO(get(FRED_URL)))
    df.columns = ["date", "price"]
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df = df.dropna()
    _write("henry_hub.csv", df)
    return len(df)


def update_storage() -> int:
    import xlrd

    book = xlrd.open_workbook(file_contents=get(STORAGE_URL))
    sheet = book.sheet_by_name("Data 1")
    rows = []
    for i in range(3, sheet.nrows):
        date, stocks = sheet.cell_value(i, 0), sheet.cell_value(i, 1)
        if date and stocks != "":
            rows.append((xlrd.xldate_as_datetime(date, book.datemode).strftime("%Y-%m-%d"), float(stocks)))
    df = pd.DataFrame(rows, columns=["week_ending", "stocks_bcf"])
    df["change_bcf"] = df["stocks_bcf"].diff()
    df = df[df["week_ending"] >= "2016-01-01"].dropna()
    _write("storage.csv", df)
    return len(df)


def _nyiso_month(month: pd.Timestamp) -> list[tuple[str, str, float]]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(get(NYISO_URL.format(month=month))))
    except NotAvailable:
        return []
    out = []
    for name in archive.namelist():
        df = pd.read_csv(io.BytesIO(archive.read(name)))
        nyc = df[df["Name"] == "N.Y.C."]
        if len(nyc):
            day = pd.to_datetime(nyc["Time Stamp"].iloc[0]).strftime("%Y-%m-%d")
            out.append((day, "nyiso_nyc", round(float(nyc["LBMP ($/MWHr)"].mean()), 2)))
    return out


def _miso_day(day: pd.Timestamp) -> list[tuple[str, str, float]]:
    try:
        text = get(MISO_URL.format(day=day)).decode("utf-8", "replace")
    except NotAvailable:
        return []
    out = []
    for row in csv.reader(io.StringIO(text)):
        if len(row) > 10 and row[0] in MISO_NODES and row[2] == "LMP":
            hours = [float(x) for x in row[3:27] if x not in ("", None)]
            if hours:
                out.append((day.strftime("%Y-%m-%d"), MISO_NODES[row[0]], round(sum(hours) / len(hours), 2)))
    return out


def _caiso_window(start: pd.Timestamp, end: pd.Timestamp) -> list[tuple[str, str, float]]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(get(CAISO_URL.format(start=start, end=end))))
    except (NotAvailable, zipfile.BadZipFile):
        return []
    name = archive.namelist()[0]
    if not name.endswith(".csv"):
        return []  # OASIS returns an XML error document inside the zip when a query is refused
    df = pd.read_csv(io.BytesIO(archive.read(name)))
    df = df[df["LMP_TYPE"] == "LMP"]
    daily = df.groupby("OPR_DT")["MW"].mean()
    return [(str(day), "caiso_sp15", round(float(price), 2)) for day, price in daily.items()]


def update_power(start: str = POWER_START, progress=print) -> int:
    """Fetch day-ahead prices not yet stored, from ``start`` to yesterday."""
    old = _read("power.csv")
    have = set(zip(old["date"], old["zone"])) if not old.empty else set()
    days = pd.date_range(start, pd.Timestamp.now(tz="UTC").tz_localize(None).normalize() - pd.Timedelta(days=1), freq="D")
    rows: list[tuple[str, str, float]] = []

    def missing(zone: str) -> list[pd.Timestamp]:
        return [d for d in days if (d.strftime("%Y-%m-%d"), zone) not in have]

    months = sorted({d.to_period("M").to_timestamp() for d in missing("nyiso_nyc")})
    for month in months:
        rows += _nyiso_month(month)
    progress(f"  NYISO: {len(months)} monthly files")

    miso_days = sorted(set(missing("miso_indiana")) | set(missing("miso_minn")))
    with ThreadPoolExecutor(max_workers=6) as pool:
        for got in pool.map(_miso_day, miso_days):
            rows += got
    progress(f"  MISO: {len(miso_days)} daily files")

    caiso_days = missing("caiso_sp15")
    windows = 0
    if caiso_days:
        d = caiso_days[0]
        while d <= caiso_days[-1]:
            end = min(d + pd.Timedelta(days=30), days[-1] + pd.Timedelta(days=1))
            rows += _caiso_window(d, end)
            windows += 1
            d = end
            time.sleep(5.5)  # OASIS allows roughly one request every five seconds
    progress(f"  CAISO: {windows} requests")

    new = pd.DataFrame(rows, columns=["date", "zone", "price"])
    df = pd.concat([old, new], ignore_index=True) if not old.empty else new
    df = df[df["date"] >= start].drop_duplicates(["date", "zone"], keep="last").sort_values(["zone", "date"])
    _write("power.csv", df)
    return len(new)


def update(progress=print) -> None:
    progress("Market:")
    for name, fn in (("Henry Hub", update_henry_hub), ("storage", update_storage)):
        try:
            progress(f"  {name}: {fn()} rows")
        except Exception as e:  # one source being down must not stop the others
            progress(f"  {name}: FAILED ({type(e).__name__}: {str(e)[:120]})")
    try:
        progress(f"  power: {update_power(progress=progress)} new daily prices")
    except Exception as e:
        progress(f"  power: FAILED ({type(e).__name__}: {str(e)[:120]})")


def dashboard_block() -> dict | None:
    hh, storage, power = _read("henry_hub.csv"), _read("storage.csv"), _read("power.csv")
    if hh.empty and storage.empty and power.empty:
        return None
    zones = []
    for z in ZONES:
        part = power[power["zone"] == z["id"]] if not power.empty else power
        if len(part):
            zones.append({**z, "series": [{"date": d, "price": p} for d, p in zip(part["date"], part["price"])]})
    return {
        "henry_hub": [{"date": d, "price": p} for d, p in zip(hh["date"], hh["price"])] if not hh.empty else [],
        "storage": [{"week_ending": w, "change": c} for w, c in zip(storage["week_ending"], storage["change_bcf"])]
        if not storage.empty else [],
        "power": zones,
        "notes": NOTES,
    }
