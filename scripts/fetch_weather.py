#!/usr/bin/env python3
"""
Fetch global weather data from Open-Meteo (free, no API key required)
and write data/weather.json for the globe visualization.

Queries a 5°x5° global grid (~2520 points) using the Open-Meteo
forecast API for current conditions updated hourly.

Usage:
    pip install requests
    python scripts/fetch_weather.py

For near-real-time wind & temperature:
    The default mode fetches the latest hour's data.

For ERA5 historical reanalysis (higher accuracy, 5-day lag):
    Set USE_ERA5 = True below (requires the same free Open-Meteo API
    but hits their historical endpoint instead).

For very high resolution (1° grid, ~65000 pts):
    Consider the CDS (Copernicus Climate Data Store) API with cdsapi:
    https://cds.climate.copernicus.eu/
"""

import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import requests
except ImportError:
    raise SystemExit("Run: pip install requests")

# ── Config ────────────────────────────────────────────────────────────────────
GRID_STEP = 5          # degrees; 5 → ~2520 pts, 10 → ~612 pts (faster)
USE_ERA5  = False      # True: ERA5 reanalysis (5-day lag); False: live forecast
DELAY     = 0.06       # seconds between requests (free tier: no hard limit)
OUT_FILE  = Path(__file__).parent.parent / "data" / "weather.json"
# ─────────────────────────────────────────────────────────────────────────────

LATS = list(range(-85, 90, GRID_STEP))
LONS = list(range(-180, 180, GRID_STEP))

FORECAST_URL  = "https://api.open-meteo.com/v1/forecast"
ERA5_URL      = "https://archive-api.open-meteo.com/v1/era5"


def dir_to_uv(speed, direction_deg):
    """Meteorological wind direction → u/v components (m/s)."""
    d = math.radians(direction_deg)
    return -speed * math.sin(d), -speed * math.cos(d)


def fetch_forecast(lat, lon):
    r = requests.get(FORECAST_URL, params={
        "latitude": lat, "longitude": lon,
        "current_weather": True,
        "hourly": "temperature_2m",
        "forecast_days": 1,
        "timezone": "UTC",
    }, timeout=12)
    r.raise_for_status()
    d = r.json()
    cw = d.get("current_weather", {})
    ws = cw.get("windspeed")
    wd = cw.get("winddirection")
    # Temperature from first hourly value (current hour)
    t = d.get("hourly", {}).get("temperature_2m", [None])[cw.get("weathercode", 0)]
    # Fallback: use current_weather temperature if hourly lookup fails
    t = d["hourly"]["temperature_2m"][0] if t is None else t
    if ws is None or wd is None or t is None:
        return None
    u, v = dir_to_uv(ws, wd)
    return {"lat": lat, "lon": lon, "t": round(t, 1),
            "u": round(u, 2), "v": round(v, 2), "spd": round(ws, 1)}


def fetch_era5(lat, lon):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    r = requests.get(ERA5_URL, params={
        "latitude": lat, "longitude": lon,
        "hourly": "temperature_2m,windspeed_10m,winddirection_10m",
        "start_date": today, "end_date": today,
        "timezone": "UTC",
    }, timeout=15)
    r.raise_for_status()
    d = r.json()["hourly"]
    temps = [x for x in d.get("temperature_2m", []) if x is not None]
    wsps  = [x for x in d.get("windspeed_10m", []) if x is not None]
    wdirs = [x for x in d.get("winddirection_10m", []) if x is not None]
    if not temps or not wsps or not wdirs:
        return None
    t  = sum(temps) / len(temps)
    ws = sum(wsps) / len(wsps)
    wd = sum(wdirs) / len(wdirs)
    u, v = dir_to_uv(ws, wd)
    return {"lat": lat, "lon": lon, "t": round(t, 1),
            "u": round(u, 2), "v": round(v, 2), "spd": round(ws, 1)}


def main():
    fetch_fn = fetch_era5 if USE_ERA5 else fetch_forecast
    mode = "ERA5 reanalysis" if USE_ERA5 else "live forecast"
    total = len(LATS) * len(LONS)
    print(f"Fetching {total} grid points ({GRID_STEP}° resolution, {mode})…")

    points = []
    errors = 0
    for lat in LATS:
        for lon in LONS:
            try:
                pt = fetch_fn(lat, lon)
                if pt:
                    points.append(pt)
            except Exception as e:
                errors += 1
                if errors <= 5:
                    print(f"  ✗ ({lat},{lon}): {e}")
            time.sleep(DELAY)

    OUT_FILE.parent.mkdir(exist_ok=True)
    OUT_FILE.write_text(json.dumps(points, separators=(',', ':')))
    print(f"\n✓ Wrote {len(points)} points to {OUT_FILE}  ({errors} errors)")


if __name__ == "__main__":
    main()
