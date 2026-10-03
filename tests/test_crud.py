from datetime import date
from decimal import Decimal

from conftest import OWNER_ID, STRANGER_ID, load_receipt, texts
from db.crud import get_monthly_stats, save_receipt_to_db, update_receipt_item_field
from db.database import AsyncSessionLocal
from schemas import ReceiptData


def _ai_receipt(blob_suffix: str = "") -> ReceiptData:
    return ReceiptData(
        store_name="Dec" + blob_suffix,
        date=date.today(),
        currency="CZK",
        total_amount=0.1 + 0.2,
        items=[
            {"name": "a", "quantity": 1.0, "total_price": 0.1, "category": "Groceries"},
            {"name": "b", "quantity": 0.5, "total_price": 0.2, "category": "Other"},
        ],
    )


async def _save(user_id: int = OWNER_ID, blob: str = "dec-blob"):
    async with AsyncSessionLocal() as session:
        return await save_receipt_to_db(session, user_id, blob, _ai_receipt())


async def test_ai_floats_are_stored_as_exact_decimals(db):
    data = _ai_receipt()
    assert data.total_amount == 0.30000000000000004  # the float artifact we must not store

    saved = await _save()
    receipt = await load_receipt(saved.id)
    assert receipt.total_amount == Decimal("0.30")
    assert isinstance(receipt.total_amount, Decimal)
    assert sorted(str(i.total_price) for i in receipt.items) == ["0.10", "0.20"]
    assert sorted(str(i.quantity) for i in receipt.items) == ["0.500", "1.000"]


async def test_save_creates_missing_user(db):
    saved = await _save(user_id=777, blob="new-user-blob")
    assert (await load_receipt(saved.id)).user_id == 777


async def test_item_update_recalculates_total_exactly(db):
    saved = await _save()
    first_item = sorted((await load_receipt(saved.id)).items, key=lambda i: i.id)[0]
    async with AsyncSessionLocal() as session:
        updated = await update_receipt_item_field(session, first_item.id, OWNER_ID, "total_price", Decimal("0.10"))
    assert updated.total_amount == Decimal("0.30")


async def test_item_update_requires_ownership(db):
    saved = await _save()
    item_id = (await load_receipt(saved.id)).items[0].id
    async with AsyncSessionLocal() as session:
        assert await update_receipt_item_field(session, item_id, STRANGER_ID, "name", "x") is None


async def test_monthly_stats_are_decimal(db):
    await _save()
    today = date.today()
    async with AsyncSessionLocal() as session:
        total, categories = await get_monthly_stats(session, OWNER_ID, today.year, today.month)
    assert total == Decimal("0.30") and isinstance(total, Decimal)
    assert dict(categories) == {"Groceries": Decimal("0.10"), "Other": Decimal("0.20")}
    assert all(isinstance(amount, Decimal) for _, amount in categories)


async def test_empty_month_stats(db):
    async with AsyncSessionLocal() as session:
        total, categories = await get_monthly_stats(session, OWNER_ID, 2000, 1)
    assert total == Decimal("0") and isinstance(total, Decimal)
    assert categories == []


async def test_stats_message_renders_decimal_totals(tg):
    await _save()
    sent = texts(await tg.send(OWNER_ID, "📊 Monthly Expenses"))
    assert any("<code>0.30</code>" in t for t in sent)
