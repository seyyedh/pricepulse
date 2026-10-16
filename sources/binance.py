"""Spot prices from Binance's public API (no API key needed)."""

import asyncio
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
    """Last price of a symbol like "BTCUSDT", with its change over the last hour and day."""
    last_error: Exception | None = None
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        for base in BASE_URLS:
            try:
                # Rolling-window tickers ending now: the last hour (like a one-hour candle) and
                # the last 24 hours (crypto trades nonstop, so "day" means the last 24h)
                hour, day = await asyncio.gather(*(
                    client.get(f"{base}/api/v3/ticker", params={"symbol": symbol, "windowSize": window})
                    for window in ("1h", "1d")
                ))
                hour.raise_for_status()
                day.raise_for_status()
                return SourcePrice(
                    float(hour.json()["lastPrice"]),
                    day_change_pct=float(day.json()["priceChangePercent"]),
                    hour_change_pct=float(hour.json()["priceChangePercent"]),
                )
            except (httpx.HTTPError, KeyError, ValueError) as e:
                logger.warning("Binance request to %s failed for %s: %s", base, symbol, e)
                last_error = e
    raise RuntimeError(f"Could not fetch {symbol} from Binance") from last_error
