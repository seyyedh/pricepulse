"""Private alerts to the bot's admin (ADMIN_CHAT_ID) when something goes wrong.

Each problem is reported once when it starts and once when it is resolved, not on every
run, so a long outage doesn't flood the admin's chat. The state is kept in
data/alerts.json: {problem key: {"since": Unix time, "alerted": bool}}.
"""

import json
import logging
from datetime import datetime, timedelta
from html import escape

from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import TelegramError

import config
from price_store import DATA_DIR

logger = logging.getLogger(__name__)

STATE_PATH = DATA_DIR / "alerts.json"
# A price must be missing this long before it is reported, so a single failed request
# (tgju is slow and sometimes times out) doesn't trigger an alert
MISSING_GRACE = timedelta(minutes=50)
# No price message for this long means the scheduler (cron-job.org) stopped calling
NO_POST_LIMIT = timedelta(minutes=90)


def _load() -> dict:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except ValueError as e:
        logger.warning("Could not read %s, starting fresh: %s", STATE_PATH, e)
        return {}


def _save(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


async def _send(bot: Bot, text: str) -> bool:
    if not config.ADMIN_CHAT_ID:
        logger.warning("Alert not sent (ADMIN_CHAT_ID is not set): %s", text)
        return False
    try:
        await bot.send_message(config.ADMIN_CHAT_ID, text, parse_mode=ParseMode.HTML)
        return True
    except TelegramError as e:
        logger.error("Could not send alert to admin (did they /start the bot?): %s", e)
        return False


async def _update(bot: Bot, active: dict[str, str], prefix: str, now: datetime, grace: timedelta) -> None:
    """Report problems under prefix: active maps problem key -> description (Persian)."""
    state = _load()
    tracked = {k: v for k, v in state.items() if k.startswith(prefix)}

    for key, description in active.items():
        entry = state.setdefault(key, {"since": now.timestamp(), "alerted": False})
        since = datetime.fromtimestamp(entry["since"], config.TIMEZONE)
        if not entry["alerted"] and now - since >= grace:
            entry["alerted"] = await _send(bot, f"⚠️ {description}\nاز {since:%H:%M} ({since:%m/%d})")

    for key, entry in tracked.items():
        if key not in active:
            if entry["alerted"]:
                await _send(bot, f"✅ برطرف شد: {escape(entry.get('label', key))}")
            del state[key]

    for key in active:
        state[key]["label"] = active[key].split("\n")[0]
    _save(state)


async def check_missing_prices(bot: Bot, failures: dict[str, tuple[str, str]], now: datetime) -> None:
    """failures: asset key -> (asset name, reason) for assets whose price couldn't be fetched."""
    active = {
        f"missing:{key}": f"قیمت «{escape(name)}» در پیام‌ها نیست\n<code>{escape(reason[:300])}</code>"
        for key, (name, reason) in failures.items()
    }
    await _update(bot, active, "missing:", now, MISSING_GRACE)


async def check_post_gap(bot: Bot, last_post: datetime | None, now: datetime) -> None:
    """Reports when no price message went out for NO_POST_LIMIT (called before each post)."""
    active = {}
    if last_post is not None and now - last_post >= NO_POST_LIMIT:
        active["gap:prices"] = (
            f"از ساعت {last_post:%H:%M} هیچ پیام قیمتی ارسال نشده بود\n"
            "احتمالاً cron-job.org غیرفعال شده؛ وضعیت cronjob ها را بررسی کنید"
        )
    await _update(bot, active, "gap:", now, timedelta(0))


async def report_failure(bot: Bot, kind: str, problem: str | None, now: datetime) -> None:
    """Reports a failed post of kind ("prices"/"summary"); problem=None means it succeeded."""
    active = {f"failed:{kind}": problem} if problem else {}
    await _update(bot, active, f"failed:{kind}", now, timedelta(0))
