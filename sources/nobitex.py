"""Prices from the Nobitex exchange public API (no API key needed)."""

import logging

import httpx

logger = logging.getLogger(__name__)

# api.nobitex.ir does not resolve from some networks; apiv2 serves the same API
BASE_URLS = (
    "https://apiv2.nobitex.ir",
    "https://api.nobitex.ir",
)
TIMEOUT = 10


async def fetch_price_toman(currency: str) -> float:
    """Returns the last traded price of a currency like "usdt" in Toman."""
    pair = f"{currency}-rls"
    last_error: Exception | None = None
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        for base in BASE_URLS:
            try:
                resp = await client.get(
                    f"{base}/market/stats",
                    params={"srcCurrency": currency, "dstCurrency": "rls"},
                )
                resp.raise_for_status()
                data = resp.json()
                if data.get("status") != "ok":
                    raise ValueError(f"unexpected response: {data}")
                rial = float(data["stats"][pair]["latest"])
                return rial / 10
            except (httpx.HTTPError, KeyError, ValueError) as e:
                logger.warning("Nobitex request to %s failed for %s: %s", base, pair, e)
                last_error = e
    raise RuntimeError(f"Could not fetch {pair} from Nobitex") from last_error
