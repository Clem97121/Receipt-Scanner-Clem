import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from dotenv import load_dotenv

from db.migrations import run_migrations
from fsm_storage import DatabaseStorage
from handlers import get_routers

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("ERROR: Bot token not found! Check your .env file")

# FSM state lives in the DB: on Lambda every update may be handled by a fresh process
dp = Dispatcher(storage=DatabaseStorage())
dp.include_routers(*get_routers())


def create_bot() -> Bot:
    """Creates a Bot whose HTTP session belongs to the current event loop; close bot.session when done."""
    return Bot(token=BOT_TOKEN)


bot = create_bot()


async def main():
    """Local development only: long polling. Production runs on Lambda via a webhook (lambda_handlers.webhook).

    Telegram refuses polling while a webhook is set, so use a separate test bot token locally.
    """
    logging.basicConfig(level=logging.INFO)

    await asyncio.to_thread(run_migrations)

    logging.info("Bot started!")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
