"""Iran Mercantile Exchange deposit certificate prices from chartix.ir.

There is no public API; the market page embeds its data as a Nuxt payload
(<script id="__NUXT_DATA__">), a flat JSON array where objects refer to their values by
index. The page is large and slow, so it is fetched once and shared for CACHE_TTL.
"""

import asyncio
import json
import logging
import re
import time

import httpx

from sources import SourcePrice

logger = logging.getLogger(__name__)

URL = "https://chartix.ir/market/bourse_kala"
TIMEOUT = 30
CACHE_TTL = 60  # seconds

_PAYLOAD_RE = re.compile(r'<script[^>]*id="__NUXT_DATA__"[^>]*>(.*?)</script>', re.S)

_cache: dict[str, dict] | None = None
_cache_time = 0.0
_lock = asyncio.Lock()


def _parse_symbols(html: str) -> dict[str, dict]:
    """{ticker: {"name", "last_price", "change", "changePercent", ...}} from the page's Nuxt payload."""
    match = _PAYLOAD_RE.search(html)
    if not match:
        raise ValueError("Nuxt payload not found in page")
    data = json.loads(match.group(1))

    symbols = {}
    for item in data:
        if isinstance(item, dict) and {"ticker", "last_price", "changePercent"} <= item.keys():
            resolved = {k: data[v] if isinstance(v, int) else v for k, v in item.items()}
            symbols[resolved["ticker"]] = resolved
    if not symbols:
        raise ValueError("no symbols found in Nuxt payload")
    return symbols


async def _symbols() -> dict[str, dict]:
    global _cache, _cache_time
    async with _lock:
        if _cache is not None and time.monotonic() - _cache_time < CACHE_TTL:
            return _cache
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(URL, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
        _cache = _parse_symbols(resp.text)
        _cache_time = time.monotonic()
        return _cache


async def fetch_price_toman(ticker: str) -> SourcePrice:
    """Last price (Rial on the exchange, returned in Toman) and today's change of a ticker like "GOLDBAR"."""
    symbols = await _symbols()
    try:
        s = symbols[ticker]
        return SourcePrice(float(s["last_price"]) / 10, day_change_pct=float(s["changePercent"]))
    except (KeyError, TypeError, ValueError) as e:
        raise RuntimeError(f"chartix symbol {ticker!r} missing or invalid") from e
