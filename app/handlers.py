# app/handlers.py
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command

from db.database import AsyncSessionLocal
from db.crud import get_monthly_stats, delete_receipt_by_id
from keyboards import get_main_reply_keyboard

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message):
    """Приветствие и выдача главной клавиатуры."""
    await message.answer(
        "Привет! Отправь мне фото чека, и я распознаю его детали.\n"
        "Нажми «📊 Траты за месяц», чтобы посмотреть общую статистику.",
        reply_markup=get_main_reply_keyboard()
    )


@router.message(F.text == "📊 Траты за месяц")
@router.message(Command("stats"))
async def show_stats_handler(message: Message):
    """Обработчик запроса статистики за текущий месяц."""
    async with AsyncSessionLocal() as session:
        total, categories = await get_monthly_stats(session, message.from_user.id)

    if total == 0:
        await message.answer("📊 В этом месяце пока нет сохраненных трат.")
        return

    cat_text = "\n".join([f"• *{cat or 'Разное'}*: `{amount:.2f}`" for cat, amount in categories])
    
    text = (
        f"📊 *Статистика трат за текущий месяц*\n\n"
        f"💰 *Всего потрачено:* `{total:.2f}`\n\n"
        f"🏷 *По категориям:*\n{cat_text}"
    )
    await message.answer(text, parse_mode="Markdown")


@router.callback_query(F.data.startswith("delete_receipt:"))
async def delete_receipt_handler(callback: CallbackQuery):
    """Обработчик нажатия на инлайн-кнопку удаления чека."""
    receipt_id = int(callback.data.split(":")[1])
    
    async with AsyncSessionLocal() as session:
        success = await delete_receipt_by_id(session, receipt_id, callback.from_user.id)

    if success:
        await callback.answer("Чек успешно удален!")
        await callback.message.edit_text("🗑 *Этот чек был удален из системы.*", parse_mode="Markdown")
    else:
        await callback.answer("Не удалось найти чек или нет прав на удаление.", show_alert=True)