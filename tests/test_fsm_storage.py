from aiogram.fsm.storage.base import StorageKey
from sqlalchemy import select

from db.database import AsyncSessionLocal
from db.models import FsmState
from fsm_storage import DatabaseStorage
from states import EditItemState

KEY = StorageKey(bot_id=1, chat_id=10, user_id=20)
OTHER_KEY = StorageKey(bot_id=1, chat_id=11, user_id=21)


async def rows() -> list[FsmState]:
    async with AsyncSessionLocal() as session:
        return list((await session.execute(select(FsmState))).scalars().all())


async def test_state_and_data_round_trip(db):
    storage = DatabaseStorage()
    await storage.set_state(KEY, EditItemState.waiting_for_value)
    await storage.set_data(KEY, {"item_id": 5, "field": "name", "amount": "12.50"})

    assert await storage.get_state(KEY) == EditItemState.waiting_for_value.state
    assert await storage.get_data(KEY) == {"item_id": 5, "field": "name", "amount": "12.50"}
    assert await storage.get_state(OTHER_KEY) is None
    assert await storage.get_data(OTHER_KEY) == {}


async def test_a_new_storage_instance_sees_the_same_state(db):
    """Each Lambda invocation may create its own process; the state must come from the DB."""
    await DatabaseStorage().set_state(KEY, "Some:state")
    assert await DatabaseStorage().get_state(KEY) == "Some:state"


async def test_clearing_removes_the_row(db):
    storage = DatabaseStorage()
    await storage.set_state(KEY, "Some:state")
    await storage.set_data(KEY, {"x": 1})

    await storage.set_state(KEY, None)
    await storage.set_data(KEY, {})

    assert await rows() == []


async def test_empty_writes_do_not_create_rows(db):
    storage = DatabaseStorage()
    await storage.set_state(KEY, None)
    await storage.set_data(KEY, {})
    assert await rows() == []


async def test_update_data_merges(db):
    storage = DatabaseStorage()
    await storage.update_data(KEY, {"a": 1})
    await storage.update_data(KEY, {"b": 2})
    assert await storage.get_data(KEY) == {"a": 1, "b": 2}
