from dataclasses import dataclass


@dataclass(frozen=True)
class SourcePrice:
    """A price from a source that also reports its own daily change.

    Sources that only report a price return a plain float instead.
    """

    price: float
    day_change_pct: float | None = None  # vs the previous trading day's close
