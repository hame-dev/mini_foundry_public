"""Quiver time-series analysis.

Pure-pandas/numpy computations (no scipy) over a (time, value) series:
rolling average, linear-regression trend, and an FFT amplitude spectrum.
Shaped for direct consumption by ECharts on the frontend.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

VALID_OPERATIONS = {"raw", "rolling", "regression", "fft"}
MAX_POINTS = 50_000


def analyze_series(
    rows: list[dict[str, Any]],
    time_column: str,
    value_column: str,
    *,
    operations: list[str] | None = None,
    resample_freq: str | None = None,
    rolling_window: int = 7,
) -> dict[str, Any]:
    ops = set(operations or ["raw", "rolling", "regression", "fft"])
    unknown = ops - VALID_OPERATIONS
    if unknown:
        raise ValueError(f"unknown operations: {sorted(unknown)}")

    if not rows:
        return {"time": [], "raw": [], "n": 0, "resample_freq": resample_freq}

    df = pd.DataFrame(rows)
    for col in (time_column, value_column):
        if col not in df.columns:
            raise ValueError(f"column {col!r} not found in dataset result")

    df[time_column] = pd.to_datetime(df[time_column], errors="coerce", utc=False)
    df[value_column] = pd.to_numeric(df[value_column], errors="coerce")
    df = df[[time_column, value_column]].dropna()
    df = df.sort_values(time_column)
    if df.empty:
        return {"time": [], "raw": [], "n": 0, "resample_freq": resample_freq}

    series = pd.Series(df[value_column].to_numpy(), index=pd.DatetimeIndex(df[time_column]))

    if resample_freq:
        series = series.resample(resample_freq).mean().interpolate(limit_direction="both")
        series = series.dropna()

    if len(series) > MAX_POINTS:
        series = series.iloc[:MAX_POINTS]

    times = [t.isoformat() for t in series.index.to_pydatetime()]
    values = [float(v) for v in series.to_numpy()]
    n = len(values)

    out: dict[str, Any] = {
        "time": times,
        "raw": values,
        "n": n,
        "resample_freq": resample_freq,
    }

    if "rolling" in ops and n:
        window = max(1, int(rolling_window))
        rolled = series.rolling(window=window, min_periods=1).mean()
        out["rolling"] = {
            "window": window,
            "values": [float(v) for v in rolled.to_numpy()],
        }

    if "regression" in ops and n >= 2:
        out["regression"] = _linear_regression(values)

    if "fft" in ops and n >= 4:
        out["fft"] = _fft_spectrum(values)

    return out


def _linear_regression(values: list[float]) -> dict[str, Any]:
    """Least-squares line fit over the sample index (slope is per sample)."""
    y = np.asarray(values, dtype=float)
    x = np.arange(len(y), dtype=float)
    slope, intercept = np.polyfit(x, y, 1)
    fitted = slope * x + intercept
    ss_res = float(np.sum((y - fitted) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return {
        "slope": float(slope),
        "intercept": float(intercept),
        "r2": r2,
        "line": [float(v) for v in fitted],
    }


def _fft_spectrum(values: list[float]) -> dict[str, Any]:
    """Single-sided amplitude spectrum of the mean-detrended series.

    Frequencies are in cycles/sample; `period` is samples/cycle. The DC
    (zero-frequency) component is dropped.
    """
    y = np.asarray(values, dtype=float)
    y = y - y.mean()
    n = len(y)
    spectrum = np.fft.rfft(y)
    amplitude = np.abs(spectrum) * 2.0 / n
    freq = np.fft.rfftfreq(n, d=1.0)

    # Drop DC term (index 0); guard against division by zero for period.
    freq = freq[1:]
    amplitude = amplitude[1:]
    with np.errstate(divide="ignore"):
        period = np.where(freq > 0, 1.0 / freq, 0.0)

    return {
        "freq": [float(f) for f in freq],
        "amplitude": [float(a) for a in amplitude],
        "period": [float(p) for p in period],
    }
