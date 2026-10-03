from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
import calendar

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

BTN_MONTHLY_EXPENSES = "📊 Monthly Expenses"
BTN_MY_RECEIPTS = "📜 My Receipts"
BTN_FAMILY = "👨‍👩‍👧 Family"
BTN_ADD_EXPENSE = "➕ Add expense"
MAIN_MENU_BUTTONS = (BTN_MONTHLY_EXPENSES, BTN_MY_RECEIPTS, BTN_ADD_EXPENSE, BTN_FAMILY)


def get_main_reply_keyboard() -> ReplyKeyboardMarkup:
    """Returns the main persistent reply keyboard located beneath the input field."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text=BTN_MONTHLY_EXPENSES),
                KeyboardButton(text=BTN_MY_RECEIPTS)
            ],
            [
                KeyboardButton(text=BTN_ADD_EXPENSE),
                KeyboardButton(text=BTN_FAMILY)
            ]
        ],
        resize_keyboard=True
    )


def get_manual_cancel_keyboard() -> InlineKeyboardMarkup:
    """Cancel button for the manual expense form."""
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="❌ Cancel", callback_data="manual_cancel")]]
    )


def get_manual_category_keyboard() -> InlineKeyboardMarkup:
    """Category choice for a manual expense."""
    buttons = []
    for i in range(0, len(PRESET_CATEGORIES), 2):
        buttons.append([
            InlineKeyboardButton(text=label, callback_data=f"manual_cat:{cat_code}")
            for label, cat_code in PRESET_CATEGORIES[i:i+2]
        ])
    buttons.append([InlineKeyboardButton(text="❌ Cancel", callback_data="manual_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_manual_description_keyboard() -> InlineKeyboardMarkup:
    """Lets the user skip the optional description of a manual expense."""
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="⏭ Skip", callback_data="manual_skip_description"),
            InlineKeyboardButton(text="❌ Cancel", callback_data="manual_cancel")
        ]]
    )


def get_family_keyboard(in_family: bool) -> InlineKeyboardMarkup:
    """Returns the family screen actions."""
    buttons = [[InlineKeyboardButton(text="🔗 Invite to family", callback_data="family_invite")]]
    if in_family:
        buttons.append([InlineKeyboardButton(text="🚪 Leave family", callback_data="family_leave")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_family_leave_confirm_keyboard() -> InlineKeyboardMarkup:
    """Asks the user to confirm leaving the family."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Yes, leave", callback_data="family_leave_confirm"),
                InlineKeyboardButton(text="❌ Cancel", callback_data="family_menu")
            ]
        ]
    )


def get_receipt_inline_keyboard(receipt_id: int, back_page: int = None) -> InlineKeyboardMarkup:
    """Returns the main inline keyboard attached to a receipt card, with an optional back-to-list button."""
    keyboard = [
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
    if back_page is not None:
        keyboard.append([
            InlineKeyboardButton(
                text="📜 Back to List", 
                callback_data=f"receipts_page:{back_page}"
            )
        ])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_receipts_list_keyboard(receipts, page: int, total_pages: int) -> InlineKeyboardMarkup:
    """Generates a keyboard with a list of receipts and pagination controls."""
    keyboard = []
    
    for r in receipts:
        if r.blob_name is None:
            store = f"✍️ {r.store_name or 'Manual expense'}"
        else:
            store = f"🏪 {r.store_name or 'Unknown Store'}"
        total = f"{r.total_amount:.2f} {r.currency}" if r.total_amount is not None else ""
        date = str(r.date) if r.date else ""

        btn_text = f"{store} | {total} | {date}"
        if len(btn_text) > 36:
            btn_text = btn_text[:33] + "..."
            
        keyboard.append([
            InlineKeyboardButton(
                text=btn_text,
                callback_data=f"view_receipt_from_list:{r.id}:{page}"
            )
        ])
    
    # Navigation row
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(text="⬅️ Prev", callback_data=f"receipts_page:{page - 1}"))
    
    nav_row.append(InlineKeyboardButton(text=f"📄 {page}/{max(total_pages, 1)}", callback_data="ignore_receipts_title"))
    
    if page < total_pages:
        nav_row.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"receipts_page:{page + 1}"))
        
    if nav_row:
        keyboard.append(nav_row)
        
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


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


def get_stats_keyboard(year: int, month: int) -> InlineKeyboardMarkup:
    """Generates month pagination keyboard for statistics."""
    prev_month = month - 1
    prev_year = year
    if prev_month < 1:
        prev_month = 12
        prev_year -= 1

    next_month = month + 1
    next_year = year
    if next_month > 12:
        next_month = 1
        next_year += 1

    month_name = calendar.month_name[month]

    buttons = [
        [
            InlineKeyboardButton(text="⬅️ Prev", callback_data=f"stats:{prev_year}:{prev_month}"),
            InlineKeyboardButton(text=f"📅 {month_name} {year}", callback_data="ignore_stats_title"),
            InlineKeyboardButton(text="Next ➡️", callback_data=f"stats:{next_year}:{next_month}")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)