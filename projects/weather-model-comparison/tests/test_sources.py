import zlib

import numpy as np
import pandas as pd
import pytest

from wxcc import grid
from wxcc.sources import cira, ecmwf, gfs, grib
from wxcc.sources.http import NotAvailable

IDX = """434:231100000:d=2021021000:PRES:surface:6 hour fcst:
435:232227369:d=2021021000:TMP:2 m above ground:6 hour fcst:
436:233075141:d=2021021000:SPFH:2 m above ground:6 hour fcst:
"""


def test_gfs_index_gives_offset_and_length_of_t2m():
    assert gfs.t2m_range(IDX) == (232227369, 233075141 - 232227369)
    last = "1:0:d=2021021000:TMP:2 m above ground:6 hour fcst:\n"
    assert gfs.t2m_range(last) == (0, None)  # last message: read to end of file
    with pytest.raises(NotAvailable):
        gfs.t2m_range("1:0:d=2021021000:PRES:surface:anl:\n")


def test_gfs_url_follows_the_2021_layout_change():
    old = gfs.gfs_url(pd.Timestamp("2021-02-10 00:00"), 6)
    new = gfs.gfs_url(pd.Timestamp("2026-11-15 12:00"), 384)
    assert old.endswith("gfs.20210210/00/gfs.t00z.pgrb2.0p25.f006")
    assert new.endswith("gfs.20261115/12/atmos/gfs.t12z.pgrb2.0p25.f384")


def test_noaa_ai_url_switches_from_graphcastgfs_to_aigfs():
    assert "graphcastgfs.20250110/00/forecasts_13_levels" in gfs.ai_url(pd.Timestamp("2025-01-10"), 6)
    assert gfs.ai_url(pd.Timestamp("2026-11-14"), 6).endswith("aigfs.20261114/00/model/atmos/grib2/aigfs.t00z.sfc.f006.grib2")


def test_ecmwf_index_and_layouts():
    index = (
        '{"type": "fc", "step": "6", "param": "2d", "_offset": 1, "_length": 2}\n'
        '{"type": "fc", "step": "6", "param": "2t", "_offset": 22573074, "_length": 310883}\n'
    )
    assert ecmwf.t2m_range(index) == (22573074, 310883)
    with pytest.raises(NotAvailable):
        ecmwf.t2m_range('{"param": "msl", "_offset": 1, "_length": 2}\n')
    ifs = ecmwf.candidates("ifs", pd.Timestamp("2024-01-10 00:00"))
    assert ifs[0].endswith("20240110/00z/ifs/0p25/oper") and ifs[-1].endswith("20240110/00z/0p4-beta/oper")
    assert ecmwf.candidates("ifs", pd.Timestamp("2026-11-15 06:00"))[0].endswith("/scda")
    assert ecmwf.candidates("aifs", pd.Timestamp("2025-03-01"))[0].endswith("aifs-single/0p25/oper")
    assert ecmwf.IFS().steps(pd.Timestamp("2026-11-15 00:00"))[-1] == 240
    assert ecmwf.IFS().steps(pd.Timestamp("2026-11-15 06:00"))[-1] == 90
    assert ecmwf.AIFS().steps(pd.Timestamp("2026-11-15 00:00"))[-1] == 360


def lat_lon_field(lats, lons):
    """A field equal to latitude + longitude/1000 (in -180..180), so position is readable from value."""
    lon180 = ((lons + 180) % 360) - 180
    return lats[:, None] + lon180[None, :] / 1000.0


def expected_conus():
    return grid.LATS[:, None] + grid.LONS[None, :] / 1000.0


@pytest.mark.parametrize("lon_first", [0.0, 180.0, -180.0])
def test_crop_of_quarter_degree_grid_is_exact(lon_first):
    lats = np.arange(90, -90.25, -0.25)
    lons = lon_first + np.arange(1440) * 0.25
    out = grib.to_conus(lat_lon_field(lats, lons), 90.0, lon_first, 0.25)
    assert out.shape == grid.SHAPE
    np.testing.assert_allclose(out, expected_conus(), atol=1e-4)


def test_coarser_grid_is_interpolated_bilinearly():
    lats = np.arange(90, -90.4, -0.4)
    lons = -180 + np.arange(900) * 0.4
    out = grib.to_conus(lat_lon_field(lats, lons), 90.0, -180.0, 0.4)
    # the test field is linear in latitude and longitude, so bilinear interpolation is exact
    np.testing.assert_allclose(out, expected_conus(), atol=1e-4)


def test_hdf5_unshuffle_round_trip():
    data = np.arange(12, dtype="<f4").reshape(3, 4) * 1.5
    shuffled = np.frombuffer(data.tobytes(), dtype=np.uint8).reshape(-1, 4).T.tobytes()
    assert cira._unshuffle(shuffled, 4) == data.tobytes()
    assert zlib.decompress(zlib.compress(shuffled)) == shuffled


def test_cira_url():
    url = cira.run_url("PANG_v100_GFS", pd.Timestamp("2021-02-10 12:00"))
    assert url.endswith("PANG_v100_GFS/2021/0210/PANG_v100_GFS_2021021012_f000_f240_06.nc")
