from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import and_, or_, select, func, delete, desc
from sqlalchemy.orm import selectinload

from db.models import Receipt, ReceiptItem, User
from schemas import ReceiptData
from timeutils import local_today


MONEY_QUANT = Decimal("0.01")
QUANTITY_QUANT = Decimal("0.001")


def visible_user_ids(user_id: int):
    """Subquery of users whose receipts user_id may see and change: the user and their family members."""
    family_id = select(User.family_id).where(User.telegram_id == user_id).scalar_subquery()
    return select(User.telegram_id).where(
        or_(
            User.telegram_id == user_id,
            and_(User.family_id.is_not(None), User.family_id == family_id),
        )
    )


def visible_to(user_id: int):
    """SQL condition: the receipt belongs to user_id or to a member of their family."""
    return Receipt.user_id.in_(visible_user_ids(user_id))


def to_decimal(value, quant: Decimal = MONEY_QUANT) -> Decimal:
    """Converts a float/str/Decimal to a Decimal rounded to the column scale (via str to avoid binary float artifacts)."""
    return Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP)


async def save_receipt_to_db(
    session: AsyncSession, user_id: int, blob_name: str, receipt_data: ReceiptData
) -> Receipt:
    """Saves the user, receipt, and line items to DB and returns the created Receipt entity.

    Receipts without a readable date get today's date, so they still show up in monthly statistics.
    """
    receipt_date = receipt_data.date
    if isinstance(receipt_date, str):
        try:
            receipt_date = datetime.strptime(receipt_date, "%Y-%m-%d").date()
        except ValueError:
            receipt_date = None
    if receipt_date is None:
        receipt_date = local_today()

    user = await session.get(User, user_id)
    if not user:
        user = User(telegram_id=user_id)
        session.add(user)
        await session.flush()

    receipt = Receipt(
        user_id=user_id,
        store_name=receipt_data.store_name,
        date=receipt_date,
        total_amount=to_decimal(receipt_data.total_amount),
        currency=receipt_data.currency,
        blob_name=blob_name,
    )
    session.add(receipt)
    await session.flush()

    for item in receipt_data.items:
        session.add(
            ReceiptItem(
                receipt_id=receipt.id,
                name=item.name,
                quantity=to_decimal(item.quantity, QUANTITY_QUANT),
                total_price=to_decimal(item.total_price),
                category=item.category,
            )
        )
    await session.commit()
    await session.refresh(receipt)
    return receipt


async def get_receipt_by_id(session: AsyncSession, receipt_id: int, user_id: int) -> Optional[Receipt]:
    """Fetches a receipt by ID with preloaded items, if it is visible to the user (own or family)."""
    stmt = (
        select(Receipt)
        .options(selectinload(Receipt.items))
        .where(Receipt.id == receipt_id, visible_to(user_id))
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def update_receipt_field(
    session: AsyncSession, receipt_id: int, user_id: int, field: str, new_value
) -> Optional[Receipt]:
    """Updates a specific field of a receipt and returns the updated entity."""
    receipt = await get_receipt_by_id(session, receipt_id, user_id)
    if not receipt:
        return None

    if hasattr(receipt, field):
        setattr(receipt, field, new_value)
        await session.commit()
        await session.refresh(receipt)
        return receipt

    return None


def _month_filter(year: int, month: int):
    """SQL condition for receipts dated within the given month (a date range, so the date index is used)."""
    first_day = date(year, month, 1)
    next_month = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return and_(Receipt.date >= first_day, Receipt.date < next_month)


async def get_monthly_stats(session: AsyncSession, user_id: int, year: int = None, month: int = None):
    """Returns total monthly expenses and category breakdown for the user (and their family) and period."""
    if year is None or month is None:
        today = local_today()
        year, month = today.year, today.month

    in_month = _month_filter(year, month)
    total_stmt = select(func.sum(Receipt.total_amount)).where(
        visible_to(user_id),
        in_month,
    )
    total_result = await session.execute(total_stmt)
    total_sum = Decimal(str(total_result.scalar() or 0))

    cat_stmt = (
        select(ReceiptItem.category, func.sum(ReceiptItem.total_price))
        .join(Receipt, Receipt.id == ReceiptItem.receipt_id)
        .where(
            visible_to(user_id),
            in_month,
        )
        .group_by(ReceiptItem.category)
    )
    cat_result = await session.execute(cat_stmt)
    categories = [(cat, Decimal(str(amount or 0))) for cat, amount in cat_result.all()]

    return total_sum, categories


async def delete_receipt_by_id(
    session: AsyncSession, receipt_id: int, user_id: int
) -> tuple[bool, Optional[str]]:
    """Deletes a receipt visible to the user (own or family).

    Returns (deleted, photo blob name); the blob name is None for manual expenses.
    """
    stmt = (
        delete(Receipt)
        .where(Receipt.id == receipt_id, visible_to(user_id))
        .returning(Receipt.blob_name)
    )
    result = await session.execute(stmt)
    rows = result.all()
    await session.commit()
    if not rows:
        return False, None
    return True, rows[0].blob_name

async def get_receipt_item_by_id(session: AsyncSession, item_id: int):
    """Fetches a specific receipt item by its ID."""
    return await session.get(ReceiptItem, item_id)

async def update_receipt_item_field(
    session: AsyncSession, item_id: int, user_id: int, field: str, new_value
) -> Optional[Receipt]:
    """Updates a specific field of a receipt item visible to the user (own or family), recalculates total receipt amount, and returns parent receipt."""
    item_stmt = (
        select(ReceiptItem)
        .join(Receipt, Receipt.id == ReceiptItem.receipt_id)
        .where(ReceiptItem.id == item_id, visible_to(user_id))
    )
    item = (await session.execute(item_stmt)).scalar_one_or_none()
    if not item:
        return None

    if not hasattr(item, field):
        return None

    setattr(item, field, new_value)

    stmt = (
        select(Receipt)
        .options(selectinload(Receipt.items))
        .where(Receipt.id == item.receipt_id, visible_to(user_id))
    )
    result = await session.execute(stmt)
    receipt = result.scalar_one_or_none()

    if receipt:
        receipt.total_amount = sum((Decimal(i.total_price) for i in receipt.items), Decimal("0.00"))

        await session.commit()
        await session.refresh(receipt)
        return receipt

    return None

async def save_manual_expense(
    session: AsyncSession,
    user_id: int,
    amount: Decimal,
    category: str,
    description: Optional[str],
    currency: str,
    expense_date: date,
) -> Receipt:
    """Saves an expense entered without a receipt photo as a receipt with a single item."""
    receipt = Receipt(
        user_id=user_id,
        store_name=description,
        date=expense_date,
        total_amount=to_decimal(amount),
        currency=currency,
        blob_name=None,
    )
    session.add(receipt)
    await session.flush()
    session.add(ReceiptItem(
        receipt_id=receipt.id,
        name=description or category,
        quantity=Decimal("1.000"),
        total_price=to_decimal(amount),
        category=category,
    ))
    await session.commit()
    return await get_receipt_by_id(session, receipt.id, user_id)


def photo_blob_name(user_id: int, file_unique_id: str) -> str:
    """Blob name for a receipt photo; file_unique_id is stable for the same file, unlike file_id."""
    return f"{user_id}/{file_unique_id}.jpg"


async def find_receipt_by_photo(session: AsyncSession, file_unique_id: str, user_id: int) -> Optional[Receipt]:
    """Finds an already saved receipt (own or family) made from the same Telegram photo, preloading items."""
    stmt = (
        select(Receipt)
        .options(selectinload(Receipt.items))
        .where(
            visible_to(user_id),
            Receipt.blob_name.endswith(f"/{file_unique_id}.jpg", autoescape=True),
        )
        .order_by(Receipt.id)
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()

async def get_user_receipts_paginated(session, user_id: int, offset: int = 0, limit: int = 5):
    """Returns a paginated list of the user's and their family's receipts, newest first."""
    stmt = (
        select(Receipt)
        .where(visible_to(user_id))
        .order_by(desc(Receipt.id))
        .offset(offset)
        .limit(limit)
    )
    result = await session.execute(stmt)
    return result.scalars().all()

async def get_user_receipts_count(session, user_id: int) -> int:
    """Returns the total number of receipts visible to the user (own and family)."""
    stmt = select(func.count(Receipt.id)).where(visible_to(user_id))
    result = await session.execute(stmt)
    return result.scalar() or 0