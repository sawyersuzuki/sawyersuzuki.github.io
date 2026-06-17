#!/usr/bin/env python3
"""
Fetch global 2m-temperature data from Open-Meteo (free, no API key) and
write data/weather.json for the globe visualisation.

Uses a 10°×10° global grid (~595 points) and concurrent requests so the
whole fetch completes in ~20–30 seconds. Intended to be run daily via the
GitHub Action in .github/workflows/update-weather.yml.

Usage:
    python scripts/fetch_weather.py

Dependencies: none beyond the Python standard library.
"""

import json
import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.request import urlopen
from urllib.parse import urlencode
from pathlib import Path

# ── Config ─────────────────────────────────────────────────────────────────
GRID_STEP   = 10    # degrees; 10 → ~595 pts, 5 → ~2520 pts (slower)
MAX_WORKERS = 12    # concurrent HTTP connections
OUT_FILE    = Path(__file__).parent.parent / "data" / "weather.json"
# ───────────────────────────────────────────────────────────────────────────

LATS = list(range(-80, 81, GRID_STEP))
LONS = list(range(-170, 171, GRID_STEP))
BASE = "https://api.open-meteo.com/v1/forecast"


def fetch_point(lat, lon):
    """Return a dict with temperature (°C) and wind u/v (m/s), or None on failure."""
    params = urlencode({
        "latitude": lat, "longitude": lon,
        "current_weather": "true",
        "hourly": "temperature_2m",
        "forecast_days": 1,
        "timezone": "UTC",
    })
    with urlopen(f"{BASE}?{params}", timeout=15) as r:
        d = json.loads(r.read())

    cw = d.get("current_weather", {})
    t  = d.get("hourly", {}).get("temperature_2m", [None])[0]
    if t is None:
        t = cw.get("temperature")
    if t is None:
        return None

    ws   = float(cw.get("windspeed", 0))
    wd_r = math.radians(float(cw.get("winddirection", 0)))
    return {
        "lat": lat, "lon": lon,
        "t":   round(float(t), 1),
        "u":   round(-ws * math.sin(wd_r), 2),   # eastward component
        "v":   round(-ws * math.cos(wd_r), 2),   # northward component
        "spd": round(ws, 1),
    }


def main():
    tasks = [(lat, lon) for lat in LATS for lon in LONS]
    print(f"Fetching {len(tasks)} grid points at {GRID_STEP}° resolution "
          f"({MAX_WORKERS} concurrent workers)…")
    t0 = time.time()

    results, errors = [], 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(fetch_point, lat, lon): (lat, lon)
                   for lat, lon in tasks}
        for i, f in enumerate(as_completed(futures), 1):
            try:
                pt = f.result()
                if pt:
                    results.append(pt)
            except Exception as e:
                errors += 1
            if i % 100 == 0 or i == len(tasks):
                print(f"  {i}/{len(tasks)}  ({errors} errors)")

    OUT_FILE.parent.mkdir(exist_ok=True)
    OUT_FILE.write_text(json.dumps(results, separators=(',', ':')))

    temps = [p["t"] for p in results]
    print(f"\n✓ {len(results)} points written to {OUT_FILE} in {time.time()-t0:.0f}s"
          f"  ({errors} errors)")
    print(f"  Temp range: {min(temps):.1f}°C to {max(temps):.1f}°C, "
          f"mean {sum(temps)/len(temps):.1f}°C")


if __name__ == "__main__":
    main()
