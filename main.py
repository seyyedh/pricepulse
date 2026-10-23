import argparse
import asyncio
import logging
import sys
from datetime import datetime, time, timedelta

from telegram import Bot, Message, Update
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest, TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

import config
from formatter import format_price_message, format_summary_message
from bubbles import get_bubbles
from price_service import get_quotes, get_summary_quotes, mark_posted, mark_summary_posted, prices_of
from price_store import DATA_DIR, PriceStore
from membership import (
    CHECK_MEMBERSHIP_CALLBACK,
    NOT_MEMBER_TEXT,
    is_member,
    join_keyboard,
    require_membership,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

DAILY_SUMMARY_TIME = time(23, 55, tzinfo=config.TIMEZONE)
POST_INTERVAL = timedelta(minutes=30)
# Tehran hours [start, end) with a new price message every half hour; outside them a new
# message only on the hour, and the half hour edits it
BUSY_HOURS = (9, 18)
# A half-hour run only edits a message posted at most this long ago
MAX_EDIT_AGE = timedelta(minutes=50)
WEEKLY_SUMMARY_WEEKDAY = 4  # Friday (datetime.weekday(): Monday is 0)

# One-shot mode can be triggered by more than one scheduler (cron-job.org, with GitHub's own
# cron as a backup); a post made more recently than this is not repeated
MIN_REPOST_GAP = {"prices": timedelta(minutes=20), "summary": timedelta(hours=12)}
# Backup runs fire at random times; they only fill gaps the main scheduler left, so they
# don't take a slot just before the main scheduler's on-time post (which would then be skipped)
MIN_REPOST_GAP_BACKUP = {"prices": timedelta(minutes=45), "summary": timedelta(hours=12)}

WELCOME_TEXT ="👋 خوش آمدید! عضویت شما تأیید شد و می‌توانید از ربات استفاده کنید."


@require_membership
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(WELCOME_TEXT)


@require_membership
async def prices(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Some sources take several seconds; show "typing..." meanwhile
    await update.effective_chat.send_action(ChatAction.TYPING)
    quotes = await get_quotes()
    if not quotes:
        await update.effective_message.reply_text("⚠️ دریافت قیمت‌ها با خطا مواجه شد، کمی بعد دوباره تلاش کنید.")
        return
    await update.effective_message.reply_text(await _price_message(quotes), parse_mode=ParseMode.HTML)


async def check_membership_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if await is_member(query.from_user.id, context):
        await query.answer("عضویت تأیید شد ✅")
        await query.edit_message_text(WELCOME_TEXT)
    else:
        await query.answer("هنوز عضو کانال نشده‌اید ❌", show_alert=True)
        # Keep the join message as is so the user can try again
        if query.message and query.message.text != NOT_MEMBER_TEXT:
            await query.edit_message_text(NOT_MEMBER_TEXT, reply_markup=join_keyboard())


async def _price_message(quotes) -> str:
    """The price message, with the IME certificates' bubbles."""
    return format_price_message(quotes, bubbles=await get_bubbles(prices_of(quotes)))


async def _send_to_channel(bot: Bot, text: str) -> Message | None:
    try:
        return await bot.send_message(config.CHANNEL_ID, text, parse_mode=ParseMode.HTML)
    except TelegramError as e:
        logger.error("Could not post to %s (is the bot an admin with 'Post Messages'?): %s", config.CHANNEL_ID, e)
        return None


async def _pin_summary(bot: Bot, message: Message) -> None:
    """Pins the daily summary and unpins the previous one, so only the latest stays pinned.

    A failure is only logged: the summary itself was posted.
    """
    pinned = PriceStore(DATA_DIR / "pinned.json")  # "summary" -> message id of the pinned summary
    try:
        await bot.pin_chat_message(config.CHANNEL_ID, message.message_id, disable_notification=True)
    except TelegramError as e:
        logger.error("Could not pin the summary (does the bot have 'Edit Messages' in the channel?): %s", e)
        return
    # Telegram posts a "pinned a message" service message right after; channel message ids are
    # sequential, so it is the next id. (Without receiving updates the bot can't see it, so this
    # assumes nobody posted in the second between the summary and the pin.)
    try:
        await bot.delete_message(config.CHANNEL_ID, message.message_id + 1)
    except TelegramError as e:
        logger.warning("Could not delete the pin notice (does the bot have 'Delete Messages'?): %s", e)
    previous = pinned.get("summary")
    if previous is not None:
        try:
            await bot.unpin_chat_message(config.CHANNEL_ID, int(previous))
        except TelegramError as e:
            logger.warning("Could not unpin the previous summary %d: %s", previous, e)
    pinned.update({"summary": message.message_id})


def _edits_previous(now: datetime) -> bool:
    """Whether this half-hour slot updates the previous price message instead of posting one.

    During busy market hours (BUSY_HOURS) a new message goes out every half hour; the rest of
    the day only on the hour, and the half hour edits that hour's message.
    """
    start, end = BUSY_HOURS
    return now.minute >= 30 and not start <= now.hour < end


async def _edit_in_channel(bot: Bot, message_id: int, text: str) -> bool:
    try:
        await bot.edit_message_text(text, config.CHANNEL_ID, message_id, parse_mode=ParseMode.HTML)
        return True
    except BadRequest as e:
        if "not modified" in str(e).lower():  # same text as before: nothing to update
            return True
        logger.warning("Could not edit price message %d, posting a new one: %s", message_id, e)
    except TelegramError as e:
        logger.warning("Could not edit price message %d, posting a new one: %s", message_id, e)
    return False


async def post_prices(bot: Bot, now: datetime | None = None) -> bool:
    now = now or datetime.now(config.TIMEZONE)
    quotes = await get_quotes()
    if not quotes:
        logger.error("No prices could be fetched; nothing posted to %s", config.CHANNEL_ID)
        return False
    text = await _price_message(quotes)

    # message_ids: "prices" -> id of the last new price message, "prices_at" -> its Unix time
    message_ids = PriceStore(DATA_DIR / "message_ids.json")
    last_id, last_at = message_ids.get("prices"), message_ids.get("prices_at")
    # Only edit the message of this hour: if runs were missed, post a fresh one instead
    recent = last_at is not None and now.timestamp() - last_at < MAX_EDIT_AGE.total_seconds()
    if _edits_previous(now) and last_id is not None and recent:
        if await _edit_in_channel(bot, int(last_id), text):
            mark_posted(quotes)
            logger.info("Updated price message %d in %s", last_id, config.CHANNEL_ID)
            return True

    message = await _send_to_channel(bot, text)
    if message is None:
        return False
    message_ids.update({"prices": message.message_id, "prices_at": now.timestamp()})
    mark_posted(quotes)
    logger.info("Posted prices to %s", config.CHANNEL_ID)
    return True


async def post_summary(bot: Bot, now: datetime | None = None) -> bool:
    """Posts (and pins) the daily summary; on Fridays the weekly summary follows it."""
    now = now or datetime.now(config.TIMEZONE)
    quotes = await get_summary_quotes()
    if not quotes:
        logger.error("No prices could be fetched; daily summary not posted to %s", config.CHANNEL_ID)
        return False
    message = await _send_to_channel(bot, format_summary_message(quotes))
    if message is None:
        return False
    mark_summary_posted(quotes)
    logger.info("Posted daily summary to %s", config.CHANNEL_ID)
    await _pin_summary(bot, message)

    if now.weekday() == WEEKLY_SUMMARY_WEEKDAY:
        weekly = await get_summary_quotes(weekly=True)
        if weekly and await _send_to_channel(bot, format_summary_message(weekly, weekly=True)):
            mark_summary_posted(weekly, weekly=True)
            logger.info("Posted weekly summary to %s", config.CHANNEL_ID)
    return True


POSTERS = {"prices": post_prices, "summary": post_summary}


async def post_prices_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    await post_prices(context.bot)


async def post_summary_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    await post_summary(context.bot)


async def post_once(kind: str, backup: bool = False) -> bool:
    """One-shot mode for external schedulers (e.g. GitHub Actions): post and exit.

    Skips (successfully) if the same kind was posted less than MIN_REPOST_GAP ago
    (MIN_REPOST_GAP_BACKUP for a backup scheduler's run).
    """
    post_times = PriceStore(DATA_DIR / "post_times.json")  # kind -> Unix time of last post
    now = datetime.now(config.TIMEZONE)
    last = post_times.get(kind)
    min_gap = (MIN_REPOST_GAP_BACKUP if backup else MIN_REPOST_GAP)[kind]
    if last is not None and now - datetime.fromtimestamp(last, config.TIMEZONE) < min_gap:
        logger.info("Skipping %s: already posted at %s", kind, datetime.fromtimestamp(last, config.TIMEZONE))
        return True

    async with Bot(config.BOT_TOKEN) as bot:
        posted = await POSTERS[kind](bot)
    if posted:
        post_times.update({kind: now.timestamp()})
    return posted


def run_bot() -> None:
    app = Application.builder().token(config.BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("prices", prices))
    app.add_handler(CallbackQueryHandler(check_membership_callback, pattern=f"^{CHECK_MEMBERSHIP_CALLBACK}$"))

    # The run time is fixed now, but the scheduler only starts after connecting to Telegram;
    # without misfire_grace_time=None APScheduler silently skips a job more than 1s late.
    app.job_queue.run_once(
        post_prices_job, when=0, name="startup_post",
        job_kwargs={"misfire_grace_time": None},
    )
    # Then on every hour and half hour
    now = datetime.now(config.TIMEZONE)
    next_slot = now.replace(minute=0, second=0, microsecond=0) + POST_INTERVAL * (now.minute // 30 + 1)
    app.job_queue.run_repeating(
        post_prices_job, interval=POST_INTERVAL, first=next_slot, name="prices",
        job_kwargs={"misfire_grace_time": 300},
    )
    app.job_queue.run_daily(
        post_summary_job, time=DAILY_SUMMARY_TIME, name="daily_summary",
        # Still run if the scheduler gets to it a bit late (APScheduler's default grace is 1s)
        job_kwargs={"misfire_grace_time": 300},
    )

    logger.info("Bot started, required channel: %s", config.CHANNEL_ID)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


def main() -> None:
    parser = argparse.ArgumentParser(description="Price Pulse Telegram bot")
    parser.add_argument(
        "--post", choices=POSTERS,
        help="post once to the channel and exit, instead of running the bot",
    )
    parser.add_argument(
        "--backup", action="store_true",
        help="with --post: run from a backup scheduler; only post if the main one missed a slot",
    )
    args = parser.parse_args()

    if args.post:
        sys.exit(0 if asyncio.run(post_once(args.post, args.backup)) else 1)
    run_bot()


if __name__ == "__main__":
    main()
