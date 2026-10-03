"""Builds the messages posted to the channel / sent in the bot.

Messages are HTML; send them with parse_mode=ParseMode.HTML.
"""

from dataclasses import dataclass
from datetime import datetime
from html import escape

import jdatetime

import config
from assets import Asset

UP = "🟢"
DOWN = "🔴"
UNCHANGED = "⚪️"
CHANNEL_EMOJI = "📊"
SUMMARY_TITLE = "📋 خلاصه تغییرات ۲۴ ساعت گذشته"

_PERSIAN_DIGITS = str.maketrans("0123456789.", "۰۱۲۳۴۵۶۷۸۹٫")


@dataclass
class Quote:
    asset: Asset
    price: float
    prev_price: float | None = None  # comparison base; None if unknown


def to_persian_digits(text: str) -> str:
    return text.translate(_PERSIAN_DIGITS)


def trend_emoji(quote: Quote) -> str:
    # Compare at display precision so a change too small to see shows as unchanged
    if quote.prev_price is None:
        return UNCHANGED
    decimals = quote.asset.decimals
    price = round(quote.price, decimals)
    prev = round(quote.prev_price, decimals)
    if price == prev:
        return UNCHANGED
    return UP if price > prev else DOWN


def format_number(value: float, decimals: int = 0) -> str:
    """65054.3 -> 65,054 (decimals=0); 31.40 -> 31.4 (decimals=2)."""
    text = f"{value:,.{decimals}f}"
    if decimals:
        text = text.rstrip("0").rstrip(".")
    return text


def format_quote(quote: Quote) -> str:
    asset = quote.asset
    price = to_persian_digits(format_number(quote.price, asset.decimals))
    return f"{trend_emoji(quote)} {escape(asset.name)}: <b>{price}</b> {escape(asset.unit)}"


def format_summary_quote(quote: Quote) -> str:
    """🟢 BTC: $84,868 (↑0.27%)"""
    asset = quote.asset
    number = format_number(quote.price, asset.decimals)
    price = f"${number}" if asset.is_usd else f"{number} T"
    line = f"{escape(asset.symbol)}: {price}"

    if not quote.prev_price:
        return f"{UNCHANGED} {line}"
    change = round((quote.price - quote.prev_price) / quote.prev_price * 100, 2)
    if change > 0:
        return f"{UP} {line} (↑{change:.2f}%)"
    if change < 0:
        return f"{DOWN} {line} (↓{-change:.2f}%)"
    return f"{UNCHANGED} {line} (0.00%)"


def format_timestamp(now: datetime) -> str:
    j = jdatetime.datetime.fromgregorian(datetime=now)
    return to_persian_digits(f"📅 {j.strftime('%Y/%m/%d')} ⏰ {j.strftime('%H:%M')}")


def _footer(now: datetime | None) -> list[str]:
    now = now or datetime.now(config.TIMEZONE)
    return [
        "",
        format_timestamp(now),
        "",
        f"{CHANNEL_EMOJI} {escape(config.CHANNEL_TITLE)}",
        escape(config.CHANNEL_HANDLE),
    ]


def _blocks(groups: list[list[Quote]], format_line) -> str:
    """Each group of quotes is a block; blocks are separated by a blank line."""
    return "\n\n".join("\n".join(format_line(q) for q in group) for group in groups)


def format_price_message(groups: list[list[Quote]], now: datetime | None = None) -> str:
    return "\n".join([_blocks(groups, format_quote), *_footer(now)])


def format_summary_message(groups: list[list[Quote]], now: datetime | None = None) -> str:
    return "\n".join([SUMMARY_TITLE, "", _blocks(groups, format_summary_quote), *_footer(now)])
