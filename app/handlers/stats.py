import calendar
import html
from datetime import datetime

from aiogram import F, Router, types
from aiogram.filters import Command

from db.crud import get_monthly_stats
from db.database import AsyncSessionLocal
from keyboards import BTN_MONTHLY_EXPENSES, get_stats_keyboard

router = Router(name="stats")


async def send_or_edit_stats(target, user_id: int, year: int, month: int, is_callback: bool = False, callback_query = None):
    """Helper to fetch and display monthly stats with pagination keyboard."""
    async with AsyncSessionLocal() as session:
        total, categories = await get_monthly_stats(session, user_id, year, month)

    month_str = f"{calendar.month_name[month]} {year}"

    if total == 0:
        text = f"📊 <b>Expense Statistics for {month_str}</b>\n\nNo saved expenses found for this period."
    else:
        cat_text = "\n".join([f"• <b>{html.escape(cat or 'Uncategorized')}</b>: <code>{amount:.2f}</code>" for cat, amount in categories])
        text = (
            f"📊 <b>Expense Statistics for {month_str}</b>\n\n"
            f"💰 <b>Total Spent:</b> <code>{total:.2f}</code>\n\n"
            f"🏷 <b>By Category:</b>\n{cat_text}"
        )

    keyboard = get_stats_keyboard(year, month)

    if is_callback:
        try:
            await callback_query.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
        except Exception:
            pass
        await callback_query.answer()
    else:
        await target.answer(text, parse_mode="HTML", reply_markup=keyboard)


@router.message(F.text == BTN_MONTHLY_EXPENSES)
@router.message(Command("stats"))
async def show_stats_handler(message: types.Message):
    """Handler for the '📊 Monthly Expenses' button or /stats command."""
    now = datetime.now()
    await send_or_edit_stats(message, message.from_user.id, now.year, now.month, is_callback=False)


@router.callback_query(F.data.startswith("stats:"))
async def stats_pagination_handler(callback: types.CallbackQuery):
    """Handler for switching months in statistics."""
    _, year_str, month_str = callback.data.split(":")
    year, month = int(year_str), int(month_str)
    await send_or_edit_stats(callback.message, callback.from_user.id, year, month, is_callback=True, callback_query=callback)


@router.callback_query(F.data == "ignore_stats_title")
async def ignore_title_handler(callback: types.CallbackQuery):
    """Stub handler for middle title button."""
    await callback.answer()
