from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, extract, delete

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