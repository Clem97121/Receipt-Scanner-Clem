from aiogram.fsm.state import State, StatesGroup


class EditReceiptState(StatesGroup):
    waiting_for_value = State()


class EditItemState(StatesGroup):
    waiting_for_value = State()


# States in which the user is expected to type a new value
EDIT_STATES = (EditReceiptState.waiting_for_value, EditItemState.waiting_for_value)
