from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

PRESET_CATEGORIES = [
    ("🥦 Groceries", "Groceries"),
    ("🍽 Cafe & Dining", "Cafe & Dining"),
    ("🚗 Transport", "Transport"),
    ("🏠 Household", "Household"),
    ("⚡ Utilities & Bills", "Utilities"),
    ("🎮 Entertainment", "Entertainment"),
    ("🛍 Shopping", "Shopping"),
    ("❓ Other", "Other"),
]


def get_main_reply_keyboard() -> ReplyKeyboardMarkup:
    """Returns the main persistent reply keyboard located beneath the input field."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Monthly Expenses")]
        ],
        resize_keyboard=True
    )


def get_receipt_inline_keyboard(receipt_id: int) -> InlineKeyboardMarkup:
    """Returns the main inline keyboard attached to a receipt card."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✏️ Edit", 
                    callback_data=f"edit_receipt:{receipt_id}"
                ),
                InlineKeyboardButton(
                    text="🗑 Delete", 
                    callback_data=f"delete_receipt:{receipt_id}"
                )
            ]
        ]
    )


def get_edit_fields_keyboard(receipt_id: int) -> InlineKeyboardMarkup:
    """Returns the inline keyboard with field selection for editing."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🏪 Store Name", callback_data=f"edit_field:store_name:{receipt_id}"),
                InlineKeyboardButton(text="📅 Date", callback_data=f"edit_field:date:{receipt_id}")
            ],
            [
                InlineKeyboardButton(text="💰 Total Amount", callback_data=f"edit_field:total_amount:{receipt_id}"),
                InlineKeyboardButton(text="🛒 Edit Items", callback_data=f"edit_items_menu:{receipt_id}")
            ],
            [
                InlineKeyboardButton(text="❌ Cancel", callback_data=f"cancel_edit:{receipt_id}")
            ]
        ]
    )

def get_items_selection_keyboard(receipt) -> InlineKeyboardMarkup:
    """Returns a grid of item numbers for selection."""
    sorted_items = sorted(receipt.items, key=lambda x: x.id)
    buttons = []
    row = []
    
    for i, item in enumerate(sorted_items):
        row.append(InlineKeyboardButton(text=f"📌 {i+1}", callback_data=f"select_item:{item.id}:{receipt.id}"))
        if len(row) == 5:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    
    buttons.append([InlineKeyboardButton(text="🔙 Back", callback_data=f"edit_receipt:{receipt.id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_single_item_edit_keyboard(item_id: int, receipt_id: int) -> InlineKeyboardMarkup:
    """Returns options to edit a specific item (Name, Price, Category, Back)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✏️ Name", callback_data=f"edit_item_field:name:{item_id}:{receipt_id}"),
                InlineKeyboardButton(text="💰 Price", callback_data=f"edit_item_field:total_price:{item_id}:{receipt_id}")
            ],
            [
                InlineKeyboardButton(text="🏷 Category", callback_data=f"select_item_category:{item_id}:{receipt_id}")
            ],
            [
                InlineKeyboardButton(text="🔙 Back to Items", callback_data=f"edit_items_menu:{receipt_id}")
            ]
        ]
    )

def get_item_categories_keyboard(item_id: int, receipt_id: int) -> InlineKeyboardMarkup:
    """Returns preset category buttons for a specific item."""
    buttons = []
    for i in range(0, len(PRESET_CATEGORIES), 2):
        row = []
        for label, cat_code in PRESET_CATEGORIES[i:i+2]:
            row.append(InlineKeyboardButton(text=label, callback_data=f"set_item_cat:{item_id}:{receipt_id}:{cat_code}"))
        buttons.append(row)
    
    buttons.append([InlineKeyboardButton(text="🔙 Back", callback_data=f"select_item:{item_id}:{receipt_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)