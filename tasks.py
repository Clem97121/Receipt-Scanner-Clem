import os
import time
import logging
from celery import Celery
from dotenv import load_dotenv

load_dotenv()

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

celery_app = Celery("receipt_tasks", broker=REDIS_URL, backend=REDIS_URL)


@celery_app.task
def process_receipt_task(blob_name: str, chat_id: int):
    """Фоновая задача обработки чека (тут скоро будет OCR)."""
    logging.info(f"[Celery Worker] Взял в работу файл: {blob_name} для chat_id: {chat_id}")

    # Имитируем тяжелое скачивание и распознавание OCR (задержка 3 секунды)
    time.sleep(3)

    logging.info(f"[Celery Worker] Успешно обработал файл: {blob_name}")
    
    # В будущем тут будет отправка распознанной суммы пользователю в Telegram
    return {"status": "completed", "blob_name": blob_name, "chat_id": chat_id}