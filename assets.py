"""The assets shown in the price message, in display order."""

import asyncio
from dataclasses import dataclass, replace
from datetime import time, timedelta
from functools import partial
from typing import Awaitable, Callable

from sources import SourcePrice, binance, chartix, goldapi, nobitex, tgju


@dataclass(frozen=True)
class Asset:
    key: str  # stable id, used to remember past prices
    name: str  # shown in the price message
    symbol: str  # shown in the daily summary
    unit: str
    fetch: Callable[[], Awaitable[float | SourcePrice]]
    decimals: int = 0  # max decimals shown
    # (open, close) in Tehran time; outside it the asset is left out of the message.
    # None means it is always shown.
    trading_hours: tuple[time, time] | None = None
    # Show the source's daily change next to the price (and color by it)
    show_day_change: bool = False

    def is_open(self, now: time) -> bool:
        if self.trading_hours is None:
            return True
        open_at, close_at = self.trading_hours
        return open_at <= now < close_at

    @property
    def is_usd(self) -> bool:
        return self.unit.startswith("دلار")


# How old a tgju price may be before it is treated as stale and left out. Generous enough
# to cover weekends (global markets: Sat-Sun, Iran: Friday) and short holidays.
GLOBAL_MAX_AGE = timedelta(days=3)
IRAN_MAX_AGE = timedelta(days=4)

GRAMS_PER_MESGHAL = 4.608


def _tgju(key: str, max_age: timedelta = GLOBAL_MAX_AGE) -> Callable[[], Awaitable[SourcePrice]]:
    return partial(tgju.fetch_price, key, max_age)


def _tgju_toman(key: str) -> Callable[[], Awaitable[SourcePrice]]:
    # tgju quotes Iranian prices in Rial
    return partial(tgju.fetch_price, key, IRAN_MAX_AGE, divisor=10)


def _with_tgju_day_change(
    fetch: Callable[[], Awaitable[float]], tgju_key: str
) -> Callable[[], Awaitable[SourcePrice]]:
    """Price from fetch, plus the day change of the same instrument on tgju.

    For sources that report no change of their own, so the trend has a fallback when the
    price an hour ago isn't known. If tgju fails, the price is still returned.
    """
    async def fetch_with_change() -> SourcePrice:
        price, tgju_price = await asyncio.gather(fetch(), _tgju(tgju_key)(), return_exceptions=True)
        if isinstance(price, BaseException):
            raise price
        if isinstance(tgju_price, BaseException):
            return SourcePrice(price)
        return replace(tgju_price, price=price)

    return fetch_with_change


def _ime(key: str, name: str, symbol: str, ticker: str) -> Asset:
    # Iran Mercantile Exchange deposit certificate, price per certificate unit in Toman,
    # shown with the exchange's own daily change
    return Asset(key, name, symbol, "تومان", partial(chartix.fetch_price_toman, ticker), show_day_change=True)


# Each group is a block in the message, separated by a blank line
ASSET_GROUPS: list[list[Asset]] = [
    [
        Asset("btc", "بیت‌کوین", "BTC", "دلار", partial(binance.fetch_price, "BTCUSDT")),
        # USDT trading in Iran is halted 21:00-09:00; Nobitex still returns a stale price then
        Asset(
            "usdt", "تتر", "USDT", "تومان", partial(nobitex.fetch_price_toman, "usdt"),
            trading_hours=(time(9, 0), time(21, 0)),
        ),
        Asset("usd", "دلار", "USD", "تومان", _tgju_toman("price_dollar_rl")),
        # tgju's plain "oil" item is stale
        Asset("brent", "نفت برنت", "Brent", "دلار", _tgju("oil_brent"), decimals=2),
        # gold-api updates every few seconds; tgju's global prices can lag
        Asset(
            "xau", "انس طلا", "XAU", "دلار",
            _with_tgju_day_change(partial(goldapi.fetch_price, "XAU"), "ons"), decimals=2,
        ),
        Asset(
            "xag", "انس نقره", "XAG", "دلار",
            _with_tgju_day_change(partial(goldapi.fetch_price, "XAG"), "silver"), decimals=2,
        ),
        # Copper is COMEX (USD/lb, converted to tons); zinc is tgju's global (LME) price.
        # tgju's plain "copper"/"zinc" items are stale
        Asset(
            "copper", "مس", "Copper", "دلار/تن",
            _with_tgju_day_change(
                partial(goldapi.fetch_price, "HG", multiplier=goldapi.POUNDS_PER_TON),
                "base_global_copper2",  # tgju's COMEX copper
            ),
        ),
        Asset("zinc", "روی", "Zinc", "دلار/تن", _tgju("base_global_zinc")),
    ],
    [
        Asset("gold18", "طلای ۱۸ عیار", "Gold 18K", "تومان", _tgju_toman("geram18")),
        Asset("gold24", "طلای ۲۴ عیار", "Gold 24K", "تومان", _tgju_toman("geram24")),
        # tgju: "sekee" is Emami, "sekeb" is Bahar Azadi
        Asset("coin_emami", "سکه امامی", "Emami Coin", "تومان", _tgju_toman("sekee")),
        Asset("coin_full", "سکه تمام بهار آزادی", "Bahar Coin", "تومان", _tgju_toman("sekeb")),
        Asset("coin_half", "نیم سکه", "Half Coin", "تومان", _tgju_toman("nim")),
        Asset("coin_quarter", "ربع سکه", "Quarter Coin", "تومان", _tgju_toman("rob")),
        Asset("coin_gerami", "سکه گرمی", "Gerami Coin", "تومان", _tgju_toman("gerami")),
        # tgju quotes melted gold (cash price) per mesghal in Rial; shown per gram in Toman
        Asset(
            "gold_melted", "طلای آبشده", "Melted Gold", "تومان",
            partial(tgju.fetch_price, "mesghal", IRAN_MAX_AGE, divisor=10 * GRAMS_PER_MESGHAL),
        ),
    ],
    [
        # tgju also has gold/silver certificates but lags a day
        _ime("ime_gold", "سپرده شمش طلا", "IME Gold", "GOLDBAR"),
        _ime("ime_coin", "سپرده سکه", "IME Coin", "GOLDCOIN"),
        _ime("ime_silver", "سپرده نقره", "IME Silver", "SILVERBAR"),
        _ime("ime_copper", "سپرده مس", "IME Copper", "COPPERCTHD"),
        _ime("ime_zinc", "سپرده روی", "IME Zinc", "ZINCINGOT"),
        _ime("ime_iron", "سپرده سنگ آهن", "IME Iron Ore", "IRONOREPLT"),
    ],
]
