from aiogram import F, Router, types
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext

from keyboards import MAIN_MENU_BUTTONS, get_main_reply_keyboard
from states import EDIT_STATES

router = Router(name="common")


@router.message(Command("cancel"))
async def cmd_cancel(message: types.Message, state: FSMContext):
    """Clears any active FSM state (e.g. an unfinished edit)."""
    if await state.get_state() is None:
        await message.answer("Nothing to cancel.", reply_markup=get_main_reply_keyboard())
        return
    await state.clear()
    await message.answer("✖️ Editing cancelled.", reply_markup=get_main_reply_keyboard())


@router.message(
    StateFilter(*EDIT_STATES),
    F.text.in_(MAIN_MENU_BUTTONS) | F.text.startswith("/"),
)
async def interrupt_edit_handler(message: types.Message, state: FSMContext):
    """Cancels an unfinished edit when the user presses a menu button or sends a command, then lets it run."""
    await state.clear()
    await message.answer("✖️ Editing cancelled.")
    raise SkipHandler()


@router.message(Command("start"))
async def cmd_start(message: types.Message):
    """Greeting handler that attaches the main reply keyboard."""
    await message.answer(
        "👋 Hi! I'm an expense tracking bot.\n\n"
        "• Send me a photo of a receipt, and I'll process it.\n"
        "• Click «📊 Monthly Expenses» to view your statistics.\n"
        "• Click «📜 My Receipts» to browse your saved receipts.\n"
        "• Send /cancel to abort an unfinished edit.",
        reply_markup=get_main_reply_keyboard(),
    )
