"""Command line: `wxcc update | backfill | query | inventory | models | validate | ...`."""

from __future__ import annotations

import pandas as pd
import typer

from . import degree_days as dd
from . import pipeline, store, weights
from .models import ALL_MODELS, ANALYSIS_MODELS, DEFAULT_UPDATE_MODELS, FORECAST_MODELS
from .regions import REGIONS

app = typer.Typer(add_completion=False, no_args_is_help=True,
                  help="CONUS weather-model comparison command center.")
pd.set_option("display.width", 200, "display.max_rows", 500, "display.max_columns", 30)


def _model_list(value: str) -> tuple[str, ...]:
    if value == "all":
        return DEFAULT_UPDATE_MODELS
    ids = tuple(v.strip() for v in value.split(",") if v.strip())
    unknown = [i for i in ids if i not in ALL_MODELS]
    if unknown:
        raise typer.BadParameter(f"unknown model(s) {unknown}; choose from {', '.join(ALL_MODELS)} or 'all'")
    return ids


@app.command()
def update(
    models: str = typer.Option("all", help="Comma-separated forecast models, or 'all'"),
    days: int = typer.Option(3, help="Look back this many days for runs not yet stored"),
    market: bool = typer.Option(True, help="Also refresh Henry Hub, storage and power prices"),
) -> None:
    """Daily job: fetch the latest runs of every model and refresh the truth series."""
    ids = tuple(i for i in _model_list(models) if i in FORECAST_MODELS)
    reports = pipeline.update(ids, days=days, progress=typer.echo)
    if market:
        from . import market as mkt

        mkt.update(progress=typer.echo)
    failed = sum(len(r.failed) for r in reports.values())
    stored = sum(len(r.stored) for r in reports.values())
    typer.echo(f"Done: {stored} new runs stored" + (f", {failed} failed" if failed else "") + ".")
    if failed and not stored:
        raise typer.Exit(1)


@app.command()
def backfill(
    model: str = typer.Option(..., help=f"One of: {', '.join(ALL_MODELS)}; comma-separated; or 'all' forecast models"),
    start: str = typer.Option(..., help="First day, YYYY-MM-DD (run date for forecasts, valid date for truth)"),
    end: str = typer.Option(..., help="Last day, YYYY-MM-DD"),
    method: str = typer.Option("mean6h", help=f"Truth only. One of: {', '.join(dd.METHODS)}"),
    cycles: str = typer.Option("", help="Forecast run hours, e.g. '0' or '0,12'. Default: the model's usual cycles"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt"),
    refresh: bool = typer.Option(False, help="Re-fetch what is already stored"),
) -> None:
    """Extend history. Safe to re-run and to interrupt: what is already stored is skipped."""
    if method not in dd.METHODS:
        raise typer.BadParameter(f"method must be one of {tuple(dd.METHODS)}")
    cyc = tuple(int(c) for c in cycles.split(",") if c.strip()) or None
    plans = []
    for model_id in _model_list(model):
        if model_id == "era5":
            plans.append(pipeline.plan_era5(start, end, method, refresh=refresh))
        elif model_id == "gfs_anl":
            plans.append(pipeline.plan_gfs_analysis(start, end, refresh=refresh))
        else:
            plans.append(pipeline.plan_forecast(model_id, start, end, cyc, refresh=refresh))
    for plan in plans:
        typer.echo(plan.describe())
    todo = [p for p in plans if p.items]
    if not todo:
        return
    if len(todo) > 1:
        typer.echo(f"TOTAL: ~{sum(p.download_mb for p in todo):,.0f} MB download, "
                   f"~{sum(p.stored_kb for p in todo) / 1024:,.1f} MB in the repo, "
                   f"~{sum(p.est_minutes for p in todo):.0f} min")
    if not yes and not typer.confirm("Proceed?"):
        raise typer.Abort()
    for plan in todo:
        if plan.model == "era5":
            n = pipeline.run_era5(plan, progress=typer.echo)
            typer.echo(f"era5: {n} days stored")
        elif plan.model == "gfs_anl":
            n = pipeline.run_gfs_analysis(plan, progress=typer.echo)
            typer.echo(f"gfs_anl: {n} days stored")
        else:
            report = pipeline.run_forecast(plan, progress=typer.echo)
            typer.echo(f"{plan.model}: {len(report.stored)} runs stored, "
                       f"{len(report.not_published)} not in the archive, {len(report.failed)} failed")


@app.command()
def query(
    model: str = typer.Option(None),
    region: str = typer.Option(None, help=f"One of: {', '.join(REGIONS)}"),
    start: str = typer.Option(None, help="First valid date"),
    end: str = typer.Option(None, help="Last valid date"),
    init: str = typer.Option(None, help="Forecast run time, e.g. 2026-11-15T00"),
    method: str = typer.Option(None),
    csv: bool = typer.Option(False, help="Print CSV instead of a table"),
) -> None:
    """Ask what is stored, e.g. HDD for region X, model Y, init date Z."""
    df = store.query(model=model, region=region, start=start, end=end, init=init, method=method)
    if df.empty:
        typer.echo("No rows match.")
        return
    cols = ["model", "init_time", "valid_date", "lead_days", "region", "method", "hdd", "cdd", "tmean_f", "quality"]
    out = df[cols].assign(valid_date=df["valid_date"].dt.date)
    typer.echo(out.to_csv(index=False) if csv else out.to_string(index=False))


@app.command()
def inventory() -> None:
    """Summarise everything in the store."""
    df = store.inventory()
    typer.echo("Store is empty." if df.empty else df.to_string(index=False))


@app.command()
def check() -> None:
    """Verify the store and the cache: readable files, no duplicates, a manifest per run, sizes."""
    from . import fields

    report = store.check()
    data_mb = sum(p.stat().st_size for p in store.ROOT.parent.rglob("*") if p.is_file()) / 1e6
    typer.echo(f"Store: {report['files']} files, {report['rows']:,} rows, {report['runs']:,} forecast runs, {data_mb:.1f} MB under data/")
    typer.echo(f"  unreadable files: {len(report['unreadable'])}" + ("  " + ", ".join(report["unreadable"][:5]) if report["unreadable"] else ""))
    typer.echo(f"  duplicate keys:   {report['duplicate_keys']}")
    typer.echo(f"  runs without a manifest: {report['runs_without_manifest']}"
               + (f" (reconstructed {report['manifests_added']})" if report["manifests_added"] else ""))
    typer.echo(f"Cache: {fields.cache_size_gb():.2f} GB of {fields.CACHE_CAP_GB:g} GB cap")
    if report["unreadable"] or report["duplicate_keys"]:
        raise typer.Exit(1)


@app.command()
def models() -> None:
    """List every model: what it is, where it comes from and how far back it goes."""
    rows = [
        {"id": m.id, "name": m.label, "type": m.family, "from": m.first_init,
         "lead_days": m.lead_days or "", "source": m.provider, "licence": m.licence}
        for m in list(FORECAST_MODELS.values()) + list(ANALYSIS_MODELS.values())
    ]
    typer.echo(pd.DataFrame(rows).to_string(index=False))


@app.command()
def market() -> None:
    """Refresh Henry Hub, EIA storage and day-ahead power prices (all free, no keys)."""
    from . import market as mkt

    mkt.update(progress=typer.echo)


@app.command()
def build() -> None:
    """Rebuild the dashboard (site/index.html) from what is stored."""
    from . import build as builder

    out = builder.build()
    typer.echo(f"Wrote {out} ({out.stat().st_size / 1e6:.1f} MB). Open it in a browser, or run `wxcc serve`.")


@app.command()
def serve(port: int = typer.Option(8765, help="Local port")) -> None:
    """Rebuild the dashboard and serve it at http://localhost:<port> until you press Ctrl-C."""
    import functools
    import http.server

    from . import build as builder

    builder.build()
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(builder.SITE))
    typer.echo(f"Dashboard at http://localhost:{port}  (Ctrl-C to stop)")
    http.server.ThreadingHTTPServer(("127.0.0.1", port), handler).serve_forever()


@app.command("weights")
def build_weights() -> None:
    """Download 2020 Census tract centres (3.6 MB) and rebuild the population weights."""
    cells = weights.build_and_save()
    by_division = cells.groupby("division")["population"].sum()
    typer.echo(f"Wrote {weights.DEFAULT_PATH}: {len(cells):,} populated grid cells")
    typer.echo((by_division / 1e6).round(2).to_string() + "\n(population, millions)")


@app.command("validate")
def validate_cpc(
    start: str = typer.Option(...),
    end: str = typer.Option(...),
    method: str = typer.Option("minmax1h", help="minmax1h matches CPC's (Tmax+Tmin)/2 definition"),
    variable: str = typer.Option("hdd", help="hdd or cdd"),
) -> None:
    """Compare stored ERA5 degree days with NOAA CPC's station-based values."""
    from . import validate

    _, summary = validate.compare(start, end, method, variable)
    typer.echo(f"ERA5 ({method}) vs NOAA CPC population-weighted {variable.upper()}, {start} to {end}")
    typer.echo(summary.reindex([r for r in REGIONS if r in summary.index]).round(2).to_string())


fields_app = typer.Typer(help="Daily temperature maps: local cache and long-term storage on GitHub Releases.")
app.add_typer(fields_app, name="fields")


def _months(months: str, last: int) -> list[str]:
    if months:
        return [m.strip() for m in months.split(",") if m.strip()]
    now = pd.Timestamp.now(tz="UTC").tz_localize(None)
    return [f"{(now - pd.DateOffset(months=i)):%Y-%m}" for i in range(last)]


@fields_app.command("status")
def fields_status() -> None:
    """Show what is in the local map cache."""
    from . import fields

    present = fields.months_present()
    for model, months in present.items():
        typer.echo(f"  {model:12s} {len(months):3d} months  {months[0]} to {months[-1]}")
    typer.echo(f"Cache: {fields.cache_size_gb():.2f} GB of {fields.CACHE_CAP_GB:g} GB cap ({fields.CACHE})")


@fields_app.command("publish")
def fields_publish(
    months: str = typer.Option("", help="Months to upload, e.g. 2026-10,2026-11. Default: the last two months"),
    all_months: bool = typer.Option(False, "--all", help="Upload every month in the local cache"),
) -> None:
    """Upload map bundles to this repository's GitHub Releases (needs the gh CLI, signed in)."""
    from . import fields

    wanted = sorted({m for ms in fields.months_present().values() for m in ms}) if all_months else _months(months, 2)
    n = fields.publish(wanted, progress=typer.echo)
    typer.echo(f"Uploaded {n} bundles.")


@fields_app.command("pull")
def fields_pull(months: str = typer.Option("", help="Months to download, e.g. 2021-02. Default: the last two months")) -> None:
    """Download map bundles into the local cache (kept under the cache cap)."""
    from . import fields

    n = fields.pull(_months(months, 2), progress=typer.echo)
    typer.echo(f"Unpacked {n} bundles. Cache: {fields.cache_size_gb():.2f} GB")


@app.command("validate-stations")
def validate_stations(month: str = typer.Option(..., help="Month to check, YYYY-MM")) -> None:
    """Compare ERA5 with 31 big-city airport stations (downloads about 1.8 GB of ERA5, stores nothing)."""
    from . import validate

    year, mon = (int(x) for x in month.split("-"))
    df = validate.station_check(year, mon)
    typer.echo(df.round(2).to_string(index=False))
    by_div = df.groupby("division")["era5_minus_station"].mean().round(2)
    typer.echo("\nERA5 minus station, mean by division (F):\n" + by_div.to_string())
    typer.echo(f"\nAll stations: ERA5 is {df['era5_minus_station'].mean():+.2f} F relative to stations "
               f"(median {df['era5_minus_station'].median():+.2f} F, {len(df)} stations)")


if __name__ == "__main__":
    app()
