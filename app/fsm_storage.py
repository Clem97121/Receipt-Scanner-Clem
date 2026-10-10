import json
from typing import Any, Mapping

from aiogram.fsm.state import State
from aiogram.fsm.storage.base import BaseStorage, DefaultKeyBuilder, KeyBuilder, StorageKey
from sqlalchemy import inspect

from db.database import AsyncSessionLocal
from db.models import FsmState


class DatabaseStorage(BaseStorage):
    """aiogram FSM storage in the app database.

    Lambda instances keep no memory between invocations, so an unfinished edit or manual expense
    must survive in the DB. Load is tiny (a few rows per user), so a row per conversation is enough.
    """

    def __init__(self, key_builder: KeyBuilder | None = None):
        self.key_builder = key_builder or DefaultKeyBuilder(with_bot_id=True)

    def _key(self, key: StorageKey) -> str:
        return self.key_builder.build(key)

    async def _get_row(self, session, key: StorageKey) -> FsmState | None:
        return await session.get(FsmState, self._key(key))

    async def set_state(self, key: StorageKey, state: str | State | None = None) -> None:
        value = state.state if isinstance(state, State) else state
        async with AsyncSessionLocal() as session:
            row = await self._get_row(session, key)
            if row is None:
                if value is None:
                    return
                row = FsmState(key=self._key(key), data="{}")
                session.add(row)
            row.state = value
            await self._save(session, row)

    async def get_state(self, key: StorageKey) -> str | None:
        async with AsyncSessionLocal() as session:
            row = await self._get_row(session, key)
            return row.state if row else None

    async def set_data(self, key: StorageKey, data: Mapping[str, Any]) -> None:
        async with AsyncSessionLocal() as session:
            row = await self._get_row(session, key)
            if row is None:
                if not data:
                    return
                row = FsmState(key=self._key(key), state=None)
                session.add(row)
            row.data = json.dumps(dict(data))
            await self._save(session, row)

    async def get_data(self, key: StorageKey) -> dict[str, Any]:
        async with AsyncSessionLocal() as session:
            row = await self._get_row(session, key)
            return json.loads(row.data) if row and row.data else {}

    async def _save(self, session, row: FsmState) -> None:
        """Commits the row, deleting it when the conversation has neither a state nor data."""
        if row.state is None and (not row.data or row.data == "{}"):
            if inspect(row).persistent:
                await session.delete(row)
            else:
                session.expunge(row)
        await session.commit()

    async def close(self) -> None:
        pass
