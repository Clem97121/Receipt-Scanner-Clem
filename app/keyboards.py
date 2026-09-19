from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton


def get_main_reply_keyboard() -> ReplyKeyboardMarkup:
    """The main permanent keyboard is located below the input field."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Monthly Expenses")]
        ],
        resize_keyboard=True
    )


def get_receipt_inline_keyboard(receipt_id: int) -> InlineKeyboardMarkup:
    """Inline buttons below the card for the created receipt."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🗑 Delete receipt", 
                    callback_data=f"delete_receipt:{receipt_id}"
                )
            ]
        ]
    )