from aiogram.methods import EditMessageText

from conftest import ITEM_ID, OWNER_ID, RECEIPT_ID, STRANGER_ID, load_receipt, texts
from db.database import AsyncSessionLocal
from db.models import Receipt


# --- Ownership (IDOR) ---

async def test_stranger_cannot_change_item_category(tg):
    await tg.click(STRANGER_ID, f"set_item_cat:{ITEM_ID}:{RECEIPT_ID}:Other")
    assert (await load_receipt(RECEIPT_ID)).items[0].category == "Groceries"


async def test_stranger_cannot_rename_item(tg):
    await tg.click(STRANGER_ID, f"edit_item_field:name:{ITEM_ID}:{RECEIPT_ID}")
    await tg.send(STRANGER_ID, "hacked")
    assert (await load_receipt(RECEIPT_ID)).items[0].name == "milk"


async def test_stranger_cannot_edit_receipt(tg):
    await tg.click(STRANGER_ID, f"edit_field:store_name:{RECEIPT_ID}")
    await tg.send(STRANGER_ID, "hacked")
    assert (await load_receipt(RECEIPT_ID)).store_name == "Shop"


async def test_owner_can_change_item_category(tg):
    await tg.click(OWNER_ID, f"set_item_cat:{ITEM_ID}:{RECEIPT_ID}:Other")
    assert (await load_receipt(RECEIPT_ID)).items[0].category == "Other"


async def test_unknown_category_is_rejected(tg):
    await tg.click(OWNER_ID, f"set_item_cat:{ITEM_ID}:{RECEIPT_ID}:<b>Evil</b>")
    assert (await load_receipt(RECEIPT_ID)).items[0].category == "Groceries"


async def test_non_editable_fields_are_rejected(tg):
    await tg.click(OWNER_ID, f"edit_field:user_id:{RECEIPT_ID}")
    assert await tg.state(OWNER_ID) is None
    await tg.click(OWNER_ID, f"edit_item_field:receipt_id:{ITEM_ID}:{RECEIPT_ID}")
    assert await tg.state(OWNER_ID) is None


# --- Deleting receipts ---

async def test_owner_deletes_receipt_and_its_photo(tg, storage):
    sent = texts(await tg.click(OWNER_ID, f"delete_receipt:{RECEIPT_ID}"))
    assert any("deleted" in t for t in sent)
    assert storage.deleted == ["owner-blob"]
    async with AsyncSessionLocal() as session:
        assert await session.get(Receipt, RECEIPT_ID) is None


async def test_stranger_cannot_delete_receipt_or_photo(tg, storage):
    await tg.click(STRANGER_ID, f"delete_receipt:{RECEIPT_ID}")
    assert storage.deleted == []
    assert (await load_receipt(RECEIPT_ID)).store_name == "Shop"


async def test_storage_failure_does_not_block_deletion(tg, storage, monkeypatch):
    def broken_delete(**kwargs):
        raise ConnectionError("s3 is down")

    monkeypatch.setattr(storage, "delete_object", broken_delete)
    sent = texts(await tg.click(OWNER_ID, f"delete_receipt:{RECEIPT_ID}"))
    assert any("deleted" in t for t in sent)
    async with AsyncSessionLocal() as session:
        assert await session.get(Receipt, RECEIPT_ID) is None


# --- Edit flow (FSM) ---

async def test_menu_button_cancels_edit_and_still_works(tg):
    await tg.click(OWNER_ID, f"edit_field:store_name:{RECEIPT_ID}")
    sent = texts(await tg.send(OWNER_ID, "📊 Monthly Expenses"))
    assert await tg.state(OWNER_ID) is None
    assert any("cancelled" in t.lower() for t in sent)
    assert any("Expense Statistics" in t for t in sent)
    assert (await load_receipt(RECEIPT_ID)).store_name == "Shop"


async def test_unknown_command_cancels_edit_and_is_not_saved(tg):
    await tg.click(OWNER_ID, f"edit_field:store_name:{RECEIPT_ID}")
    await tg.send(OWNER_ID, "/foo")
    assert await tg.state(OWNER_ID) is None
    assert (await load_receipt(RECEIPT_ID)).store_name == "Shop"


async def test_start_cancels_edit_and_greets(tg):
    await tg.click(OWNER_ID, f"edit_field:store_name:{RECEIPT_ID}")
    sent = texts(await tg.send(OWNER_ID, "/start"))
    assert await tg.state(OWNER_ID) is None
    assert any("Hi!" in t for t in sent)


async def test_cancel_command(tg):
    await tg.click(OWNER_ID, f"edit_item_field:name:{ITEM_ID}:{RECEIPT_ID}")
    sent = texts(await tg.send(OWNER_ID, "/cancel"))
    assert await tg.state(OWNER_ID) is None
    assert any("cancelled" in t.lower() for t in sent)

    sent = texts(await tg.send(OWNER_ID, "/cancel"))
    assert any("Nothing to cancel" in t for t in sent)


async def test_non_text_reply_keeps_edit_state(tg):
    await tg.click(OWNER_ID, f"edit_field:store_name:{RECEIPT_ID}")
    sent = texts(await tg.send(OWNER_ID, sticker=True))
    assert await tg.state(OWNER_ID) is not None
    assert any("text message" in t for t in sent)


# --- Input validation ---

async def test_store_name_length_limit(tg):
    await tg.click(OWNER_ID, f"edit_field:store_name:{RECEIPT_ID}")
    await tg.send(OWNER_ID, "x" * 129)
    assert await tg.state(OWNER_ID) is not None
    assert (await load_receipt(RECEIPT_ID)).store_name == "Shop"


async def test_item_name_length_limit(tg):
    await tg.click(OWNER_ID, f"edit_item_field:name:{ITEM_ID}:{RECEIPT_ID}")
    await tg.send(OWNER_ID, "x" * 256)
    assert await tg.state(OWNER_ID) is not None
    assert (await load_receipt(RECEIPT_ID)).items[0].name == "milk"


async def test_store_name_is_saved_and_escaped_in_card(tg):
    await tg.click(OWNER_ID, f"edit_field:store_name:{RECEIPT_ID}")
    calls = await tg.send(OWNER_ID, "New <Shop> & Co")
    assert await tg.state(OWNER_ID) is None
    assert (await load_receipt(RECEIPT_ID)).store_name == "New <Shop> & Co"
    edited = [m.text for m in calls if isinstance(m, EditMessageText)]
    assert edited and "New &lt;Shop&gt; &amp; Co" in edited[0]


async def test_invalid_amounts_are_rejected_and_state_kept(tg):
    await tg.click(OWNER_ID, f"edit_field:total_amount:{RECEIPT_ID}")
    for bad in ["nan", "inf", "-5", "1e30", "100000000", "abc"]:
        await tg.send(OWNER_ID, bad)
    assert await tg.state(OWNER_ID) is not None
    assert str((await load_receipt(RECEIPT_ID)).total_amount) == "3.00"


async def test_valid_amount_is_rounded_and_saved(tg):
    await tg.click(OWNER_ID, f"edit_field:total_amount:{RECEIPT_ID}")
    await tg.send(OWNER_ID, "12,345")
    assert await tg.state(OWNER_ID) is None
    assert str((await load_receipt(RECEIPT_ID)).total_amount) == "12.35"


async def test_invalid_date_is_rejected(tg):
    await tg.click(OWNER_ID, f"edit_field:date:{RECEIPT_ID}")
    await tg.send(OWNER_ID, "29.03.2026")
    assert await tg.state(OWNER_ID) is not None
    await tg.send(OWNER_ID, "2026-03-29")
    assert await tg.state(OWNER_ID) is None
    assert str((await load_receipt(RECEIPT_ID)).date) == "2026-03-29"


async def test_item_price_updates_receipt_total(tg):
    await tg.click(OWNER_ID, f"edit_item_field:total_price:{ITEM_ID}:{RECEIPT_ID}")
    await tg.send(OWNER_ID, "abc")
    assert await tg.state(OWNER_ID) is not None
    await tg.send(OWNER_ID, "7.5")
    receipt = await load_receipt(RECEIPT_ID)
    assert str(receipt.items[0].total_price) == "7.50"
    assert str(receipt.total_amount) == "7.50"


async def test_item_price_can_be_a_discount(tg):
    await tg.click(OWNER_ID, f"edit_item_field:total_price:{ITEM_ID}:{RECEIPT_ID}")
    await tg.send(OWNER_ID, "-2,5")
    assert await tg.state(OWNER_ID) is None
    receipt = await load_receipt(RECEIPT_ID)
    assert str(receipt.items[0].total_price) == "-2.50"


async def test_receipt_total_still_cannot_be_negative(tg):
    await tg.click(OWNER_ID, f"edit_field:total_amount:{RECEIPT_ID}")
    await tg.send(OWNER_ID, "-5")
    assert await tg.state(OWNER_ID) is not None
    assert str((await load_receipt(RECEIPT_ID)).total_amount) == "3.00"
