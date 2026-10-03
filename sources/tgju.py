"""Prices from tgju.org (Iran free-market dollar, gold, coins, global commodities, ...).

tgju serves every price it tracks in one large (~170 KB) and slow JSON file, so it is
fetched once and shared between assets for CACHE_TTL.
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

logger = logging.getLogger(__name__)

BASE_URLS = (
    "https://call4.tgju.org",
    "https://call3.tgju.org",
    "https://call1.tgju.org",
)
TIMEOUT = 30
CACHE_TTL = 60  # seconds
# Timestamps in tgju data ("ts") are Tehran time
TGJU_TZ = ZoneInfo("Asia/Tehran")

_cache: dict | None = None
_cache_time = 0.0
_lock = asyncio.Lock()


class StalePriceError(RuntimeError):
    pass


async def _current_prices() -> dict:
    global _cache, _cache_time
    async with _lock:
        if _cache is not None and time.monotonic() - _cache_time < CACHE_TTL:
            return _cache

        last_error: Exception | None = None
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            for base in BASE_URLS:
                try:
                    resp = await client.get(f"{base}/ajax.json")
                    resp.raise_for_status()
                    _cache = resp.json()["current"]
                    _cache_time = time.monotonic()
                    return _cache
                except (httpx.HTTPError, KeyError, ValueError) as e:
                    logger.warning("tgju request to %s failed: %s", base, e)
                    last_error = e
        raise RuntimeError("Could not fetch prices from tgju") from last_error


async def fetch_price(key: str, max_age: timedelta, divisor: float = 1) -> float:
    """Price of a tgju item, e.g. "ons" (gold ounce, USD) or "price_dollar_rl" (Rial; divisor=10 for Toman).

    Raises StalePriceError if tgju last updated the item more than max_age ago, since
    tgju keeps serving items it no longer tracks with their old price.
    """
    prices = await _current_prices()
    try:
        item = prices[key]
        price = float(item["p"].replace(",", "")) / divisor
        updated_at = datetime.fromisoformat(item["ts"]).replace(tzinfo=TGJU_TZ)
    except (KeyError, ValueError, AttributeError) as e:
        raise RuntimeError(f"tgju item {key!r} missing or invalid") from e

    age = datetime.now(TGJU_TZ) - updated_at
    if age > max_age:
        raise StalePriceError(f"tgju item {key!r} was last updated {updated_at:%Y-%m-%d %H:%M} ({age} ago)")
    return price
