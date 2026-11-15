import base64
import json

import numpy as np
import pandas as pd

from wxcc import build, fields, market, store
from wxcc.regions import REGIONS


def decode(b64, shape):
    a = np.frombuffer(base64.b64decode(b64), dtype="<i2").astype(float).reshape(shape)
    a[a == build.MISSING] = np.nan
    return a / build.SCALE


def rows(model, days, value, init_time=None, quality="final"):
    days = pd.DatetimeIndex(days)
    arr = np.full((len(days), len(REGIONS)), float(value))
    return store.make_rows(model=model, days=days, regional={"hdd": arr, "cdd": arr * 0 + 1, "tmean_f": 65 - arr},
                           method="mean6h", quality=quality, source="test", init_time=init_time)


def make_store(root):
    store.write_analysis(rows("era5", pd.date_range("2025-01-01", "2025-01-20"), 30), root=root)
    store.write_analysis(rows("gfs_anl", pd.date_range("2025-01-19", "2025-01-22"), 99, quality="provisional"), root=root)
    init = pd.Timestamp("2025-01-10 00:00")
    store.write_forecast(rows("gfs", pd.date_range("2025-01-10", periods=16), 28, init_time=init), root=root)
    store.write_forecast(rows("ifs", pd.date_range("2025-01-10", periods=10), 31, init_time=init), root=root)
    store.write_forecast(rows("lab_fcn3", pd.date_range("2025-01-10", periods=5), 29, init_time=init), root=root, lab=True)


def test_assemble_packs_truth_runs_and_normals(tmp_path, monkeypatch):
    monkeypatch.setattr(fields, "ROOT", tmp_path / "fields")
    monkeypatch.setattr(market, "ROOT", tmp_path / "market")
    monkeypatch.setattr(store, "MANIFESTS", tmp_path / "manifests")
    make_store(tmp_path)
    data = build.assemble(tmp_path)
    json.dumps(data)  # must be serialisable
    nr = len(REGIONS)
    assert [m["id"] for m in data["models"]] == ["gfs", "ifs", "lab_fcn3"]
    truth = decode(data["truth"]["hdd"], (data["truth"]["n"], nr))
    start = pd.Timestamp(data["truth"]["start"])
    i = (pd.Timestamp("2025-01-20") - start).days
    assert truth[i, 0] == 30.0  # ERA5 wins where both exist
    assert truth[i + 1, 0] == 99.0  # GFS analysis fills in after ERA5 ends
    assert data["truth"]["quality"][i] == "f" and data["truth"]["quality"][i + 1] == "g"
    assert data["truth"]["era5_through"] == "2025-01-20"
    gfs = decode(data["runs"]["gfs"]["hdd"], (1, build.NLEAD, nr))
    assert data["runs"]["gfs"]["inits"] == ["2025-01-10T00"]
    assert gfs[0, 0, 0] == 28.0 and gfs[0, 15, -1] == 28.0 and np.isnan(gfs[0, 16, 0])
    ifs = decode(data["runs"]["ifs"]["hdd"], (1, build.NLEAD, nr))
    assert ifs[0, 9, 0] == 31.0 and np.isnan(ifs[0, 10, 0])
    normals = decode(data["normals"]["hdd"], (366, nr))
    assert normals[9, 0] == 30.0  # 10 January, from the one year of truth available
    assert data["maps"] is None and data["market"] is None


def test_build_writes_a_self_contained_page(tmp_path, monkeypatch):
    monkeypatch.setattr(fields, "ROOT", tmp_path / "fields")
    monkeypatch.setattr(market, "ROOT", tmp_path / "market")
    monkeypatch.setattr(store, "MANIFESTS", tmp_path / "manifests")
    make_store(tmp_path / "regional")
    out = build.build(site=tmp_path / "site", root=tmp_path / "regional")
    html = out.read_text()
    assert html.startswith("<!doctype html>") and "/*__DATA__*/null" not in html
    assert html.index("<title>") < html.index("</head>") < html.index("<body>")
    assert '"inits":["2025-01-10T00"]' in html
    assert not (tmp_path / "site" / "fragment.html").read_text().startswith("<!doctype")


def test_market_block_reads_csvs(tmp_path, monkeypatch):
    monkeypatch.setattr(market, "ROOT", tmp_path)
    assert market.dashboard_block() is None
    (tmp_path / "henry_hub.csv").write_text("date,price\n2026-11-10,3.0\n")
    (tmp_path / "storage.csv").write_text("week_ending,stocks_bcf,change_bcf\n2026-11-06,3862.0,61.0\n")
    (tmp_path / "power.csv").write_text("date,zone,price\n2026-11-01,nyiso_nyc,41.5\n")
    block = market.dashboard_block()
    assert block["henry_hub"] == [{"date": "2026-11-10", "price": 3.0}]
    assert block["storage"][0]["change"] == 61.0
    assert [z["id"] for z in block["power"]] == ["nyiso_nyc"] and block["power"][0]["region"] == "NY"
