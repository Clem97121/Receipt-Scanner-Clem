from datetime import date as DateType
from typing import List, Optional, Literal
from pydantic import BaseModel, Field


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