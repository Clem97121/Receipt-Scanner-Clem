from decimal import Decimal

from aiogram.methods import SendMessage
from sqlalchemy import select

from conftest import OWNER_ID, STRANGER_ID, texts
from db.database import AsyncSessionLocal
from db.models import Receipt
from timeutils import local_today


async def manual_receipts() -> list[Receipt]:
    async with AsyncSessionLocal() as session:
        from sqlalchemy.orm import selectinload
        result = await session.execute(
            select(Receipt).options(selectinload(Receipt.items)).where(Receipt.blob_name.is_(None))
        )
        return list(result.scalars().all())


async def add_expense(tg, user_id=OWNER_ID, amount="250", category="Transport", description="taxi") -> list:
    await tg.send(user_id, "➕ Add expense")
    await tg.send(user_id, amount)
    await tg.click(user_id, f"manual_cat:{category}")
    if description is None:
        return await tg.click(user_id, "manual_skip_description")
    return await tg.send(user_id, description)


async def test_full_flow_saves_expense_and_shows_card(tg):
    calls = await add_expense(tg)
    assert await tg.state(OWNER_ID) is None

    [receipt] = await manual_receipts()
    assert receipt.user_id == OWNER_ID
    assert receipt.total_amount == Decimal("250.00")
    assert receipt.store_name == "taxi"
    assert receipt.date == local_today()
    assert [(i.name, i.category, i.total_price) for i in receipt.items] == [("taxi", "Transport", Decimal("250.00"))]

    card = [c for c in calls if isinstance(c, SendMessage)][-1]
    assert "Expense saved" in card.text and "Manual expense:</b> taxi" in card.text
    assert card.reply_markup.inline_keyboard[0][0].callback_data == f"edit_receipt:{receipt.id}"


async def test_description_can_be_skipped(tg):
    await add_expense(tg, amount="12,5", category="Cafe & Dining", description=None)
    [receipt] = await manual_receipts()
    assert receipt.store_name is None
    assert receipt.total_amount == Decimal("12.50")
    assert receipt.items[0].name == "Cafe & Dining"


async def test_invalid_amounts_keep_asking(tg):
    await tg.send(OWNER_ID, "➕ Add expense")
    for bad in ["abc", "0", "-5", "nan", "1e30"]:
        sent = texts(await tg.send(OWNER_ID, bad))
        assert any("Invalid amount" in t for t in sent)
    assert await tg.state(OWNER_ID) is not None
    assert await manual_receipts() == []


async def test_unknown_category_is_rejected(tg):
    await tg.send(OWNER_ID, "➕ Add expense")
    await tg.send(OWNER_ID, "100")
    await tg.click(OWNER_ID, "manual_cat:<b>Evil</b>")
    assert "category" in (await tg.state(OWNER_ID))


async def test_typing_instead_of_choosing_category_reminds_about_buttons(tg):
    await tg.send(OWNER_ID, "➕ Add expense")
    await tg.send(OWNER_ID, "100")
    sent = texts(await tg.send(OWNER_ID, "Transport"))
    assert any("choose a category with the buttons" in t for t in sent)


async def test_too_long_description_is_rejected(tg):
    await tg.send(OWNER_ID, "➕ Add expense")
    await tg.send(OWNER_ID, "100")
    await tg.click(OWNER_ID, "manual_cat:Other")
    sent = texts(await tg.send(OWNER_ID, "x" * 129))
    assert any("too long" in t for t in sent)
    assert await manual_receipts() == []


async def test_cancel_button_and_stale_buttons(tg):
    await tg.send(OWNER_ID, "➕ Add expense")
    await tg.click(OWNER_ID, "manual_cancel")
    assert await tg.state(OWNER_ID) is None

    calls = await tg.click(OWNER_ID, "manual_cat:Other")  # button from the cancelled form
    assert any("no longer active" in (getattr(c, "text", None) or "") for c in calls)
    assert await manual_receipts() == []


async def test_menu_button_cancels_form_and_still_works(tg):
    await tg.send(OWNER_ID, "➕ Add expense")
    sent = texts(await tg.send(OWNER_ID, "📊 Monthly Expenses"))
    assert await tg.state(OWNER_ID) is None
    assert any("Statistics" in t for t in sent)


async def test_add_expense_restarts_an_unfinished_edit(tg):
    await tg.click(OWNER_ID, "edit_field:store_name:10")
    await tg.send(OWNER_ID, "➕ Add expense")
    assert "waiting_for_amount" in (await tg.state(OWNER_ID))


async def test_manual_expense_counts_in_stats(tg):
    await add_expense(tg, amount="100", category="Transport")
    today = local_today()
    sent = texts(await tg.click(OWNER_ID, f"stats:{today.year}:{today.month}"))
    stats = next(t for t in sent if "Statistics" in t)
    assert "Transport</b>: <code>100.00</code>" in stats


async def test_manual_expense_in_list_and_deletion_does_not_touch_storage(tg, storage):
    await add_expense(tg)
    [receipt] = await manual_receipts()

    calls = await tg.send(OWNER_ID, "📜 My Receipts")
    keyboard = [c for c in calls if isinstance(c, SendMessage)][-1].reply_markup.inline_keyboard
    assert any(button.text.startswith("✍️ taxi") for row in keyboard for button in row)

    sent = texts(await tg.click(OWNER_ID, f"delete_receipt:{receipt.id}"))
    assert any("deleted" in t for t in sent)
    assert storage.deleted == []
    assert await manual_receipts() == []


async def test_manual_expense_can_be_edited(tg):
    await add_expense(tg)
    [receipt] = await manual_receipts()
    await tg.click(OWNER_ID, f"edit_item_field:total_price:{receipt.items[0].id}:{receipt.id}")
    await tg.send(OWNER_ID, "300")
    [receipt] = await manual_receipts()
    assert receipt.total_amount == Decimal("300.00")


async def test_family_sees_manual_expenses(tg):
    from test_family import make_family

    await make_family(tg)
    await add_expense(tg, user_id=STRANGER_ID, description="flowers")
    [receipt] = await manual_receipts()
    sent = texts(await tg.click(OWNER_ID, f"view_receipt_from_list:{receipt.id}:1"))
    assert any("Manual expense:</b> flowers" in t and f"Added by:</b> Name{STRANGER_ID}" in t for t in sent)
