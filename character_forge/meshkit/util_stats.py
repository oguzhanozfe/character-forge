"""Tiny statistics helpers (stdlib only)."""
from __future__ import annotations


def percentile(values, q):
    values = sorted(values)
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    position = (len(values) - 1) * q / 100.0
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def median(values):
    return percentile(values, 50)
