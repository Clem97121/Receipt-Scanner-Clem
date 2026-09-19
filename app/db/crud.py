from datetime import datetime
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, extract, delete, update
from sqlalchemy.orm import selectinload

from db.database import Base, engine
from db.models import Receipt, ReceiptItem, User
from schemas import ReceiptData


async def init_db():
    """Automatically creates tables in Postgres at startup if they don't exist."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def save_receipt_to_db(
    session: AsyncSession, user_id: int, blob_name: str, receipt_data: ReceiptData
) -> Receipt:
    """Saves the user, receipt, and line items to DB and returns the created Receipt entity."""
    receipt_date = receipt_data.date
    if isinstance(receipt_date, str):
        try:
            receipt_date = datetime.strptime(receipt_date, "%Y-%m-%d").date()
        except ValueError:
            receipt_date = None

    user = await session.get(User, user_id)
    if not user:
        user = User(telegram_id=user_id)
        session.add(user)
        await session.flush()

    receipt = Receipt(
        user_id=user_id,
        store_name=receipt_data.store_name,
        date=receipt_date,
        total_amount=receipt_data.total_amount,
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
                quantity=item.quantity,
                total_price=item.total_price,
                category=item.category,
            )
        )
    await session.commit()
    await session.refresh(receipt)
    return receipt


async def get_receipt_by_id(session: AsyncSession, receipt_id: int, user_id: int) -> Optional[Receipt]:
    """Fetches a receipt by ID with preloaded items for a specific user."""
    stmt = (
        select(Receipt)
        .options(selectinload(Receipt.items))
        .where(Receipt.id == receipt_id, Receipt.user_id == user_id)
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


async def update_receipt_category(
    session: AsyncSession, receipt_id: int, user_id: int, new_category: str
) -> Optional[Receipt]:
    """Updates the category for all items belonging to the receipt."""
    receipt = await get_receipt_by_id(session, receipt_id, user_id)
    if not receipt:
        return None

    # Обновляем категорию всех позиций чека
    stmt = (
        update(ReceiptItem)
        .where(ReceiptItem.receipt_id == receipt_id)
        .values(category=new_category)
    )
    await session.execute(stmt)
    await session.commit()
    
    # Перезагружаем чек с обновившимися позициями
    return await get_receipt_by_id(session, receipt_id, user_id)


async def get_monthly_stats(session: AsyncSession, user_id: int):
    """Returns total monthly expenses and category breakdown for the specified user."""
    now = datetime.now()
    year, month = now.year, now.month

    total_stmt = select(func.sum(Receipt.total_amount)).where(
        Receipt.user_id == user_id,
        extract('year', Receipt.date) == year,
        extract('month', Receipt.date) == month
    )
    total_result = await session.execute(total_stmt)
    total_sum = total_result.scalar() or 0.0

    cat_stmt = (
        select(ReceiptItem.category, func.sum(ReceiptItem.total_price))
        .join(Receipt, Receipt.id == ReceiptItem.receipt_id)
        .where(
            Receipt.user_id == user_id,
            extract('year', Receipt.date) == year,
            extract('month', Receipt.date) == month
        )
        .group_by(ReceiptItem.category)
    )
    cat_result = await session.execute(cat_stmt)
    categories = cat_result.all()

    return total_sum, categories


async def delete_receipt_by_id(session: AsyncSession, receipt_id: int, user_id: int) -> bool:
    """Deletes a receipt from the database by ID after validating ownership."""
    stmt = delete(Receipt).where(Receipt.id == receipt_id, Receipt.user_id == user_id)
    result = await session.execute(stmt)
    await session.commit()
    return result.rowcount > 0

async def get_receipt_item_by_id(session: AsyncSession, item_id: int):
    """Fetches a specific receipt item by its ID."""
    return await session.get(ReceiptItem, item_id)

async def update_receipt_item_field(
    session: AsyncSession, item_id: int, field: str, new_value
) -> Optional[Receipt]:
    """Updates a specific field of a receipt item, recalculates total receipt amount, and returns parent receipt."""
    item = await session.get(ReceiptItem, item_id)
    if not item:
        return None

    if not hasattr(item, field):
        return None

    setattr(item, field, new_value)

    stmt = (
        select(Receipt)
        .options(selectinload(Receipt.items))
        .where(Receipt.id == item.receipt_id)
    )
    result = await session.execute(stmt)
    receipt = result.scalar_one_or_none()

    if receipt:
        receipt.total_amount = sum(float(i.total_price) for i in receipt.items)

        await session.commit()
        await session.refresh(receipt)
        return receipt

    return None