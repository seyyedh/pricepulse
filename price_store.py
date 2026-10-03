"""A small persistent {asset key: price} store, used as a comparison base.

update() only overwrites the given assets: assets missing from a post (e.g. USDT while
its market is closed) keep their older price, so the first post after the market opens
is compared with the last price posted before it closed.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Next to the code, so it doesn't depend on the directory the bot is started from
DATA_DIR = Path(__file__).resolve().parent / "data"


class PriceStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._prices: dict[str, float] = {}
        self._load()

    def get(self, key: str) -> float | None:
        return self._prices.get(key)

    def update(self, prices: dict[str, float]) -> None:
        self._prices.update(prices)
        self._save()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            self._prices = {k: float(v) for k, v in json.loads(self.path.read_text(encoding="utf-8")).items()}
        except (ValueError, TypeError, AttributeError) as e:
            logger.warning("Could not read %s, starting empty: %s", self.path, e)

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._prices, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)
