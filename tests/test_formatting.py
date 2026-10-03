from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from formatting import format_receipt_text
from schemas import ReceiptData


def test_escapes_html_in_user_and_ai_text():
    receipt = ReceiptData(
        store_name="A&B <script>",
        currency="CZK",
        total_amount=3,
        items=[{"name": "<b>bold</b>", "total_price": 3, "category": "Other"}],
    )
    text = format_receipt_text(receipt)
    assert "A&amp;B &lt;script&gt;" in text
    assert "&lt;b&gt;bold&lt;/b&gt;" in text
    assert "<script>" not in text


def test_escapes_currency_and_category_from_db():
    item = SimpleNamespace(id=1, name="x", quantity=Decimal("1"), total_price=Decimal("1"), category="O&")
    receipt = SimpleNamespace(store_name=None, date=None, currency="€<", total_amount=Decimal("1"), items=[item])
    text = format_receipt_text(receipt)
    assert "€&lt;" in text
    assert "[O&amp;]" in text


def test_db_items_sorted_by_id_pydantic_items_keep_order():
    db_items = [
        SimpleNamespace(id=5, name="second", quantity=1, total_price=1, category="Other"),
        SimpleNamespace(id=2, name="first", quantity=1, total_price=2, category="Other"),
    ]
    db_receipt = SimpleNamespace(store_name="S", date=None, currency="CZK", total_amount=3, items=db_items)
    db_text = format_receipt_text(db_receipt)
    assert db_text.index("first") < db_text.index("second")

    ai_receipt = ReceiptData(currency="CZK", total_amount=3, items=[
        {"name": "zeta", "total_price": 1, "category": "Other"},
        {"name": "alpha", "total_price": 2, "category": "Other"},
    ])
    ai_text = format_receipt_text(ai_receipt)
    assert ai_text.index("zeta") < ai_text.index("alpha")


def test_money_has_two_decimals_and_quantity_has_no_trailing_zeros():
    receipt = ReceiptData(store_name="S", date=date(2026, 3, 29), currency="CZK", total_amount=0.1 + 0.2, items=[
        {"name": "a", "quantity": 1.0, "total_price": 0.1, "category": "Other"},
        {"name": "b", "quantity": 0.5, "total_price": 12.5, "category": "Other"},
    ])
    text = format_receipt_text(receipt)
    assert "<code>0.30 CZK</code>" in text
    assert "<code>12.50 CZK</code>" in text
    assert "(1x)" in text and "(0.5x)" in text
    assert "0000" not in text
    assert "2026-03-29" in text


def test_long_receipt_fits_telegram_message_limit():
    items = [{"name": f"item number {i} " + "x" * 40, "total_price": 1, "category": "Groceries"} for i in range(150)]
    receipt = ReceiptData(store_name="Big", currency="CZK", total_amount=150, items=items)
    text = format_receipt_text(receipt)
    assert len(text) <= 3500
    assert "1. <b>item number 0 " in text
    assert "more items</i>" in text


def test_short_receipt_is_not_truncated():
    receipt = ReceiptData(currency="CZK", total_amount=1, items=[{"name": "a", "total_price": 1, "category": "Other"}])
    assert "more items" not in format_receipt_text(receipt)


def test_missing_store_and_date():
    receipt = ReceiptData(currency="CZK", total_amount=0, items=[])
    text = format_receipt_text(receipt)
    assert "<b>Store:</b> Not specified" in text
    assert "<b>Date:</b> Not specified" in text
