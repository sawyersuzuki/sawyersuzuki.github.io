"""Build the static dashboard: one self-contained HTML file with the data inside.

`wxcc build` reads the store, packs the series into compact arrays, and writes

    site/index.html      open in a browser (or `wxcc serve`)
    site/fragment.html   the same page without the outer <html> wrapper

The page needs no server and no Colab; charts are drawn by Plotly from a CDN.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from . import __version__, events, fields, grid, store
from .models import ANALYSIS_MODELS, FORECAST_MODELS
from .regions import REGION_NAMES, REGIONS

SITE = Path("site")
TEMPLATE = Path(__file__).parent / "dashboard" / "template.html"
STATIC = Path("data/static")
TRUTH_START = pd.Timestamp("2016-01-01")
NORMAL_YEARS = (2016, 2025)
MISSING = -32768
SCALE = 10
NLEAD = 17  # lead days 0..16
MAP_STRIDE = 2
MAP_DAYS = 16


def b64_i16(a: np.ndarray) -> str:
    a = np.where(np.isfinite(a), np.rint(np.asarray(a, dtype=np.float64) * SCALE), MISSING)
    return base64.b64encode(np.clip(a, -32768, 32767).astype("<i2").tobytes()).decode()


def _read(kind_dir: str, root: Path) -> pd.DataFrame:
    files = [str(p) for p in (root / kind_dir).rglob("*.parquet")]
    if not files:
        return pd.DataFrame()
    return duckdb.execute("SELECT * FROM read_parquet(?, union_by_name=true)", [files]).df()


def truth_block(root: Path) -> dict:
    """Daily truth per region: ERA5 where it exists, GFS analysis for the rest."""
    df = _read("analysis", root)
    df = df[df["method"] == "mean6h"] if not df.empty else df
    end = pd.Timestamp.now(tz="UTC").tz_localize(None).normalize()
    days = pd.date_range(TRUTH_START, end, freq="D")
    n, nr = len(days), len(REGIONS)
    out = {v: np.full((n, nr), np.nan) for v in ("hdd", "cdd", "tmean_f")}
    quality = np.array(["-"] * n)
    flag = {"final": "f", "prelim": "p", "provisional": "g"}
    for model in ("gfs_anl", "era5"):  # ERA5 written last, so it wins where both exist
        part = df[df["model"] == model] if not df.empty else df
        if part.empty:
            continue
        di = days.get_indexer(pd.DatetimeIndex(part["valid_date"]).astype("datetime64[ns]"))
        ri = pd.Index(REGIONS).get_indexer(part["region"])
        ok = (di >= 0) & (ri >= 0)
        for v in out:
            out[v][di[ok], ri[ok]] = part[v].to_numpy()[ok]
        quality[di[ok]] = part["quality"].map(flag).to_numpy()[ok]
    era_days = days[np.isin(quality, ["f", "p"])]
    return {
        "start": f"{TRUTH_START:%Y-%m-%d}", "n": n,
        "hdd": b64_i16(out["hdd"]), "cdd": b64_i16(out["cdd"]), "tmean": b64_i16(out["tmean_f"]),
        "quality": "".join(quality),
        "era5_through": f"{era_days.max():%Y-%m-%d}" if len(era_days) else None,
        "_arrays": out, "_days": days, "_quality": quality,
    }


def normals_block(truth: dict) -> dict:
    """Day-of-year normals: mean over NORMAL_YEARS of a centred 15-day window."""
    days = truth["_days"]
    sel = (days.year >= NORMAL_YEARS[0]) & (days.year <= NORMAL_YEARS[1]) & np.isin(truth["_quality"], ["f", "p"])
    doy = np.minimum(days.day_of_year.to_numpy(), 366)
    out = {}
    for v in ("hdd", "cdd"):
        a = truth["_arrays"][v]
        by_doy = np.full((366, a.shape[1]), np.nan)
        for d in range(1, 367):
            window = ((doy - d + 183) % 366 - 183)
            m = sel & (np.abs(window) <= 7)
            if m.any():
                by_doy[d - 1] = np.nanmean(a[m], axis=0)
        out[v] = b64_i16(by_doy)
    years = sorted(set(days[sel].year))
    out["years"] = f"{years[0]}-{years[-1]}" if years else ""
    out["n_years"] = len(years)
    return out


def runs_block(root: Path) -> tuple[dict, list[str]]:
    """Every stored forecast run, packed as [init, lead day, region] arrays per model."""
    df = pd.concat([_read("forecast", root), _read("lab", root)], ignore_index=True)
    if df.empty:
        return {}, []
    df = df[df["method"] == "mean6h"]
    nr = len(REGIONS)
    out, order = {}, []
    known = list(FORECAST_MODELS) + sorted(set(df["model"]) - set(FORECAST_MODELS))
    for model in known:
        part = df[df["model"] == model]
        if part.empty:
            continue
        inits = pd.DatetimeIndex(sorted(part["init_time"].unique()))
        ii = inits.get_indexer(pd.DatetimeIndex(part["init_time"]))
        li = part["lead_days"].to_numpy(dtype=int)
        ri = pd.Index(REGIONS).get_indexer(part["region"])
        ok = (li >= 0) & (li < NLEAD) & (ri >= 0)
        block = {}
        for v in ("hdd", "cdd"):
            a = np.full((len(inits), NLEAD, nr), np.nan)
            a[ii[ok], li[ok], ri[ok]] = part[v].to_numpy()[ok]
            block[v] = b64_i16(a)
        block["inits"] = [f"{t:%Y-%m-%dT%H}" for t in inits]
        out[model] = block
        order.append(model)
    return out, order


def maps_block(models: list[str]) -> dict | None:
    """Daily-mean temperature maps of the latest 00Z run that most models have."""
    counts: dict[str, int] = {}
    for model in models:
        for p in (fields.ROOT / model).glob("*00.npz"):
            counts[p.stem] = counts.get(p.stem, 0) + 1
    if not counts:
        return None
    best = max(counts.values())
    stamp = max(s for s, c in counts.items() if c >= max(2, best - 1))
    init = pd.Timestamp(f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}")
    rows, cols = slice(None, None, MAP_STRIDE), slice(None, None, MAP_STRIDE)
    lats, lons = grid.LATS[rows], grid.LONS[cols]
    out = {"init": f"{init:%Y-%m-%dT%H}", "ny": len(lats), "nx": len(lons),
           "lat0": float(lats[0]), "dlat": float(lats[1] - lats[0]),
           "lon0": float(lons[0]), "dlon": float(lons[1] - lons[0]), "ndays": MAP_DAYS, "models": {}}
    for model in models:
        got = fields.load_forecast(model, init)
        if got is None:
            continue
        days, t_f = got
        a = np.full((MAP_DAYS, len(lats), len(lons)), np.nan)
        lead = (days - init).days.to_numpy()
        ok = (lead >= 0) & (lead < MAP_DAYS)
        a[lead[ok]] = t_f[ok][:, rows, cols]
        out["models"][model] = b64_i16(a)
    states = STATIC / "us_states.json"
    out["states"] = json.loads(states.read_text()) if states.exists() else None
    return out


def inventory_block(root: Path) -> list[dict]:
    inv = store.inventory(root)
    manifests = store.read_manifests()
    rows = []
    for model_id, m in (FORECAST_MODELS | ANALYSIS_MODELS).items():
        part = inv[inv["model"] == model_id] if not inv.empty else inv
        part = part[part["method"] == "mean6h"] if not part.empty else part
        stored_runs = int(part["runs"].sum()) if not part.empty else 0
        first = last = None
        if not manifests.empty and model_id in set(manifests["model"]):
            mm = manifests[manifests["model"] == model_id]["init_time"]
            first, last = mm.min()[:13], mm.max()[:13]
        elif not part.empty:
            first, last = str(part["first_valid"].min()), str(part["last_valid"].max())
        rows.append({
            "id": model_id, "label": m.label, "family": m.family, "provider": m.provider,
            "available_from": m.first_init, "lead_days": m.lead_days, "licence": m.licence, "note": m.note,
            "stored_runs": stored_runs,
            "stored_days": int(part["valid_days"].max()) if not part.empty else 0,
            "stored_first": first, "stored_last": last,
        })
    return rows


def lab_block() -> list[dict]:
    """Runs made in the Colab lab, newest first, with what they cost."""
    manifests = store.read_manifests()
    if manifests.empty:
        return []
    lab = manifests[manifests["model"].str.startswith("lab_")].sort_values("written_at", ascending=False)
    out = []
    for rec in lab.head(50).to_dict("records"):
        detail = rec.get("detail") or {}
        out.append({"model": rec["model"], "init_time": rec["init_time"], "written_at": rec["written_at"],
                    "gpu": detail.get("gpu"), "run_s": detail.get("run_s"), "session_s": detail.get("session_s"),
                    "units": detail.get("est_compute_units"), "source": detail.get("initial_conditions") or detail.get("input")})
    return out


def assemble(root: Path = store.ROOT) -> dict:
    truth = truth_block(root)
    normals = normals_block(truth)
    runs, order = runs_block(root)
    data = {
        "built": f"{pd.Timestamp.now(tz='UTC'):%Y-%m-%d %H:%M} UTC",
        "version": __version__,
        "scale": SCALE, "missing": MISSING, "nlead": NLEAD,
        "regions": [{"id": r, "name": REGION_NAMES[r]} for r in REGIONS],
        "models": [
            {"id": mid,
             "label": FORECAST_MODELS[mid].label if mid in FORECAST_MODELS else mid.replace("lab_", "Lab: "),
             "family": FORECAST_MODELS[mid].family if mid in FORECAST_MODELS else "AI (Colab lab)",
             "lead_days": FORECAST_MODELS[mid].lead_days if mid in FORECAST_MODELS else None,
             "note": FORECAST_MODELS[mid].note if mid in FORECAST_MODELS else "Run in the Earth2Studio Colab lab."}
            for mid in order
        ],
        "truth": {k: v for k, v in truth.items() if not k.startswith("_")},
        "normals": normals,
        "runs": runs,
        "events": events.as_dicts(),
        "maps": maps_block(order),
        "inventory": inventory_block(root),
        "lab": lab_block(),
        "market": None,
    }
    try:
        from . import market

        data["market"] = market.dashboard_block()
    except Exception:  # the market link is optional; the rest of the page must still build
        data["market"] = None
    return data


def build(site: Path = SITE, root: Path = store.ROOT, home_link: str | None = None) -> Path:
    """Write the dashboard. ``home_link`` adds a link back to the website above the title."""
    import html

    data = assemble(root)
    payload = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    template = TEMPLATE.read_text().replace("/*__DATA__*/null", payload)
    if home_link:
        link = f'<a class="home-link" href="{html.escape(home_link, quote=True)}">&larr; Sawyer Suzuki &middot; Projects</a>'
        template = template.replace("<!--HOME_LINK-->", link)
    head, body = template.split("<!--BODY-->", 1)
    site.mkdir(parents=True, exist_ok=True)
    # fragment.html has no outer <html> wrapper, for hosts that add their own
    (site / "fragment.html").write_text(head + body)
    page = (
        "<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\">\n"
        + head + "</head>\n<body>\n" + body + "\n</body>\n</html>\n"
    )
    out = site / "index.html"
    out.write_text(page)
    return out
