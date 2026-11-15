"""Shared shape of a forecast adapter.

Every adapter answers one question: for a run started at ``init``, what is the
2 m temperature over CONUS at each 6-hourly step? Everything downstream (degree
days, weighting, storage) is model-agnostic.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .http import NotAvailable

STEP_H = 6


@dataclass
class RunData:
    init: pd.Timestamp
    times: pd.DatetimeIndex  # valid times actually retrieved
    t2m_k: np.ndarray  # (len(times), NLAT, NLON)
    source: str  # where it came from, for the manifest
    missing_steps: list[int] = field(default_factory=list)
    detail: dict = field(default_factory=dict)


class Adapter:
    max_step_h: int = 240
    mb_per_step: float = 0.6  # typical download per 6-hourly field

    def steps(self, init: pd.Timestamp) -> list[int]:
        return list(range(0, self.max_step_h + 1, STEP_H))

    def est_mb(self, init: pd.Timestamp) -> float:
        return len(self.steps(init)) * self.mb_per_step

    def fetch(self, init: pd.Timestamp) -> RunData:  # pragma: no cover - interface
        raise NotImplementedError


def gather_steps(init: pd.Timestamp, steps: list[int], fetch_step, source: str, workers: int = 12,
                 min_fraction: float = 0.9, detail: dict | None = None) -> RunData:
    """Fetch steps in parallel. Individual gaps are tolerated; a mostly-missing run is not."""

    def one(step: int):
        try:
            return step, fetch_step(step)
        except NotAvailable:
            return step, None

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(one, steps))
    got = [(s, f) for s, f in results if f is not None]
    missing = [s for s, f in results if f is None]
    if len(got) < min_fraction * len(steps) or steps[-1] in missing:
        raise NotAvailable(f"{source} {init:%Y-%m-%d %HZ}: {len(missing)}/{len(steps)} steps missing")
    times = pd.DatetimeIndex([init + pd.Timedelta(hours=s) for s, _ in got])
    return RunData(init, times, np.stack([f for _, f in got]), source, missing, detail or {})
