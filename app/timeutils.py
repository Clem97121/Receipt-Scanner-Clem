import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

# Timezone used for "today" and "this month"; the servers run in UTC
LOCAL_TIMEZONE = ZoneInfo(os.getenv("BOT_TIMEZONE", "Europe/Prague"))


def local_now() -> datetime:
    """Returns the current time in the bot's local timezone."""
    return datetime.now(LOCAL_TIMEZONE)


def local_today() -> date:
    """Returns today's date in the bot's local timezone."""
    return local_now().date()
