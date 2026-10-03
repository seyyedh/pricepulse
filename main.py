import argparse
import asyncio
import logging
import sys
from datetime import time

from telegram import Bot, Update
from telegram.constants import ChatAction, ParseMode
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

import config
from formatter import format_price_message, format_summary_message
from price_service import get_quotes, get_summary_quotes, mark_posted, mark_summary_posted
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
    await update.effective_message.reply_text(format_price_message(quotes), parse_mode=ParseMode.HTML)


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


async def _send_to_channel(bot: Bot, text: str) -> bool:
    try:
        await bot.send_message(config.CHANNEL_ID, text, parse_mode=ParseMode.HTML)
        return True
    except TelegramError as e:
        logger.error("Could not post to %s (is the bot an admin with 'Post Messages'?): %s", config.CHANNEL_ID, e)
        return False


async def post_prices(bot: Bot) -> bool:
    quotes = await get_quotes()
    if not quotes:
        logger.error("No prices could be fetched; nothing posted to %s", config.CHANNEL_ID)
        return False
    if not await _send_to_channel(bot, format_price_message(quotes)):
        return False
    mark_posted(quotes)
    logger.info("Posted prices to %s", config.CHANNEL_ID)
    return True


async def post_summary(bot: Bot) -> bool:
    quotes = await get_summary_quotes()
    if not quotes:
        logger.error("No prices could be fetched; daily summary not posted to %s", config.CHANNEL_ID)
        return False
    if not await _send_to_channel(bot, format_summary_message(quotes)):
        return False
    mark_summary_posted(quotes)
    logger.info("Posted daily summary to %s", config.CHANNEL_ID)
    return True


POSTERS = {"prices": post_prices, "summary": post_summary}


async def post_prices_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    await post_prices(context.bot)


async def post_summary_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    await post_summary(context.bot)


async def post_once(kind: str) -> bool:
    """One-shot mode for external schedulers (e.g. GitHub Actions): post and exit."""
    async with Bot(config.BOT_TOKEN) as bot:
        return await POSTERS[kind](bot)


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
    args = parser.parse_args()

    if args.post:
        sys.exit(0 if asyncio.run(post_once(args.post)) else 1)
    run_bot()


if __name__ == "__main__":
    main()
