import numpy as np
import pandas as pd
import pytest

from wxcc import fields, lab, store
from wxcc.regions import REGIONS, STATE_TO_DIVISION


@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    """Run in an empty directory with real population weights and a temp cache."""
    import shutil
    from pathlib import Path

    (tmp_path / "data/static").mkdir(parents=True)
    shutil.copy(Path(__file__).parent.parent / "data/static/pop_weights.parquet", tmp_path / "data/static")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(fields, "ROOT", tmp_path / ".cache/fields")
    return tmp_path


def global_field(times, offset_k=0.0):
    lats = np.linspace(90, -90, 721)
    lons = np.linspace(0, 360, 1440, endpoint=False)
    base = 300.0 - 0.6 * np.abs(lats)[:, None] + 0.0 * lons[None, :]  # colder toward the poles
    return np.stack([base + offset_k for _ in times]).astype(np.float32), lats, lons


def test_ingest_arrays_writes_series_manifest_and_maps(sandbox):
    init = pd.Timestamp("2026-01-10 00:00")
    times = pd.date_range(init, periods=13, freq="6h")  # 0..72 h -> 3 complete days
    t2m, lats, lons = global_field(times)
    out = lab.ingest_arrays(model="FCN3", init_time=init, valid_times=times, t2m_k=t2m, lats=lats, lons=lons,
                            config={"gpu": "test"})
    assert out["model"] == "lab_fcn3" and out["days"] == 3
    df = store.query(model="lab_fcn3")
    assert len(df) == 3 * len(REGIONS) and df["kind"].eq("forecast").all()
    assert sorted(df["lead_days"].unique()) == [0, 1, 2]
    # warmer in the south: Texas needs fewer heating degree days than New England
    by = df[df["lead_days"] == 1].set_index("region")["hdd"]
    assert by["TX"] < by["NE"]
    manifest = store.read_manifests("lab_fcn3")
    assert manifest.iloc[0]["detail"] == {"gpu": "test"} and manifest.iloc[0]["variables"] == ["t2m"]
    days, t_f = fields.load_forecast("lab_fcn3", init)
    assert len(days) == 3 and t_f.shape[1:] == (105, 235)


def test_ingest_accepts_south_to_north_and_minus180_grids(sandbox):
    init = pd.Timestamp("2026-01-10 00:00")
    times = pd.date_range(init, periods=5, freq="6h")
    t2m, lats, lons = global_field(times)
    a = lab.ingest_arrays(model="a", init_time=init, valid_times=times, t2m_k=t2m, lats=lats, lons=lons)
    shift = np.roll(t2m, 720, axis=2)
    b = lab.ingest_arrays(model="b", init_time=init, valid_times=times, t2m_k=shift[:, ::-1, :],
                          lats=lats[::-1], lons=np.linspace(-180, 180, 1440, endpoint=False))
    assert a["conus_hdd_by_day"] == b["conus_hdd_by_day"]


def test_ingest_rejects_bad_input(sandbox):
    init = pd.Timestamp("2026-01-10 00:00")
    times = pd.date_range(init, periods=5, freq="6h")
    t2m, lats, lons = global_field(times)
    with pytest.raises(ValueError, match="kelvin"):
        lab.ingest_arrays(model="x", init_time=init, valid_times=times, t2m_k=t2m - 273.15, lats=lats, lons=lons)
    with pytest.raises(ValueError, match="shape"):
        lab.ingest_arrays(model="x", init_time=init, valid_times=times[:3], t2m_k=t2m, lats=lats, lons=lons)
    with pytest.raises(ValueError, match="complete"):
        lab.ingest_arrays(model="x", init_time=init, valid_times=times[:2], t2m_k=t2m[:2], lats=lats, lons=lons)


def test_downscaled_grid_weights_and_ingest(sandbox):
    pytest.importorskip("scipy")
    lat1, lon1 = np.arange(25.0, 49.5, 0.1), np.arange(-124.0, -67.0, 0.1)
    lon2d, lat2d = np.meshgrid(lon1, lat1)
    rng = np.random.default_rng(1)
    tracts = pd.DataFrame({
        "STATEFP": np.repeat(list(STATE_TO_DIVISION), 4),
        "POPULATION": rng.integers(100, 5000, 4 * len(STATE_TO_DIVISION)),
        "LATITUDE": rng.uniform(30, 45, 4 * len(STATE_TO_DIVISION)),
        "LONGITUDE": rng.uniform(-115, -75, 4 * len(STATE_TO_DIVISION)),
    })
    w = lab.curvilinear_weights(lat2d, lon2d, tracts)
    assert w.shape == (len(REGIONS), lat2d.size)
    np.testing.assert_allclose(w.sum(axis=1), 1.0)
    times = pd.date_range("2026-01-10 06:00", periods=4, freq="6h")
    t2m = np.full((4,) + lat2d.shape, 273.15, dtype=np.float32)  # 32 F everywhere -> 33 HDD
    out = lab.ingest_downscaled(model="corrdiff_era5", valid_times=times, t2m_k=t2m, lat2d=lat2d, lon2d=lon2d, w=w)
    assert out["days"] == ["2026-01-10"] and out["conus_hdd_by_day"] == [33.0]
    df = store.query(model="lab_corrdiff_era5")
    assert df["kind"].eq("analysis").all() and df["quality"].eq("lab").all()
