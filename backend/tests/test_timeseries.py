import datetime
import math

import numpy as np

from app.timeseries.service import analyze_series


def _linear_rows(n=30, slope=2.0, intercept=10.0):
    base = datetime.datetime(2024, 1, 1)
    return [
        {"t": (base + datetime.timedelta(days=i)).isoformat(), "v": intercept + slope * i}
        for i in range(n)
    ]


def test_empty_input_returns_zero_points():
    res = analyze_series([], "t", "v")
    assert res["n"] == 0
    assert res["raw"] == []


def test_rolling_and_regression_on_linear_series():
    res = analyze_series(
        _linear_rows(), "t", "v",
        operations=["raw", "rolling", "regression"], rolling_window=3,
    )
    assert res["n"] == 30
    assert len(res["raw"]) == 30
    assert res["rolling"]["window"] == 3
    assert len(res["rolling"]["values"]) == 30
    # A perfectly linear series → slope ≈ 2.0/sample and R² ≈ 1.
    assert abs(res["regression"]["slope"] - 2.0) < 1e-6
    assert res["regression"]["r2"] > 0.999


def test_fft_recovers_dominant_period():
    base = datetime.datetime(2024, 1, 1)
    n = 120
    rows = [
        {"t": (base + datetime.timedelta(hours=i)).isoformat(), "v": math.sin(2 * math.pi * i / 12)}
        for i in range(n)
    ]
    res = analyze_series(rows, "t", "v", operations=["raw", "fft"])
    fft = res["fft"]
    assert fft and fft["amplitude"]
    peak = int(np.argmax(fft["amplitude"]))
    # Dominant period should be ~12 samples.
    assert abs(fft["period"][peak] - 12.0) < 1.0


def test_resample_aggregates_to_daily():
    base = datetime.datetime(2024, 1, 1)
    # Two readings per day for 5 days.
    rows = []
    for d in range(5):
        for h in (0, 12):
            rows.append({"t": (base + datetime.timedelta(days=d, hours=h)).isoformat(), "v": d})
    res = analyze_series(rows, "t", "v", operations=["raw"], resample_freq="D")
    assert res["n"] == 5
    assert res["raw"] == [0.0, 1.0, 2.0, 3.0, 4.0]


def test_unknown_operation_raises():
    import pytest
    with pytest.raises(ValueError):
        analyze_series(_linear_rows(3), "t", "v", operations=["bogus"])
