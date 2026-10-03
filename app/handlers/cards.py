from db.database import AsyncSessionLocal
from db.family import get_display_name
from formatting import format_receipt_text


async def receipt_card(receipt, viewer_id: int) -> str:
    """Formats a saved receipt for the viewer, naming the author when another family member added it."""
    added_by = None
    if receipt.user_id != viewer_id:
        async with AsyncSessionLocal() as session:
            added_by = await get_display_name(session, receipt.user_id)
    return format_receipt_text(receipt, added_by=added_by)
