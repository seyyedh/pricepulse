import os
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Environment variable {name} is not set (see .env.example)")
    return value


BOT_TOKEN = _require("BOT_TOKEN")

# Either "@channel_username" (public channel) or a numeric id like "-1001234567890" (private channel)
CHANNEL_ID = _require("CHANNEL_ID")

# Link shown on the "join" button. For public channels it is derived from the username;
# for private channels an invite link must be provided.
CHANNEL_LINK = os.getenv("CHANNEL_LINK", "").strip()
if not CHANNEL_LINK:
    if CHANNEL_ID.startswith("@"):
        CHANNEL_LINK = f"https://t.me/{CHANNEL_ID[1:]}"
    else:
        raise RuntimeError("CHANNEL_LINK must be set when CHANNEL_ID is a numeric id")

# Shown at the bottom of every price message
CHANNEL_TITLE = os.getenv("CHANNEL_TITLE", "Price Pulse").strip()
CHANNEL_HANDLE = CHANNEL_ID if CHANNEL_ID.startswith("@") else CHANNEL_LINK

TIMEZONE = ZoneInfo(os.getenv("TIMEZONE", "Asia/Tehran"))
