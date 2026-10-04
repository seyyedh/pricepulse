"""Live metal prices from gold-api.com (no API key needed).

Symbols: XAU (gold ounce), XAG (silver ounce), HG (COMEX copper, USD per pound), ...
"""

import logging

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.gold-api.com/price"
TIMEOUT = 15

POUNDS_PER_TON = 2204.62


async def fetch_price(symbol: str, multiplier: float = 1) -> float:
    """Price of a symbol like "XAU" in USD, times multiplier (e.g. POUNDS_PER_TON for copper per ton)."""
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.get(f"{BASE_URL}/{symbol}")
        resp.raise_for_status()
    try:
        return float(resp.json()["price"]) * multiplier
    except (KeyError, TypeError, ValueError) as e:
        raise RuntimeError(f"gold-api returned an invalid response for {symbol}: {resp.text[:200]}") from e
