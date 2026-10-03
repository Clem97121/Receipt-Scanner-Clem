from decimal import Decimal
from html import escape


def _esc(value) -> str:
    """Converts a value to string and escapes it for Telegram HTML parse mode."""
    return escape(str(value))


def _money(value) -> str:
    """Formats a money amount (Decimal or float) with exactly two decimals."""
    return f"{Decimal(str(value)):.2f}"


def _quantity(value) -> str:
    """Formats a quantity without trailing zeros (1.000 -> 1, 0.500 -> 0.5)."""
    text = f"{Decimal(str(value)):f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def format_receipt_text(receipt) -> str:
    """Formats a receipt (DB Receipt entity or pydantic ReceiptData) into an HTML text string with numbered items.

    DB items are sorted by id; pydantic items (which have no id) keep their original order.
    """
    items = list(receipt.items)
    if all(getattr(item, "id", None) is not None for item in items):
        items.sort(key=lambda x: x.id)

    currency = _esc(receipt.currency)
    items_formatted = "\n".join(
        [
            f"{i+1}. <b>{_esc(item.name)}</b> ({_quantity(item.quantity)}x) — "
            f"<code>{_money(item.total_price)} {currency}</code> <i>[{_esc(item.category)}]</i>"
            for i, item in enumerate(items)
        ]
    )
    return (
        f"🏪 <b>Store:</b> {_esc(receipt.store_name or 'Not specified')}\n"
        f"📅 <b>Date:</b> {_esc(receipt.date or 'Not specified')}\n"
        f"💰 <b>Total:</b> <code>{_money(receipt.total_amount)} {currency}</code>\n\n"
        f"🛒 <b>Items:</b>\n{items_formatted}"
    )
