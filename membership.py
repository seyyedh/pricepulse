"""Channel membership check: only users who joined the channel can use the bot."""

import functools
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatMemberStatus
from telegram.error import BadRequest, Forbidden
from telegram.ext import ContextTypes

import config

logger = logging.getLogger(__name__)

CHECK_MEMBERSHIP_CALLBACK = "check_membership"

_MEMBER_STATUSES = {
    ChatMemberStatus.OWNER,
    ChatMemberStatus.ADMINISTRATOR,
    ChatMemberStatus.MEMBER,
}

NOT_MEMBER_TEXT = (
    "🔒 برای استفاده از ربات ابتدا باید عضو کانال ما شوید.\n\n"
    "بعد از عضویت، روی دکمه «✅ عضو شدم» بزنید."
)


async def is_member(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        member = await context.bot.get_chat_member(config.CHANNEL_ID, user_id)
    except BadRequest as e:
        # "User not found" / "Participant_id_invalid": user has never joined
        logger.info("Membership check failed for %s: %s", user_id, e)
        return False
    except Forbidden:
        logger.error("Bot has no access to %s; make it an admin of the channel", config.CHANNEL_ID)
        return False

    if member.status in _MEMBER_STATUSES:
        return True
    # A restricted user may still be in the channel
    return member.status == ChatMemberStatus.RESTRICTED and getattr(member, "is_member", False)


def join_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📢 عضویت در کانال", url=config.CHANNEL_LINK)],
            [InlineKeyboardButton("✅ عضو شدم", callback_data=CHECK_MEMBERSHIP_CALLBACK)],
        ]
    )


def require_membership(handler):
    """Decorator for handlers: blocks users who are not members of the channel."""

    @functools.wraps(handler)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        if user is None:
            return None
        if await is_member(user.id, context):
            return await handler(update, context, *args, **kwargs)

        if update.callback_query:
            await update.callback_query.answer("ابتدا عضو کانال شوید.", show_alert=True)
        elif update.effective_message:
            await update.effective_message.reply_text(NOT_MEMBER_TEXT, reply_markup=join_keyboard())
        return None

    return wrapper
