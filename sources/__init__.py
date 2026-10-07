from dataclasses import dataclass


@dataclass(frozen=True)
class SourcePrice:
    """A price from a source that also reports how it changed.

    Sources that only report a price return a plain float instead.
    """

    price: float
    day_change_pct: float | None = None  # vs the previous trading day's close
    hour_change_pct: float | None = None  # over the last hour (a one-hour candle)
