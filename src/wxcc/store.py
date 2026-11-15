"""The regional degree-day store: small Parquet files committed to the repo.

Layout (one schema for every model, analysis or forecast):

    data/regional/analysis/<model>/<YYYY-MM>.parquet    truth, by valid month
    data/regional/forecast/<YYYY>/<YYYYMMDD>.parquet    every model's runs started that day
    data/regional/lab/<model>/<YYYYMMDDHH>.parquet      runs made in the Colab lab

One file per init day keeps the repo small (a file per run is mostly Parquet
overhead) while only the last few days' files ever change, so git history
grows roughly with the data. All writes are upserts by key, so re-running any
job is safe.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from . import __version__
from .regions import REGIONS

ROOT = Path("data/regional")
KEY = ["model", "init_time", "valid_date", "region", "method"]
COLUMNS = [
    "model",  # e.g. era5, gfs, ifs, aifs
    "kind",  # analysis | forecast
    "init_time",  # UTC run time; null for analysis
    "valid_date",  # day label: covers 06Z that day to 06Z the next
    "lead_days",  # valid_date - init date; null for analysis
    "region",  # census division code or CONUS
    "method",  # see degree_days.METHODS
    "hdd",
    "cdd",
    "tmean_f",  # population-weighted daily temperature
    "quality",  # final | prelim (ERA5T) | provisional (GFS analysis) | forecast
    "source",
    "pipeline_version",
]


def make_rows(
    *,
    model: str,
    days: pd.DatetimeIndex,
    regional: dict[str, np.ndarray],
    method: str,
    quality: str | list[str],
    source: str,
    init_time: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Long-format rows from regional arrays shaped (n_days, n_regions)."""
    n_days, n_regions = len(days), len(REGIONS)
    df = pd.DataFrame(
        {
            "valid_date": np.repeat(days.to_numpy(), n_regions),
            "region": np.tile(np.array(REGIONS), n_days),
            "hdd": np.round(regional["hdd"].reshape(-1), 2).astype(np.float32),
            "cdd": np.round(regional["cdd"].reshape(-1), 2).astype(np.float32),
            "tmean_f": np.round(regional["tmean_f"].reshape(-1), 2).astype(np.float32),
        }
    )
    df["model"] = model
    df["kind"] = "analysis" if init_time is None else "forecast"
    df["init_time"] = pd.Timestamp(init_time) if init_time is not None else pd.NaT
    df["init_time"] = df["init_time"].astype("datetime64[ms]")
    df["valid_date"] = df["valid_date"].astype("datetime64[ms]")
    if init_time is None:
        df["lead_days"] = pd.array([pd.NA] * len(df), dtype="Int16")
    else:
        lead = (df["valid_date"] - pd.Timestamp(init_time).normalize()).dt.days
        df["lead_days"] = lead.astype("Int16")
    df["method"] = method
    df["quality"] = np.repeat(np.array(quality), n_regions) if not isinstance(quality, str) else quality
    df["source"] = source
    df["pipeline_version"] = __version__
    return df[COLUMNS]


def _upsert(path: Path, new: pd.DataFrame) -> int:
    """Merge rows into a Parquet file by key; later rows win. Returns rows added or changed."""
    if path.exists():
        old = pd.read_parquet(path)
        merged = pd.concat([old, new], ignore_index=True)
    else:
        old, merged = None, new
    merged = merged.drop_duplicates(KEY, keep="last").sort_values(KEY).reset_index(drop=True)
    if old is not None and len(old) == len(merged) and old[COLUMNS].equals(merged[COLUMNS]):
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    merged[COLUMNS].to_parquet(tmp, index=False, compression="zstd")
    os.replace(tmp, path)  # atomic: a reader never sees a half-written file
    return len(merged) - (0 if old is None else len(old))


def write_analysis(df: pd.DataFrame, root: Path = ROOT) -> list[Path]:
    paths = []
    for (model, month), part in df.groupby(["model", df["valid_date"].dt.strftime("%Y-%m")]):
        path = root / "analysis" / model / f"{month}.parquet"
        _upsert(path, part)
        paths.append(path)
    return paths


def forecast_path(init_time: pd.Timestamp, root: Path = ROOT) -> Path:
    t = pd.Timestamp(init_time)
    return root / "forecast" / f"{t:%Y}" / f"{t:%Y%m%d}.parquet"


def lab_path(model: str, init_time: pd.Timestamp, root: Path = ROOT) -> Path:
    return root / "lab" / model / f"{pd.Timestamp(init_time):%Y%m%d%H}.parquet"


def write_forecast(df: pd.DataFrame, root: Path = ROOT, lab: bool = False) -> Path:
    model, init = df["model"].iloc[0], df["init_time"].iloc[0]
    path = lab_path(model, init, root) if lab else forecast_path(init, root)
    with _write_lock:
        _upsert(path, df)
    return path


def stored_runs(model: str, start: pd.Timestamp, end: pd.Timestamp, root: Path = ROOT) -> set[pd.Timestamp]:
    """Init times already stored for a model between two dates (inclusive)."""
    out: set[pd.Timestamp] = set()
    for day in pd.date_range(pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize(), freq="D"):
        path = forecast_path(day, root)
        if path.exists():
            df = pd.read_parquet(path, columns=["model", "init_time"])
            out.update(pd.DatetimeIndex(df.loc[df["model"] == model, "init_time"].unique()))
    return out


MANIFESTS = Path("data/manifests")
_pending_manifests: list[dict] = []
_manifest_lock = threading.Lock()
_write_lock = threading.Lock()


def write_manifest(*, model: str, init_time: pd.Timestamp, source: str, method: str, n_steps: int,
                   missing_steps: list[int], first_valid: pd.Timestamp, last_valid: pd.Timestamp,
                   detail: dict | None = None, extra: dict | None = None) -> dict:
    """Queue a run manifest: what was fetched, from where, with which settings."""
    record = {
        "model": model,
        "init_time": f"{pd.Timestamp(init_time):%Y-%m-%dT%H:%M}Z",
        "variables": ["t2m"],
        "method": method,
        "source": source,
        "n_steps": int(n_steps),
        "missing_steps": [int(s) for s in missing_steps],
        "first_valid": f"{pd.Timestamp(first_valid):%Y-%m-%d}",
        "last_valid": f"{pd.Timestamp(last_valid):%Y-%m-%d}",
        "pipeline_version": __version__,
        "written_at": f"{pd.Timestamp.now(tz='UTC'):%Y-%m-%dT%H:%M}Z",
        "detail": detail or {},
    }
    record.update(extra or {})
    with _manifest_lock:
        _pending_manifests.append(record)
    return record


def flush_manifests(root: Path | None = None) -> int:
    """Append queued manifests to data/manifests/<model>/<year>.jsonl (one line per run)."""
    root = root or MANIFESTS
    with _manifest_lock:
        pending, _pending_manifests[:] = list(_pending_manifests), []
    by_file: dict[Path, list[dict]] = {}
    for rec in pending:
        by_file.setdefault(root / rec["model"] / f"{rec['init_time'][:4]}.jsonl", []).append(rec)
    for path, records in by_file.items():
        existing = {}
        if path.exists():
            for line in path.read_text().splitlines():
                if line.strip():
                    rec = json.loads(line)
                    existing[rec["init_time"]] = rec
        existing.update({r["init_time"]: r for r in records})
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text("".join(json.dumps(existing[k], sort_keys=True) + "\n" for k in sorted(existing)))
        os.replace(tmp, path)
    return len(pending)


def read_manifests(model: str | None = None, root: Path | None = None) -> pd.DataFrame:
    root = root or MANIFESTS
    files = sorted(root.glob(f"{model or '*'}/*.jsonl"))
    records = [json.loads(line) for f in files for line in f.read_text().splitlines() if line.strip()]
    return pd.DataFrame(records)


def stored_analysis_days(model: str, method: str, root: Path = ROOT) -> dict[pd.Timestamp, str]:
    """Days already stored for an analysis model -> their quality flag."""
    files = sorted((root / "analysis" / model).glob("*.parquet"))
    if not files:
        return {}
    df = pd.concat(pd.read_parquet(f, columns=["valid_date", "method", "quality"]) for f in files)
    df = df[df["method"] == method].drop_duplicates("valid_date")
    return dict(zip(pd.DatetimeIndex(df["valid_date"]), df["quality"]))


def query(
    model: str | None = None,
    region: str | None = None,
    start: str | None = None,
    end: str | None = None,
    init: str | None = None,
    method: str | None = None,
    root: Path = ROOT,
) -> pd.DataFrame:
    """Filter the store. All arguments are optional; dates are inclusive."""
    files = [str(p) for p in root.rglob("*.parquet")]
    if not files:
        return pd.DataFrame(columns=COLUMNS)
    where, params = [], []
    for column, value in (("model", model), ("region", region), ("method", method)):
        if value is not None:
            where.append(f"{column} = ?")
            params.append(value)
    if start is not None:
        where.append("valid_date >= ?")
        params.append(pd.Timestamp(start))
    if end is not None:
        where.append("valid_date <= ?")
        params.append(pd.Timestamp(end))
    if init is not None:
        where.append("init_time = ?")
        params.append(pd.Timestamp(init))
    sql = "SELECT * FROM read_parquet(?, union_by_name=true)"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY model, init_time, valid_date, region, method"
    return duckdb.execute(sql, [files, *params]).df()


def inventory(root: Path = ROOT) -> pd.DataFrame:
    """What is stored: one row per model/kind/method with date range and counts."""
    files = [str(p) for p in root.rglob("*.parquet")]
    if not files:
        return pd.DataFrame()
    sql = """
        SELECT model, kind, method,
               min(valid_date)::DATE AS first_valid, max(valid_date)::DATE AS last_valid,
               count(DISTINCT valid_date) AS valid_days,
               count(DISTINCT init_time) AS runs,
               count(*) AS rows
        FROM read_parquet(?, union_by_name=true)
        GROUP BY ALL ORDER BY ALL
    """
    return duckdb.execute(sql, [files]).df()
