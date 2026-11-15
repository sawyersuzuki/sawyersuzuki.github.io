import numpy as np
import pandas as pd
import pytest

from wxcc import degree_days as dd
from wxcc import grid, weights
from wxcc.regions import CONUS, DIVISIONS, REGIONS, STATE_TO_DIVISION


def tracts(rows):
    return pd.DataFrame(rows, columns=["STATEFP", "POPULATION", "LATITUDE", "LONGITUDE"])


def test_every_conus_state_maps_to_exactly_one_division():
    assert len(STATE_TO_DIVISION) == 49  # 48 states + DC
    assert sum(len(states) for _, _, states in DIVISIONS.values()) == 49
    for excluded in ("02", "15", "72"):  # Alaska, Hawaii, Puerto Rico
        assert excluded not in STATE_TO_DIVISION


def test_grid_shape_and_global_crop():
    assert grid.SHAPE == (105, 235)
    rows, cols = grid.global_slices(lat_first=90.0, lon_first=0.0)
    glat = np.arange(90, -90.25, -0.25)
    glon = np.arange(0, 360, 0.25)
    np.testing.assert_allclose(glat[rows], grid.LATS)
    np.testing.assert_allclose(((glon[cols] + 180) % 360) - 180, grid.LONS)
    rows, cols = grid.global_slices(lat_first=90.0, lon_first=-180.0)
    np.testing.assert_allclose(np.arange(-180, 180, 0.25)[cols], grid.LONS)


def test_tracts_snap_to_nearest_cell_and_outsiders_drop():
    cells = weights.build_cell_population(
        tracts(
            [
                ("17", 100, 41.88, -87.63),  # Chicago -> 42.00, -87.75
                ("17", 50, 41.90, -87.70),  # same cell
                ("02", 999, 61.2, -149.9),  # Alaska: excluded
                ("48", 0, 29.76, -95.37),  # zero population: dropped
            ]
        )
    )
    assert len(cells) == 1
    assert cells.loc[0, "population"] == 150
    assert (cells.loc[0, "lat"], cells.loc[0, "lon"]) == (42.0, -87.75)
    assert cells.loc[0, "division"] == "ENC"


def full_tracts():
    rng = np.random.default_rng(0)
    rows = []
    for fips in STATE_TO_DIVISION:
        for _ in range(3):
            rows.append((fips, int(rng.integers(1, 5000)), rng.uniform(26, 48), rng.uniform(-120, -70)))
    return tracts(rows)


def test_weight_rows_sum_to_one_and_conus_is_population_share():
    cells = weights.build_cell_population(full_tracts())
    w = weights.weight_matrix(cells)
    assert w.shape == (len(REGIONS), grid.NLAT * grid.NLON)
    np.testing.assert_allclose(w.sum(axis=1), 1.0)
    assert (w >= 0).all()
    # CONUS weights are the population-share-weighted blend of division weights
    share = cells.groupby("division")["population"].sum() / cells["population"].sum()
    blend = sum(share[r] * w[i] for i, r in enumerate(REGIONS) if r in DIVISIONS)
    np.testing.assert_allclose(w[REGIONS.index(CONUS)], blend)


def test_regional_mean_of_constant_field_is_that_constant():
    w = weights.weight_matrix(weights.build_cell_population(full_tracts()))
    field = np.full((3,) + grid.SHAPE, 42.0)
    np.testing.assert_allclose(weights.regional_mean(field, w), 42.0)
    assert weights.regional_mean(field, w).shape == (3, len(REGIONS))


def test_hdd_must_be_computed_before_averaging():
    """Two equal-population cells at 55 F and 75 F: mean temp is 65 F (0 HDD) but true HDD is 5."""
    cells = weights.build_cell_population(
        tracts([("17", 100, 42.0, -88.0), ("17", 100, 40.0, -89.0)]
               # one filler tract in every other division so all regions have population
               + [(f, 1, 35.0, -100.0) for f, d in STATE_TO_DIVISION.items() if d != "ENC"])
    )
    w = weights.weight_matrix(cells)
    t_f = np.full(grid.SHAPE, 65.0)
    r1, c1, _ = grid.nearest_index(np.array([42.0]), np.array([-88.0]))
    r2, c2, _ = grid.nearest_index(np.array([40.0]), np.array([-89.0]))
    t_f[r1, c1], t_f[r2, c2] = 55.0, 75.0
    enc = REGIONS.index("ENC")
    assert weights.regional_mean(dd.hdd(t_f), w)[enc] == pytest.approx(5.0)
    assert dd.hdd(weights.regional_mean(t_f, w)[enc]) == pytest.approx(0.0)


def test_state_regions_use_only_their_states():
    cells = weights.build_cell_population(full_tracts())
    w = weights.weight_matrix(cells)
    tx = cells[cells["state"] == "48"]
    expected = np.zeros(grid.NLAT * grid.NLON)
    np.add.at(expected, tx["row"].to_numpy() * grid.NLON + tx["col"].to_numpy(), tx["population"].to_numpy(float))
    np.testing.assert_allclose(w[REGIONS.index("TX")], expected / expected.sum())
    pnw = w[REGIONS.index("PNW")]
    others = cells[~cells["state"].isin(["41", "53"])]
    only_others = np.setdiff1d(
        others["row"] * grid.NLON + others["col"],
        (cells[cells["state"].isin(["41", "53"])]["row"] * grid.NLON
         + cells[cells["state"].isin(["41", "53"])]["col"]),
    )
    assert pnw[only_others].sum() == 0


def test_missing_region_raises():
    cells = weights.build_cell_population(tracts([("17", 100, 42.0, -88.0)]))
    with pytest.raises(ValueError, match="no population"):
        weights.weight_matrix(cells)
