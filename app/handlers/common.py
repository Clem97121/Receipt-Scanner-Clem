from aiogram import F, Router, types
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.filters import Command, CommandObject, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext

from db.family import INVITE_PREFIX
from handlers.family import join_family_from_link
from keyboards import MAIN_MENU_BUTTONS, get_main_reply_keyboard
from states import INPUT_STATES

router = Router(name="common")


@router.message(Command("cancel"))
async def cmd_cancel(message: types.Message, state: FSMContext):
    """Clears any active FSM state (an unfinished edit or manual expense)."""
    if await state.get_state() is None:
        await message.answer("Nothing to cancel.", reply_markup=get_main_reply_keyboard())
        return
    await state.clear()
    await message.answer("✖️ Cancelled.", reply_markup=get_main_reply_keyboard())


@router.message(
    StateFilter(*INPUT_STATES),
    F.text.in_(MAIN_MENU_BUTTONS) | F.text.startswith("/"),
)
async def interrupt_edit_handler(message: types.Message, state: FSMContext):
    """Cancels an unfinished input when the user presses a menu button or sends a command, then lets it run."""
    await state.clear()
    await message.answer("✖️ Cancelled.")
    raise SkipHandler()


@router.message(CommandStart())
async def cmd_start(message: types.Message, command: CommandObject):
    """Greeting handler that attaches the main reply keyboard; /start join_<token> joins a family."""
    if command.args and command.args.startswith(INVITE_PREFIX):
        await join_family_from_link(message, command.args[len(INVITE_PREFIX):])
        return

    await message.answer(
        "👋 Hi! I'm an expense tracking bot.\n\n"
        "• Send me a photo of a receipt, and I'll process it.\n"
        "• Click «📊 Monthly Expenses» to view your statistics.\n"
        "• Click «📜 My Receipts» to browse your saved receipts.\n"
        "• Click «➕ Add expense» to add a purchase without a receipt.\n"
        "• Click «👨‍👩‍👧 Family» to share receipts with your family.\n"
        "• Send /cancel to abort an unfinished edit.",
        reply_markup=get_main_reply_keyboard(),
    )
