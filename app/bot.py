import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from dotenv import load_dotenv

from db.migrations import run_migrations
from handlers import get_routers
from storage import ensure_container_exists

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("ERROR: Bot token not found! Check your .env file")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
dp.include_routers(*get_routers())


async def main():
    logging.basicConfig(level=logging.INFO)

    ensure_container_exists()
    await asyncio.to_thread(run_migrations)

    logging.info("Bot started!")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
