from typing import List, Optional
from pydantic import BaseModel, Field


class ReceiptItem(BaseModel):
    name: str = Field(description="Name of item or service as on receipt")
    quantity: float = Field(default=1.0, description="Quantity")
    price_per_unit: Optional[float] = Field(
        default=None, description="Price per unit"
    )
    total_price: float = Field(
        description="Total cost for this item"
    )
    category: str = Field(
        description="Category: Groceries, Household, Electronics, Cafe, Clothing, Other"
    )


class ReceiptData(BaseModel):
    store_name: Optional[str] = Field(
        default=None, description="Store or venue name"
    )
    date: Optional[str] = Field(
        default=None, description="Receipt date in YYYY-MM-DD format"
    )
    currency: str = Field(
        default="CZK", description="Receipt currency (CZK, EUR, USD, etc.)"
    )
    total_amount: float = Field(description="Total receipt amount")
    items: List[ReceiptItem] = Field(
        description="Complete list of purchased items"
    )