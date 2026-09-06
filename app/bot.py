import asyncio
import io
import logging
import os
from azure.core.exceptions import ResourceExistsError
from azure.storage.blob import BlobServiceClient
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from tasks import process_receipt_task

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
AZURE_STORAGE_CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
AZURE_CONTAINER_NAME = os.getenv("AZURE_CONTAINER_NAME", "receipts")

if not BOT_TOKEN:
    raise ValueError("ERROR: Bot token not found! Check your .env file")

if not AZURE_STORAGE_CONNECTION_STRING:
    raise ValueError("ERROR: AZURE_STORAGE_CONNECTION_STRING not found in .env!")

blob_service_client = BlobServiceClient.from_connection_string(
    AZURE_STORAGE_CONNECTION_STRING
)


def ensure_container_exists():
    """Ensure Azure Blob Storage container exists, create if not."""
    try:
        container_client = blob_service_client.get_container_client(
            AZURE_CONTAINER_NAME
        )
        container_client.create_container()
        logging.info(f"Container '{AZURE_CONTAINER_NAME}' created successfully.")
    except ResourceExistsError:
        logging.info(f"Container '{AZURE_CONTAINER_NAME}' already exists.")
    except Exception as e:
        logging.error(f"Error creating container: {e}")


bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 Hi! I'm an expense tracking bot.\n"
        "Send me a photo of a receipt, and I'll process it!"
    )


@dp.message(F.photo)
async def handle_photo(message: types.Message):
    await message.answer("📥 Downloading photo from Telegram...")

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

        process_receipt_task.delay(blob_name, message.chat.id)

        await message.answer(
            f"✅ Photo uploaded to Azure Blob Storage successfully!\n"
            f"• Container: `{AZURE_CONTAINER_NAME}`\n"
            f"• Path: `{blob_name}`",
            parse_mode="Markdown",
        )
    except Exception as e:
        logging.error(f"Error uploading to Azure Blob Storage: {e}")
        await message.answer("❌ Failed to save photo to Azure Blob Storage.")


async def main():
    logging.basicConfig(level=logging.INFO)

    ensure_container_exists()

    logging.info("Bot started!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())