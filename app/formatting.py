from html import escape


def _esc(value) -> str:
    """Converts a value to string and escapes it for Telegram HTML parse mode."""
    return escape(str(value))


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
            f"{i+1}. <b>{_esc(item.name)}</b> ({_esc(item.quantity)}x) — "
            f"<code>{_esc(item.total_price)} {currency}</code> <i>[{_esc(item.category)}]</i>"
            for i, item in enumerate(items)
        ]
    )
    return (
        f"🏪 <b>Store:</b> {_esc(receipt.store_name or 'Not specified')}\n"
        f"📅 <b>Date:</b> {_esc(receipt.date or 'Not specified')}\n"
        f"💰 <b>Total:</b> <code>{_esc(receipt.total_amount)} {currency}</code>\n\n"
        f"🛒 <b>Items:</b>\n{items_formatted}"
    )
