"""Spot prices from Binance's public API (no API key needed)."""

import logging

import httpx

logger = logging.getLogger(__name__)

# data-api.binance.vision serves the same market data and is a fallback if api.binance.com is blocked
BASE_URLS = (
    "https://api.binance.com",
    "https://data-api.binance.vision",
)
TIMEOUT = 10


async def fetch_price(symbol: str) -> float:
    """Returns the last price for a symbol like "BTCUSDT"."""
    last_error: Exception | None = None
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        for base in BASE_URLS:
            try:
                resp = await client.get(f"{base}/api/v3/ticker/price", params={"symbol": symbol})
                resp.raise_for_status()
                return float(resp.json()["price"])
            except (httpx.HTTPError, KeyError, ValueError) as e:
                logger.warning("Binance request to %s failed for %s: %s", base, symbol, e)
                last_error = e
    raise RuntimeError(f"Could not fetch {symbol} from Binance") from last_error
