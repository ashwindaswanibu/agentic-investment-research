"""Illustrative executable policy; no claim of predictive performance.

The same source is run afresh on each observed-history prefix. Twenty sessions
define trend and realized volatility. Exposure is capped at 90%; a negative
trend or insufficient data requests cash. Orders fill at the next session open.
"""

from math import sqrt
from statistics import fmean, stdev


def run(payload):
    closes = [float(bar["close"]) for bar in payload["history"]]
    if len(closes) < 21:
        return {"target_weight": 0.0}
    returns = [b / a - 1 for a, b in zip(closes[-21:-1], closes[-20:], strict=True)]
    volatility = stdev(returns) * sqrt(252)
    target = min(0.9, 0.15 / volatility) if volatility > 0 else 0.0
    return {"target_weight": target if closes[-1] > fmean(closes[-20:]) else 0.0}
