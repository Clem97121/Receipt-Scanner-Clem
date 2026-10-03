from decimal import Decimal

import pytest

from handlers.edit import ALLOWED_CATEGORIES, parse_money_amount
from keyboards import PRESET_CATEGORIES
from schemas import ReceiptItem as AiReceiptItem


@pytest.mark.parametrize("raw, expected", [
    ("12.50", Decimal("12.50")),
    ("12,5", Decimal("12.50")),
    ("1 000", Decimal("1000.00")),
    ("0", Decimal("0.00")),
    ("12.345", Decimal("12.35")),
    ("1e-30", Decimal("0.00")),
    ("99999999.99", Decimal("99999999.99")),
])
def test_parse_money_amount_accepts_valid_values(raw, expected):
    assert parse_money_amount(raw) == expected


@pytest.mark.parametrize("raw", [
    "", "abc", "-1", "-0.001", "nan", "sNaN", "inf", "-Infinity",
    "1e30", "100000000", "99999999.995",
])
def test_parse_money_amount_rejects_invalid_values(raw):
    assert parse_money_amount(raw) is None


def test_allowed_categories_match_ai_schema():
    """Preset keyboard categories must stay in sync with the categories Gemini is allowed to return."""
    ai_categories = set(AiReceiptItem.model_fields["category"].annotation.__args__)
    assert ALLOWED_CATEGORIES == ai_categories
    assert len(ALLOWED_CATEGORIES) == len(PRESET_CATEGORIES)
