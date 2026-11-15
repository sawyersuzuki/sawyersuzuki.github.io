import numpy as np
import pandas as pd

from wxcc import store, validate
from wxcc.regions import REGIONS
from wxcc.sources import era5


def rows(days, value=10.0, quality="final", init_time=None, model="era5"):
    days = pd.DatetimeIndex(days)
    arr = np.full((len(days), len(REGIONS)), value)
    return store.make_rows(
        model=model,
        days=days,
        regional={"hdd": arr, "cdd": arr * 0, "tmean_f": 65 - arr},
        method="mean6h",
        quality=quality,
        source="test",
        init_time=init_time,
    )


def test_make_rows_shape_and_schema():
    df = rows(["2024-01-01", "2024-01-02"])
    assert list(df.columns) == store.COLUMNS
    assert len(df) == 2 * len(REGIONS)
    assert df["kind"].eq("analysis").all() and df["init_time"].isna().all()
    assert df["lead_days"].isna().all()


def test_forecast_rows_carry_lead_days():
    df = rows(["2024-01-01", "2024-01-03"], init_time=pd.Timestamp("2024-01-01 12:00"), model="gfs")
    assert df["kind"].eq("forecast").all()
    assert sorted(df["lead_days"].unique()) == [0, 2]


def test_analysis_write_is_idempotent(tmp_path):
    df = rows(["2024-01-30", "2024-01-31", "2024-02-01"])
    paths = store.write_analysis(df, root=tmp_path)
    assert sorted(p.name for p in paths) == ["2024-01.parquet", "2024-02.parquet"]
    before = {p: p.read_bytes() for p in paths}
    store.write_analysis(df, root=tmp_path)  # same data again
    assert {p: p.read_bytes() for p in paths} == before
    assert len(store.query(root=tmp_path)) == 3 * len(REGIONS)


def test_upsert_replaces_prelim_with_final(tmp_path):
    store.write_analysis(rows(["2024-01-01"], value=10.0, quality="prelim"), root=tmp_path)
    store.write_analysis(rows(["2024-01-01"], value=11.0, quality="final"), root=tmp_path)
    df = store.query(root=tmp_path)
    assert len(df) == len(REGIONS)
    assert df["quality"].eq("final").all() and df["hdd"].eq(11.0).all()
    have = store.stored_analysis_days("era5", "mean6h", root=tmp_path)
    assert have == {pd.Timestamp("2024-01-01"): "final"}


def test_query_filters_and_inventory(tmp_path):
    store.write_analysis(rows(["2024-01-01", "2024-01-02"]), root=tmp_path)
    init = pd.Timestamp("2024-01-01 00:00")
    path = store.write_forecast(rows(["2024-01-01", "2024-01-02"], init_time=init, model="gfs"), root=tmp_path)
    assert path == tmp_path / "forecast" / "2024" / "20240101.parquet"
    # a second model and a second cycle share the day file without clobbering each other
    store.write_forecast(rows(["2024-01-02"], init_time=init, model="ifs"), root=tmp_path)
    store.write_forecast(rows(["2024-01-02"], init_time=init + pd.Timedelta(hours=12), model="gfs"), root=tmp_path)
    assert store.stored_runs("gfs", init, init, root=tmp_path) == {init, init + pd.Timedelta(hours=12)}
    assert store.stored_runs("ifs", init, init, root=tmp_path) == {init}
    assert store.stored_runs("aifs", init, init, root=tmp_path) == set()
    assert len(store.query(model="gfs", region="ENC", root=tmp_path)) == 3
    assert len(store.query(model="gfs", init="2024-01-01T00", start="2024-01-02", root=tmp_path)) == len(REGIONS)
    assert store.query(model="nope", root=tmp_path).empty
    inv = store.inventory(root=tmp_path).set_index("model")
    assert inv.loc["gfs", "runs"] == 2 and inv.loc["era5", "valid_days"] == 2


def test_era5_chunk_index():
    assert era5.chunk_index(pd.Timestamp("1900-01-01 00:00")) == 0
    assert era5.chunk_index(pd.Timestamp("2026-01-15 00:00")) == 1104840


def test_parse_cpc_file():
    text = (
        "Product: Daily Heating Degree Days\nRegions: CPC::Regions::CensusDivisions\n"
        "Weights: Population\nRegion|20260101|20260102\n1|41|47\n3|47|46\nCONUS|30|31\n"
    )
    df = validate.parse_cpc(text)
    assert set(df["region"]) == {"NE", "ENC", "CONUS"}
    got = df.set_index(["region", "valid_date"])["value"]
    assert got[("ENC", pd.Timestamp("2026-01-02"))] == 46


def test_manifests_round_trip_and_upsert(tmp_path):
    kw = dict(model="gfs", source="test", method="mean6h", n_steps=65, missing_steps=[],
              first_valid=pd.Timestamp("2024-01-01"), last_valid=pd.Timestamp("2024-01-16"))
    store.write_manifest(init_time=pd.Timestamp("2024-01-01 00:00"), **kw)
    store.write_manifest(init_time=pd.Timestamp("2024-01-01 12:00"), **kw)
    assert store.flush_manifests(root=tmp_path) == 2
    store.write_manifest(init_time=pd.Timestamp("2024-01-01 00:00"), **(kw | {"n_steps": 60}))
    store.flush_manifests(root=tmp_path)
    df = store.read_manifests("gfs", root=tmp_path)
    assert len(df) == 2
    assert df.set_index("init_time").loc["2024-01-01T00:00Z", "n_steps"] == 60
    assert df["variables"].iloc[0] == ["t2m"]


def test_lab_runs_are_stored_separately_but_queried_together(tmp_path):
    init = pd.Timestamp("2024-01-01 00:00")
    path = store.write_forecast(rows(["2024-01-01"], init_time=init, model="lab_fcn3"), root=tmp_path, lab=True)
    assert path == tmp_path / "lab" / "lab_fcn3" / "2024010100.parquet"
    assert len(store.query(model="lab_fcn3", root=tmp_path)) == len(REGIONS)
