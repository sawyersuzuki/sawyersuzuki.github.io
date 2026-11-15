"""Command line: `wxcc weights | backfill | query | inventory | validate`."""

from __future__ import annotations

import pandas as pd
import typer

from . import degree_days as dd
from . import pipeline, store, validate, weights
from .regions import REGIONS

app = typer.Typer(add_completion=False, help="CONUS weather-model comparison command center.")
pd.set_option("display.width", 200, "display.max_rows", 500, "display.max_columns", 30)

MODELS = ("era5",)  # forecast models are added in phase 2


@app.command("weights")
def build_weights() -> None:
    """Download 2020 Census tract centres (3.6 MB) and build the population weights."""
    cells = weights.build_and_save()
    by_division = cells.groupby("division")["population"].sum()
    typer.echo(f"Wrote {weights.DEFAULT_PATH}: {len(cells):,} populated grid cells")
    typer.echo((by_division / 1e6).round(2).to_string() + "\n(population, millions)")


@app.command()
def backfill(
    model: str = typer.Option(..., help=f"One of: {', '.join(MODELS)}"),
    start: str = typer.Option(..., help="First day, YYYY-MM-DD"),
    end: str = typer.Option(..., help="Last day, YYYY-MM-DD"),
    method: str = typer.Option("mean6h", help=f"One of: {', '.join(dd.METHODS)}"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt"),
    refresh: bool = typer.Option(False, help="Re-fetch days that are already stored"),
) -> None:
    """Extend history. Safe to re-run: days already stored are skipped."""
    if model not in MODELS:
        raise typer.BadParameter(f"model must be one of {MODELS}")
    if method not in dd.METHODS:
        raise typer.BadParameter(f"method must be one of {tuple(dd.METHODS)}")
    plan = pipeline.plan_era5(start, end, method, refresh=refresh)
    typer.echo(plan.describe())
    if not len(plan.days):
        return
    if not yes and not typer.confirm("Proceed?"):
        raise typer.Abort()
    n = pipeline.run_era5(plan, progress=typer.echo)
    typer.echo(f"Done: {n} days stored under {store.ROOT}/{model}/")


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


@app.command("validate")
def validate_cpc(
    start: str = typer.Option(...),
    end: str = typer.Option(...),
    method: str = typer.Option("minmax1h", help="minmax1h matches CPC's (Tmax+Tmin)/2 definition"),
    variable: str = typer.Option("hdd", help="hdd or cdd"),
) -> None:
    """Compare stored ERA5 degree days with NOAA CPC's station-based values."""
    _, summary = validate.compare(start, end, method, variable)
    typer.echo(f"ERA5 ({method}) vs NOAA CPC population-weighted {variable.upper()}, {start} to {end}")
    typer.echo(summary.reindex([r for r in REGIONS if r in summary.index]).round(2).to_string())


if __name__ == "__main__":
    app()
