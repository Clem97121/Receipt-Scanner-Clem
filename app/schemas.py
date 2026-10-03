import math
from datetime import date as DateType
from typing import List, Optional, Literal
from pydantic import BaseModel, Field, field_validator

# Limits of the DB columns the AI output is saved into (see db/models.py)
MAX_STORE_NAME_LENGTH = 128
MAX_ITEM_NAME_LENGTH = 255
MAX_CURRENCY_LENGTH = 10
MAX_MONEY_AMOUNT = 100_000_000  # Numeric(10, 2) holds values strictly below 10^8
MAX_QUANTITY = 10_000_000  # Numeric(10, 3) holds values strictly below 10^7
MAX_ITEMS = 200


def _is_valid_number(value: float, upper_bound: float, allow_zero: bool = True) -> bool:
    """Checks that a number is finite and fits the DB column range."""
    if not math.isfinite(value) or value >= upper_bound:
        return False
    return value >= 0 if allow_zero else value > 0


class ReceiptItem(BaseModel):
    name: str = Field(description="Name of item or service as on receipt")
    quantity: float = Field(default=1.0, description="Quantity")
    price_per_unit: Optional[float] = Field(
        default=None, description="Price per unit"
    )
    total_price: float = Field(description="Total cost for this item")
    category: Literal[
        "Groceries",
        "Cafe & Dining", 
        "Transport", 
        "Household",
        "Utilities",
        "Entertainment",
        "Shopping", 
        "Other"
    ] = Field(
        description="You MUST strictly classify the item into one of the allowed categories."
    )

    @field_validator("name")
    @classmethod
    def _clean_name(cls, value: str) -> str:
        """Trims the item name to the DB column size and replaces blank names."""
        value = value.strip()[:MAX_ITEM_NAME_LENGTH]
        return value or "Unknown item"


class ReceiptData(BaseModel):
    store_name: Optional[str] = Field(
        default=None, description="Store or venue name"
    )
    date: Optional[DateType] = Field(
        default=None, description="Receipt date in YYYY-MM-DD format"
    )
    currency: str = Field(
        default="CZK", description="Receipt currency (CZK, EUR, USD, etc.)"
    )
    total_amount: float = Field(description="Total receipt amount")
    items: List[ReceiptItem] = Field(
        description="Complete list of purchased items"
    )
    is_receipt: bool = Field(
        default=True,
        description="Set to true ONLY if the image is an actual purchase receipt, cash register slip, or store invoice. Set to false if it is a selfie, photo of people, animals, landscapes, chats, memes, or any non-receipt image."
    )

    @field_validator("store_name")
    @classmethod
    def _clean_store_name(cls, value: Optional[str]) -> Optional[str]:
        """Trims the store name to the DB column size; blank names become None."""
        if value is None:
            return None
        return value.strip()[:MAX_STORE_NAME_LENGTH] or None

    @field_validator("currency")
    @classmethod
    def _clean_currency(cls, value: str) -> str:
        """Normalizes the currency code and falls back to CZK when it is blank."""
        return value.strip().upper()[:MAX_CURRENCY_LENGTH] or "CZK"

    def find_problems(self) -> List[str]:
        """Returns reasons why the recognized numbers cannot be trusted or saved (empty list if all is fine)."""
        problems = []
        if not _is_valid_number(self.total_amount, MAX_MONEY_AMOUNT):
            problems.append(f"invalid total_amount: {self.total_amount}")
        if len(self.items) > MAX_ITEMS:
            problems.append(f"too many items: {len(self.items)}")
        for index, item in enumerate(self.items):
            if not _is_valid_number(item.total_price, MAX_MONEY_AMOUNT):
                problems.append(f"item {index}: invalid total_price {item.total_price}")
            if not _is_valid_number(item.quantity, MAX_QUANTITY, allow_zero=False):
                problems.append(f"item {index}: invalid quantity {item.quantity}")
        return problems