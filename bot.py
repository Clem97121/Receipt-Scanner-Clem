import asyncio
import logging
import os
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("ОШИБКА: Токен бота не найден! Проверь файл .env")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 Привет! Я бот для учета трат.\n"
        "Отправь мне фото чека, и я распознаю сумму!"
    )


@dp.message(F.photo)
async def handle_photo(message: types.Message):
    photo = message.photo[-1]

    await message.answer(
        f"📸 Чек получен!\n"
        f"• File ID: `{photo.file_id}`\n"
        f"• Размер: {photo.width}x{photo.height}\n\n"
        f"⚙️ Скоро здесь будет передача фото в MinIO и Celery...",
        parse_mode="Markdown"
    )


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    )
    logging.info("Бот запущен!")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())