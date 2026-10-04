"""Price samples over the last day, used to compare each price with its value an hour ago
(like a one-hour candle).

A sample is recorded every time prices are fetched (every half hour when scheduled).
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

RETENTION = timedelta(hours=26)
# A sample counts as "an hour ago" if it is at least this old...
HOUR_AGO_MIN = timedelta(minutes=50)
# ...and at most this old (older means the bot missed runs; don't compare with it)
HOUR_AGO_MAX = timedelta(minutes=120)
# Don't pile up samples when prices are fetched many times a minute (e.g. /prices)
MIN_SAMPLE_INTERVAL = timedelta(minutes=1)


class PriceHistory:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._samples: dict[str, list[tuple[datetime, float]]] = {}
        self._load()

    def price_hour_ago(self, key: str, now: datetime) -> float | None:
        newest_allowed = now - HOUR_AGO_MIN
        oldest_allowed = now - HOUR_AGO_MAX
        candidates = [s for s in self._samples.get(key, []) if oldest_allowed <= s[0] <= newest_allowed]
        return max(candidates, key=lambda s: s[0])[1] if candidates else None

    def record(self, prices: dict[str, float], at: datetime) -> None:
        cutoff = at - RETENTION
        for key, price in prices.items():
            samples = [s for s in self._samples.get(key, []) if s[0] >= cutoff]
            if not samples or at - samples[-1][0] >= MIN_SAMPLE_INTERVAL:
                samples.append((at, price))
            self._samples[key] = samples
        self._save()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self._samples = {
                key: [(datetime.fromisoformat(ts), float(price)) for ts, price in samples]
                for key, samples in raw.items()
            }
        except (ValueError, TypeError, AttributeError) as e:
            logger.warning("Could not read %s, starting with empty history: %s", self.path, e)

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        raw = {
            key: [(ts.isoformat(timespec="seconds"), price) for ts, price in samples]
            for key, samples in self._samples.items()
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)
