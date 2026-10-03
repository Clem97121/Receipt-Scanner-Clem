from aiogram.fsm.state import State, StatesGroup


class EditReceiptState(StatesGroup):
    waiting_for_value = State()


class EditItemState(StatesGroup):
    waiting_for_value = State()


class ManualExpenseState(StatesGroup):
    waiting_for_amount = State()
    waiting_for_category = State()
    waiting_for_description = State()


# States in which the user is in the middle of a multi-step input; menu buttons and commands cancel them
INPUT_STATES = (
    EditReceiptState.waiting_for_value,
    EditItemState.waiting_for_value,
    ManualExpenseState.waiting_for_amount,
    ManualExpenseState.waiting_for_category,
    ManualExpenseState.waiting_for_description,
)
