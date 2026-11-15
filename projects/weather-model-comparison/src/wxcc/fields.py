"""Tier 2: daily-mean temperature maps, kept out of git.

One small compressed file per run (forecasts) or per day (analysis) in a local
cache, bundled per model and month into GitHub Release assets for long-term
storage. Values are tenths of a degree Fahrenheit as int16.

    .cache/fields/<model>/<YYYYMMDDHH>.npz    forecast: array (n_days, NLAT, NLON) + days
    .cache/fields/<model>/<YYYYMMDD>.npz      analysis: array (NLAT, NLON)
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd

CACHE = Path(os.environ.get("WXCC_CACHE", ".cache"))
ROOT = CACHE / "fields"
CACHE_CAP_GB = 3.0
SCALE = 10.0


def _encode(t_f: np.ndarray) -> np.ndarray:
    return np.rint(np.asarray(t_f) * SCALE).astype(np.int16)


def forecast_path(model: str, init: pd.Timestamp, root: Path | None = None) -> Path:
    return (root or ROOT) / model / f"{pd.Timestamp(init):%Y%m%d%H}.npz"


def analysis_path(model: str, day: pd.Timestamp, root: Path | None = None) -> Path:
    return (root or ROOT) / model / f"{pd.Timestamp(day):%Y%m%d}.npz"


def save_forecast(model: str, init: pd.Timestamp, days: pd.DatetimeIndex, t_f: np.ndarray,
                  root: Path | None = None) -> Path:
    path = forecast_path(model, init, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, t=_encode(t_f), days=days.strftime("%Y-%m-%d").to_numpy().astype("U10"))
    return path


def save_analysis(model: str, days: pd.DatetimeIndex, t_f: np.ndarray, root: Path | None = None) -> None:
    for day, field in zip(days, t_f):
        path = analysis_path(model, day, root)
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(path, t=_encode(field))


def load_forecast(model: str, init: pd.Timestamp, root: Path | None = None) -> tuple[pd.DatetimeIndex, np.ndarray] | None:
    path = forecast_path(model, init, root)
    if not path.exists():
        return None
    with np.load(path) as z:
        return pd.DatetimeIndex(z["days"]), z["t"].astype(np.float32) / SCALE


def load_analysis(model: str, day: pd.Timestamp, root: Path | None = None) -> np.ndarray | None:
    path = analysis_path(model, day, root)
    if not path.exists():
        return None
    with np.load(path) as z:
        return z["t"].astype(np.float32) / SCALE


def cache_size_gb(cache: Path | None = None) -> float:
    cache = cache or CACHE
    return sum(p.stat().st_size for p in cache.rglob("*") if p.is_file()) / 1e9 if cache.exists() else 0.0


def prune(cap_gb: float = CACHE_CAP_GB, cache: Path | None = None) -> int:
    """Delete least-recently-used cache files until the cache is under the cap."""
    cache = cache or CACHE
    if not cache.exists():
        return 0
    files = sorted((p for p in cache.rglob("*") if p.is_file()), key=lambda p: p.stat().st_atime)
    total = sum(p.stat().st_size for p in files)
    removed = 0
    for p in files:
        if total <= cap_gb * 1e9:
            break
        total -= p.stat().st_size
        p.unlink()
        removed += 1
    return removed


# ----------------------------------------------------------------------------- long-term storage
# Bundles live as assets on GitHub Releases of this repository (tag "fields-<year>"):
# free, private while the repo is private, and no extra account or secret. Each asset
# is a zip of one model's files for one month, replaced when that month gains runs.


def _month_files(model: str, month: str, root: Path | None = None) -> list[Path]:
    return sorted(((root or ROOT) / model).glob(f"{month.replace('-', '')}*.npz"))


def months_present(root: Path | None = None) -> dict[str, list[str]]:
    """model -> months (YYYY-MM) that have files in the local cache."""
    out: dict[str, list[str]] = {}
    base = root or ROOT
    for d in sorted(p for p in base.glob("*") if p.is_dir()):
        months = sorted({f"{p.name[:4]}-{p.name[4:6]}" for p in d.glob("*.npz")})
        if months:
            out[d.name] = months
    return out


def _gh(*args: str) -> tuple[int, str]:
    import subprocess

    try:
        proc = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=1800)
    except FileNotFoundError:
        return 127, "the GitHub CLI (gh) is not installed"
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def publish(months: list[str], models: list[str] | None = None, progress=print) -> int:
    """Upload bundles for the given months. Returns the number of assets uploaded."""
    import tempfile
    import zipfile

    present = months_present()
    uploaded = 0
    with tempfile.TemporaryDirectory() as tmp:
        for model, have in present.items():
            if models and model not in models:
                continue
            for month in months:
                files = _month_files(model, month)
                if month not in have or not files:
                    continue
                tag = f"fields-{month[:4]}"
                bundle = Path(tmp) / f"fields-{model}-{month}.zip"
                with zipfile.ZipFile(bundle, "w", zipfile.ZIP_STORED) as z:  # .npz is already compressed
                    for f in files:
                        z.write(f, arcname=f"{model}/{f.name}")
                code, _ = _gh("release", "view", tag)
                if code != 0:
                    code, msg = _gh("release", "create", tag, "--title", f"Map fields {month[:4]}", "--notes",
                                    "Daily-mean 2 m temperature maps (tier 2 data). Managed by `wxcc fields`.")
                    if code != 0:
                        progress(f"  could not create release {tag}: {msg[:200]}")
                        return uploaded
                code, msg = _gh("release", "upload", tag, str(bundle), "--clobber")
                if code != 0:
                    progress(f"  upload failed for {bundle.name}: {msg[:200]}")
                    continue
                uploaded += 1
                progress(f"  {bundle.name}: {len(files)} files, {bundle.stat().st_size / 1e6:.1f} MB")
    return uploaded


def pull(months: list[str], models: list[str] | None = None, progress=print) -> int:
    """Download and unpack bundles for the given months into the local cache."""
    import tempfile
    import zipfile

    got = 0
    with tempfile.TemporaryDirectory() as tmp:
        for month in months:
            pattern = f"fields-*-{month}.zip" if not models else None
            patterns = [pattern] if pattern else [f"fields-{m}-{month}.zip" for m in models]
            for pat in patterns:
                code, msg = _gh("release", "download", f"fields-{month[:4]}", "--pattern", pat, "--dir", tmp, "--clobber")
                if code != 0 and "no assets" not in msg and "not found" not in msg.lower():
                    progress(f"  {pat}: {msg[:160]}")
        for bundle in sorted(Path(tmp).glob("*.zip")):
            with zipfile.ZipFile(bundle) as z:
                names = [n for n in z.namelist() if n.endswith(".npz") and ".." not in n and not n.startswith("/")]
                z.extractall(ROOT, members=names)
            got += 1
            progress(f"  {bundle.name}: unpacked {len(names)} files")
    prune()
    return got
