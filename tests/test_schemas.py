import pytest

from schemas import MAX_ITEMS, ReceiptData


def _receipt(**overrides) -> ReceiptData:
    data = {
        "store_name": "Shop",
        "currency": "CZK",
        "total_amount": 10.0,
        "items": [{"name": "milk", "quantity": 1.0, "total_price": 10.0, "category": "Groceries"}],
    }
    data.update(overrides)
    return ReceiptData.model_validate(data)


def test_long_texts_are_trimmed_to_column_sizes():
    receipt = _receipt(
        store_name="  " + "s" * 300 + "  ",
        currency=" eur ",
        items=[{"name": "n" * 1000, "total_price": 1, "category": "Other"}],
    )
    assert len(receipt.store_name) == 128
    assert receipt.currency == "EUR"
    assert len(receipt.items[0].name) == 255


def test_blank_texts_get_fallbacks():
    receipt = _receipt(store_name="   ", currency=" ", items=[{"name": "  ", "total_price": 1, "category": "Other"}])
    assert receipt.store_name is None
    assert receipt.currency == "CZK"
    assert receipt.items[0].name == "Unknown item"


def test_valid_receipt_has_no_problems():
    assert _receipt().find_problems() == []
    assert _receipt(total_amount=0, items=[]).find_problems() == []


@pytest.mark.parametrize("total", [-1, 100_000_000, 1e30, float("nan"), float("inf")])
def test_invalid_total_is_a_problem(total):
    assert _receipt(total_amount=total).find_problems()


@pytest.mark.parametrize("item", [
    {"name": "x", "total_price": -1e9, "category": "Other"},
    {"name": "x", "total_price": float("nan"), "category": "Other"},
    {"name": "x", "total_price": 1e9, "category": "Other"},
    {"name": "x", "quantity": 0, "total_price": 1, "category": "Other"},
    {"name": "x", "quantity": -2, "total_price": 1, "category": "Other"},
    {"name": "x", "quantity": 1e8, "total_price": 1, "category": "Other"},
])
def test_invalid_item_numbers_are_a_problem(item):
    assert _receipt(items=[item]).find_problems()


def test_discount_lines_are_allowed():
    receipt = _receipt(total_amount=17, items=[
        {"name": "Cheese", "total_price": 20, "category": "Groceries"},
        {"name": "Discount", "total_price": -3.0, "category": "Groceries"},
        {"name": "Coupon", "total_price": -20.0, "category": "Other"},
        {"name": "Wine", "total_price": 20, "category": "Groceries"},
    ])
    assert receipt.find_problems() == []


def test_too_many_items_is_a_problem():
    items = [{"name": "x", "total_price": 1, "category": "Other"}] * (MAX_ITEMS + 1)
    assert _receipt(items=items).find_problems()


def test_nan_from_ai_json_is_caught():
    receipt = ReceiptData.model_validate_json(
        '{"total_amount": NaN, "items": [], "currency": "CZK"}'
    )
    assert receipt.find_problems()
