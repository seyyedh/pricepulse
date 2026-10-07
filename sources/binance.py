"""Spot prices from Binance's public API (no API key needed)."""

import logging

import httpx

from sources import SourcePrice

logger = logging.getLogger(__name__)

# data-api.binance.vision serves the same market data and is a fallback if api.binance.com is blocked
BASE_URLS = (
    "https://api.binance.com",
    "https://data-api.binance.vision",
)
TIMEOUT = 10


async def fetch_price(symbol: str) -> SourcePrice:
    """Last price of a symbol like "BTCUSDT", with its change over the last hour."""
    last_error: Exception | None = None
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        for base in BASE_URLS:
            try:
                # Rolling-window ticker: the last hour, like a one-hour candle ending now
                resp = await client.get(f"{base}/api/v3/ticker", params={"symbol": symbol, "windowSize": "1h"})
                resp.raise_for_status()
                data = resp.json()
                return SourcePrice(float(data["lastPrice"]), hour_change_pct=float(data["priceChangePercent"]))
            except (httpx.HTTPError, KeyError, ValueError) as e:
                logger.warning("Binance request to %s failed for %s: %s", base, symbol, e)
                last_error = e
    raise RuntimeError(f"Could not fetch {symbol} from Binance") from last_error
