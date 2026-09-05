import asyncio
import io
import logging
import os
from azure.core.exceptions import ResourceExistsError
from azure.storage.blob import BlobServiceClient
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
AZURE_STORAGE_CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
AZURE_CONTAINER_NAME = os.getenv("AZURE_CONTAINER_NAME", "receipts")

if not BOT_TOKEN:
    raise ValueError("ОШИБКА: Токен бота не найден! Проверь файл .env")

if not AZURE_STORAGE_CONNECTION_STRING:
    raise ValueError("ОШИБКА: AZURE_STORAGE_CONNECTION_STRING не найден в .env!")

blob_service_client = BlobServiceClient.from_connection_string(
    AZURE_STORAGE_CONNECTION_STRING
)

def ensure_container_exists():
    """Проверяем существование контейнера в Azure Blob Storage, если нет — создаем."""
    try:
        container_client = blob_service_client.get_container_client(
            AZURE_CONTAINER_NAME
        )
        container_client.create_container()
        logging.info(f"Контейнер '{AZURE_CONTAINER_NAME}' успешно создан.")
    except ResourceExistsError:
        logging.info(f"Контейнер '{AZURE_CONTAINER_NAME}' уже существует.")
    except Exception as e:
        logging.error(f"Ошибка при создании контейнера: {e}")

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
    await message.answer("📥 Скачиваю фото из Telegram...")

    photo = message.photo[-1]
    file_info = await bot.get_file(photo.file_id)

    file_bytes = io.BytesIO()
    await bot.download_file(file_info.file_path, destination=file_bytes)
    file_bytes.seek(0)

    blob_name = f"{message.from_user.id}/{photo.file_id}.jpg"

    try:
        blob_client = blob_service_client.get_blob_client(
            container=AZURE_CONTAINER_NAME, blob=blob_name
        )
        blob_client.upload_blob(file_bytes, overwrite=True)

        await message.answer(
            f"✅ Фото успешно загружено в Azure Blob Storage!\n"
            f"• Контейнер: `{AZURE_CONTAINER_NAME}`\n"
            f"• Путь: `{blob_name}`",
            parse_mode="Markdown",
        )
    except Exception as e:
        logging.error(f"Ошибка загрузки в Azure Blob Storage: {e}")
        await message.answer("❌ Не удалось сохранить фото в Azure Blob Storage.")


async def main():
    logging.basicConfig(level=logging.INFO)

    # Проверяем наличие контейнера в Azure
    ensure_container_exists()

    logging.info("Бот запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())