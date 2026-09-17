from sqlalchemy.ext.asyncio import AsyncSession
from db.database import engine, Base
from db.models import User, Receipt, ReceiptItem
from schemas import ReceiptData

async def init_db():
    """Automatically creates tables in Postgres at startup if they don't exist."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def save_receipt_to_db(session: AsyncSession, user_id: int, blob_name: str, receipt_data: ReceiptData):
    """Saves the user, the receipt, and all item details."""
    user = await session.get(User, user_id)
    if not user:
        user = User(telegram_id=user_id)
        session.add(user)
        await session.flush()

    receipt = Receipt(
        user_id=user_id,
        store_name=receipt_data.store_name,
        date=receipt_data.date,
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