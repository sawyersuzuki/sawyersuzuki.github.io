import numpy as np
import pandas as pd
import pytest

from wxcc import degree_days as dd


def f_to_k(t_f):
    return (np.asarray(t_f, dtype=float) - 32.0) * 5.0 / 9.0 + 273.15


def test_kelvin_to_f_reference_points():
    assert dd.kelvin_to_f(273.15) == pytest.approx(32.0)
    assert dd.kelvin_to_f(373.15) == pytest.approx(212.0)
    assert dd.kelvin_to_f(255.3722222) == pytest.approx(0.0, abs=1e-6)


def test_hdd_cdd_values_and_base():
    t = np.array([30.0, 65.0, 80.0])
    np.testing.assert_allclose(dd.hdd(t), [35.0, 0.0, 0.0])
    np.testing.assert_allclose(dd.cdd(t), [0.0, 0.0, 15.0])
    np.testing.assert_allclose(dd.hdd(t, base=60.0), [30.0, 0.0, 0.0])


def test_hdd_and_cdd_never_both_positive():
    t = np.linspace(-40, 120, 500)
    assert (dd.hdd(t) >= 0).all() and (dd.cdd(t) >= 0).all()
    assert (dd.hdd(t) * dd.cdd(t) == 0).all()
    np.testing.assert_allclose(dd.cdd(t) - dd.hdd(t), t - dd.BASE_F)


def test_required_times_6h_window_is_06z_to_00z_next_day():
    times = dd.required_times(pd.Timestamp("2021-02-15"), "mean6h")
    assert list(times) == list(
        pd.to_datetime(["2021-02-15 06:00", "2021-02-15 12:00", "2021-02-15 18:00", "2021-02-16 00:00"])
    )


def test_required_times_hourly_window_has_24_samples():
    times = dd.required_times(pd.Timestamp("2021-02-15"), "minmax1h")
    assert len(times) == 24
    assert times[0] == pd.Timestamp("2021-02-15 06:00")
    assert times[-1] == pd.Timestamp("2021-02-16 05:00")


def test_daily_mean6h_labels_and_values():
    # 00Z on the 1st belongs to the previous day (Dec 31), which is incomplete and dropped.
    times = pd.date_range("2024-01-01 00:00", "2024-01-03 00:00", freq="6h")
    temps_f = np.arange(len(times), dtype=float) * 2.0 + 20.0
    daily = dd.daily_temperature(times, f_to_k(temps_f)[:, None, None], "mean6h")
    assert list(daily.days) == list(pd.to_datetime(["2024-01-01", "2024-01-02"]))
    # day 1 uses samples 1..4 (06,12,18,00Z), day 2 uses samples 5..8
    np.testing.assert_allclose(daily.t_f[:, 0, 0], [temps_f[1:5].mean(), temps_f[5:9].mean()])
    assert daily.n_samples == 4


def test_incomplete_days_are_dropped_not_estimated():
    times = pd.date_range("2024-01-01 06:00", "2024-01-02 18:00", freq="6h")  # day 2 lacks 00Z
    daily = dd.daily_temperature(times, np.full((len(times), 1), 280.0), "mean6h")
    assert list(daily.days) == [pd.Timestamp("2024-01-01")]


def test_gap_inside_a_day_drops_only_that_day():
    times = pd.date_range("2024-01-01 06:00", "2024-01-04 00:00", freq="6h")
    keep = times != pd.Timestamp("2024-01-02 12:00")
    daily = dd.daily_temperature(times[keep], np.full((keep.sum(), 1), 280.0), "mean6h")
    assert list(daily.days) == list(pd.to_datetime(["2024-01-01", "2024-01-03"]))


def test_minmax_differs_from_mean_for_skewed_day():
    times = dd.required_times(pd.Timestamp("2024-07-01"), "minmax1h")
    temps_f = np.full(24, 60.0)
    temps_f[10] = 100.0  # one hot hour
    t_k = f_to_k(temps_f)[:, None]
    assert dd.daily_temperature(times, t_k, "minmax1h").t_f[0, 0] == pytest.approx(80.0)
    assert dd.daily_temperature(times, t_k, "mean1h").t_f[0, 0] == pytest.approx(60.0 + 40.0 / 24)


def test_mean6h_subsamples_hourly_input():
    # 24 hourly samples from 06Z: the four synoptic ones are at offsets 0, 6, 12 and 18 h
    times = pd.date_range("2024-01-01 06:00", periods=24, freq="1h")
    daily = dd.daily_temperature(times, f_to_k(np.arange(24.0))[:, None], "mean6h")
    assert daily.t_f[0, 0] == pytest.approx(np.mean([0, 6, 12, 18]))
    # without the 00Z sample the day cannot be formed
    daily = dd.daily_temperature(times[:18], f_to_k(np.arange(18.0))[:, None], "mean6h")
    assert daily.days.empty


def test_timezone_aware_times_are_handled():
    times = pd.date_range("2024-01-01 06:00", periods=4, freq="6h", tz="UTC")
    daily = dd.daily_temperature(times, np.full((4, 1), 273.15), "mean6h")
    assert list(daily.days) == [pd.Timestamp("2024-01-01")]


def test_unknown_method_and_duplicate_times_raise():
    times = pd.date_range("2024-01-01 06:00", periods=4, freq="6h")
    with pytest.raises(ValueError):
        dd.daily_temperature(times, np.zeros((4, 1)), "nope")
    dup = times.append(times[:1])
    with pytest.raises(ValueError):
        dd.daily_temperature(dup, np.zeros((5, 1)), "mean6h")
