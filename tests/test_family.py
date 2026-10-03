import re
from datetime import timedelta

from aiogram.methods import SendMessage
from sqlalchemy import select

from conftest import ITEM_ID, OTHER_RECEIPT_ID, OWNER_ID, RECEIPT_ID, STRANGER_ID, load_receipt, texts
from db.database import AsyncSessionLocal
from db.family import utc_now
from db.models import Family, FamilyInvite, User

WIFE_ID = STRANGER_ID  # the seeded second user, who owns OTHER_RECEIPT_ID
THIRD_ID = 3


async def invite_link(tg, user_id: int) -> str:
    """Presses "Invite to family" and returns the join_<token> payload from the link."""
    await tg.click(user_id, "family_menu")
    sent = texts(await tg.click(user_id, "family_invite"))
    match = re.search(r"https://t\.me/test_receipt_bot\?start=(join_[\w-]+)", "\n".join(sent))
    assert match, sent
    return match.group(1)


async def join(tg, user_id: int, payload: str) -> list[str]:
    return texts(await tg.send(user_id, f"/start {payload}"))


async def make_family(tg) -> None:
    payload = await invite_link(tg, OWNER_ID)
    sent = await join(tg, WIFE_ID, payload)
    assert any("You joined the family" in t for t in sent)


async def family_ids(user_ids) -> dict:
    async with AsyncSessionLocal() as session:
        users = (await session.execute(select(User).where(User.telegram_id.in_(user_ids)))).scalars().all()
        return {u.telegram_id: u.family_id for u in users}


# --- Joining ---

async def test_invite_link_adds_member_and_notifies_inviter(tg):
    payload = await invite_link(tg, OWNER_ID)
    calls = await tg.send(WIFE_ID, f"/start {payload}")

    ids = await family_ids([OWNER_ID, WIFE_ID])
    assert ids[OWNER_ID] is not None and ids[OWNER_ID] == ids[WIFE_ID]
    notifications = [c for c in calls if isinstance(c, SendMessage) and c.chat_id == OWNER_ID]
    assert notifications and f"Name{WIFE_ID}" in notifications[0].text


async def test_family_screen_lists_members(tg):
    await make_family(tg)
    sent = texts(await tg.send(OWNER_ID, "👨‍👩‍👧 Family"))
    assert any(f"Name{OWNER_ID} (you)" in t and f"Name{WIFE_ID}" in t for t in sent)


async def test_invite_link_works_only_once(tg):
    payload = await invite_link(tg, OWNER_ID)
    await join(tg, WIFE_ID, payload)
    sent = await join(tg, THIRD_ID, payload)
    assert any("invalid, already used or expired" in t for t in sent)
    assert (await family_ids([THIRD_ID])).get(THIRD_ID) is None


async def test_expired_invite_is_rejected(tg):
    payload = await invite_link(tg, OWNER_ID)
    async with AsyncSessionLocal() as session:
        invite = (await session.execute(select(FamilyInvite))).scalar_one()
        invite.expires_at = utc_now() - timedelta(minutes=1)
        await session.commit()

    sent = await join(tg, WIFE_ID, payload)
    assert any("invalid, already used or expired" in t for t in sent)


async def test_unknown_invite_is_rejected(tg):
    sent = await join(tg, WIFE_ID, "join_does-not-exist")
    assert any("invalid, already used or expired" in t for t in sent)


async def test_opening_own_invite_does_not_consume_it(tg):
    payload = await invite_link(tg, OWNER_ID)
    sent = await join(tg, OWNER_ID, payload)
    assert any("already in this family" in t for t in sent)
    assert any("You joined the family" in t for t in await join(tg, WIFE_ID, payload))


async def test_member_of_another_family_must_leave_first(tg):
    await make_family(tg)  # owner + wife
    payload = await invite_link(tg, THIRD_ID)
    sent = await join(tg, WIFE_ID, payload)
    assert any("already in another family" in t for t in sent)


async def test_user_alone_in_own_family_moves_and_empty_family_is_deleted(tg):
    await invite_link(tg, THIRD_ID)  # creates a family with only THIRD_ID in it
    payload = await invite_link(tg, OWNER_ID)
    sent = await join(tg, THIRD_ID, payload)
    assert any("You joined the family" in t for t in sent)

    async with AsyncSessionLocal() as session:
        families = (await session.execute(select(Family))).scalars().all()
    assert len(families) == 1


async def test_plain_start_still_greets(tg):
    sent = await join(tg, WIFE_ID, "")
    assert any("Hi!" in t for t in sent)


# --- Shared receipts ---

async def test_family_member_sees_and_edits_receipts(tg):
    await make_family(tg)

    sent = texts(await tg.click(WIFE_ID, f"view_receipt_from_list:{RECEIPT_ID}:1"))
    assert any("Shop" in t and f"Added by:</b> Name{OWNER_ID}" in t for t in sent)

    await tg.click(WIFE_ID, f"set_item_cat:{ITEM_ID}:{RECEIPT_ID}:Other")
    assert (await load_receipt(RECEIPT_ID)).items[0].category == "Other"


async def test_own_receipt_has_no_added_by_line(tg):
    await make_family(tg)
    sent = texts(await tg.click(OWNER_ID, f"view_receipt_from_list:{RECEIPT_ID}:1"))
    assert sent and all("Added by" not in t for t in sent)


async def test_family_receipts_list_includes_both_members(tg):
    await make_family(tg)
    calls = await tg.send(OWNER_ID, "📜 My Receipts")
    keyboard = [c for c in calls if isinstance(c, SendMessage)][-1].reply_markup.inline_keyboard
    callback_data = {button.callback_data for row in keyboard for button in row}
    assert f"view_receipt_from_list:{RECEIPT_ID}:1" in callback_data
    assert f"view_receipt_from_list:{OTHER_RECEIPT_ID}:1" in callback_data


async def test_family_stats_include_everyone_with_member_breakdown(tg):
    from datetime import date
    from db.models import Receipt

    async with AsyncSessionLocal() as session:
        for receipt_id in (RECEIPT_ID, OTHER_RECEIPT_ID):
            (await session.get(Receipt, receipt_id)).date = date(2026, 5, 10)
        await session.commit()

    await make_family(tg)
    sent = texts(await tg.click(OWNER_ID, "stats:2026:5"))
    stats = next(t for t in sent if "Statistics" in t)
    assert "Family Expense Statistics" in stats
    assert "<code>8.00</code>" in stats  # 3 + 5
    assert f"Name{WIFE_ID}: <code>5.00</code>" in stats and f"Name{OWNER_ID}: <code>3.00</code>" in stats


async def test_stats_without_family_have_no_member_breakdown(tg):
    sent = texts(await tg.send(OWNER_ID, "📊 Monthly Expenses"))
    assert sent and all("By Member" not in t and "Family" not in t for t in sent)


async def test_family_member_can_delete_shared_receipt(tg, storage):
    await make_family(tg)
    await tg.click(WIFE_ID, f"delete_receipt:{RECEIPT_ID}")
    assert storage.deleted == ["owner-blob"]


async def test_outsider_still_cannot_touch_family_receipts(tg):
    await make_family(tg)
    await tg.click(THIRD_ID, f"set_item_cat:{ITEM_ID}:{RECEIPT_ID}:Other")
    assert (await load_receipt(RECEIPT_ID)).items[0].category == "Groceries"
    sent = texts(await tg.click(THIRD_ID, f"view_receipt_from_list:{RECEIPT_ID}:1"))
    assert all("Shop" not in t for t in sent)


async def test_same_photo_from_family_member_is_a_duplicate(tg, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    import handlers.photo as photo_handlers
    from db.models import Receipt

    async with AsyncSessionLocal() as session:
        (await session.get(Receipt, RECEIPT_ID)).blob_name = f"{OWNER_ID}/shared-picture.jpg"
        await session.commit()

    await make_family(tg)
    monkeypatch.setattr(tg.bot, "get_file", AsyncMock(return_value=SimpleNamespace(file_path="p.jpg")))
    queue = MagicMock()
    monkeypatch.setattr(photo_handlers.process_receipt_task, "delay", queue)

    sent = texts(await tg.send(WIFE_ID, photo_file_id="wife-file-id", photo_unique_id="shared-picture"))
    queue.assert_not_called()
    assert any("already been processed" in t and f"Added by:</b> Name{OWNER_ID}" in t for t in sent)


# --- Leaving ---

async def test_leaving_makes_receipts_private_again(tg):
    await make_family(tg)
    await tg.click(WIFE_ID, "family_leave")
    await tg.click(WIFE_ID, "family_leave_confirm")

    assert (await family_ids([WIFE_ID]))[WIFE_ID] is None
    await tg.click(WIFE_ID, f"set_item_cat:{ITEM_ID}:{RECEIPT_ID}:Other")
    assert (await load_receipt(RECEIPT_ID)).items[0].category == "Groceries"


async def test_last_member_leaving_deletes_family(tg):
    await make_family(tg)
    for user_id in (WIFE_ID, OWNER_ID):
        await tg.click(user_id, "family_leave_confirm")

    async with AsyncSessionLocal() as session:
        assert (await session.execute(select(Family))).scalars().all() == []
        assert (await session.execute(select(FamilyInvite))).scalars().all() == []


async def test_leave_can_be_cancelled(tg):
    await make_family(tg)
    await tg.click(WIFE_ID, "family_leave")
    sent = texts(await tg.click(WIFE_ID, "family_menu"))
    assert any("Your family" in t for t in sent)
    assert (await family_ids([WIFE_ID]))[WIFE_ID] is not None
