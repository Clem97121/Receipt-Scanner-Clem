import asyncio
import io
import logging
import os
import cv2
import numpy as np
from azure.storage.blob import BlobServiceClient
from celery import Celery
from dotenv import load_dotenv
from aiogram import Bot
from PIL import Image
import pytesseract

load_dotenv()

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
BOT_TOKEN = os.getenv("BOT_TOKEN")
AZURE_STORAGE_CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
AZURE_CONTAINER_NAME = os.getenv("AZURE_CONTAINER_NAME", "receipts")

celery_app = Celery("receipt_tasks", broker=REDIS_URL, backend=REDIS_URL)

blob_service_client = BlobServiceClient.from_connection_string(
    AZURE_STORAGE_CONNECTION_STRING
)


async def send_telegram_notification(chat_id: int, text: str):
    bot = Bot(token=BOT_TOKEN)
    try:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
    finally:
        await bot.session.close()


def preprocess_image(image_bytes: io.BytesIO) -> Image.Image:
    """Мягкая предобработка чеков:

    1. Перевод в оттенки серого.
    2. Увеличение локального контраста (CLAHE).
    3. Нормализация размера (Tesseract лучше работает при высоте букв ~30px).
    """
    file_bytes = np.asarray(bytearray(image_bytes.read()), dtype=np.uint8)
    img = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)

    # 1. Переводим в оттенки серого
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # 2. Повышаем контрастность текста через CLAHE без бинаризации
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)

    # 3. Увеличиваем изображение, если оно слишком маленькое (помогает Tesseract)
    height, width = enhanced.shape
    if height < 1000 or width < 1000:
        enhanced = cv2.resize(
            enhanced, None, fx=1.5, fy=1.5, interpolation=cv2.INTER_CUBIC
        )

    return Image.fromarray(enhanced)


def extract_totals_simple(text: str) -> str:
    """Простая регулярка для поиска итоговых сумм в тексте чека."""
    lines = text.split("\n")
    keywords = ["total", "сумма", "итого", "kc", "czk", "celkem", "suma", "rub", "usd", "eur", "součet"]
    matched_lines = []

    for line in lines:
        if any(keyword in line.lower() for keyword in keywords):
            matched_lines.append(line.strip())

    if matched_lines:
        return "\n".join([f"• `{line}`" for line in matched_lines[:5]])
    return "Сумма не найдена явно, посмотри сырой текст ниже."


@celery_app.task
def process_receipt_task(blob_name: str, chat_id: int):
    logging.info(f"[Celery Worker] Начало OCR для: {blob_name}")

    try:
        # 1. Скачиваем файл из Azure Blob Storage в память
        blob_client = blob_service_client.get_blob_client(
            container=AZURE_CONTAINER_NAME, blob=blob_name
        )
        download_stream = blob_client.download_blob()
        image_bytes = io.BytesIO(download_stream.readall())

        # 2. Применяем предобработку OpenCV
        processed_image = preprocess_image(image_bytes)

        # 3. Запускаем Tesseract на очищенном изображении
        raw_text = pytesseract.image_to_string(processed_image, lang="ces+eng+rus")

        # 4. Ищем возможные суммы
        totals_summary = extract_totals_simple(raw_text)

        response_text = (
            f"🧾 *Результат обработки чека (с OpenCV):*\n\n"
            f"📌 *Найденные суммы/строки:*\n{totals_summary}\n\n"
            f"📝 *Очищенный сырой текст OCR:*\n```\n{raw_text[:500]}\n```"
        )

    except Exception as e:
        logging.error(f"Ошибка при обработке OCR: {e}")
        response_text = f"❌ Произошла ошибка при распознавании чека: `{e}`"

    # 5. Отправляем результат пользователю
    asyncio.run(send_telegram_notification(chat_id, response_text))
    logging.info(f"[Celery Worker] OCR завершен и отправлен в чат {chat_id}")
    return {"status": "completed", "blob_name": blob_name}