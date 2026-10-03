"""Fetches current prices and pairs them with a comparison base.

- Price messages are compared with the prices of the last price message.
- The daily summary is compared with the prices of the previous daily summary (24h ago).
"""

import asyncio
import logging
from datetime import datetime

import config
from assets import ASSET_GROUPS, Asset
from formatter import Quote
from price_store import DATA_DIR, PriceStore
from sources.tgju import StalePriceError

logger = logging.getLogger(__name__)

last_post = PriceStore(DATA_DIR / "last_post.json")
last_summary = PriceStore(DATA_DIR / "last_summary.json")


async def _fetch(asset: Asset) -> float | None:
    try:
        return await asset.fetch()
    except StalePriceError as e:
        logger.warning("Leaving out %s: %s", asset.key, e)
        return None
    except Exception:
        logger.exception("Failed to fetch price for %s", asset.key)
        return None


async def _fetch_open_assets() -> dict[str, float | None]:
    """Prices of all assets whose market is open now, by key."""
    now = datetime.now(config.TIMEZONE).time()
    assets = [a for group in ASSET_GROUPS for a in group if a.is_open(now)]
    prices = await asyncio.gather(*(_fetch(a) for a in assets))
    return dict(zip((a.key for a in assets), prices))


def _build_groups(prices: dict[str, float | None], base: PriceStore) -> list[list[Quote]]:
    """Quotes grouped like ASSET_GROUPS; assets without a price and empty groups are left out."""
    result = []
    for group in ASSET_GROUPS:
        quotes = [
            Quote(a, prices[a.key], prev_price=base.get(a.key))
            for a in group
            if prices.get(a.key) is not None
        ]
        if quotes:
            result.append(quotes)
    return result


def _prices_of(groups: list[list[Quote]]) -> dict[str, float]:
    return {q.asset.key: q.price for group in groups for q in group}


async def get_quotes() -> list[list[Quote]]:
    """Quotes for the price message. Closed assets and failed fetches are left out."""
    return _build_groups(await _fetch_open_assets(), last_post)


def mark_posted(groups: list[list[Quote]]) -> None:
    """Call after a price message was posted to the channel; it becomes the next comparison base."""
    last_post.update(_prices_of(groups))


async def get_summary_quotes() -> list[list[Quote]]:
    """Quotes for the daily summary.

    Assets that are closed now (e.g. USDT at night) or failed to fetch use their price in the
    last channel post, so the summary still covers them.
    """
    prices = await _fetch_open_assets()
    for group in ASSET_GROUPS:
        for asset in group:
            if prices.get(asset.key) is None:
                prices[asset.key] = last_post.get(asset.key)
    return _build_groups(prices, last_summary)


def mark_summary_posted(groups: list[list[Quote]]) -> None:
    """Call after the daily summary was posted; tomorrow's summary is compared with it."""
    last_summary.update(_prices_of(groups))
