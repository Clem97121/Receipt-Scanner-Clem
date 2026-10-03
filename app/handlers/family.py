import html
import logging

from aiogram import F, Router, types
from aiogram.filters import Command

from db.database import AsyncSessionLocal
from db.family import (
    INVITE_LIFETIME,
    INVITE_PREFIX,
    JoinStatus,
    create_invite,
    get_display_name,
    get_family_members,
    join_family,
    leave_family,
)
from keyboards import BTN_FAMILY, get_family_keyboard, get_family_leave_confirm_keyboard, get_main_reply_keyboard

router = Router(name="family")

JOIN_REPLIES = {
    JoinStatus.JOINED: "✅ <b>You joined the family!</b>\n\nReceipts and statistics are now shared between all members.",
    JoinStatus.ALREADY_MEMBER: "ℹ️ You're already in this family.",
    JoinStatus.INVALID_INVITE: "❌ This invite link is invalid, already used or expired. Ask for a new one.",
    JoinStatus.IN_OTHER_FAMILY: (
        "❌ You're already in another family.\n\n"
        f"Leave it first ({BTN_FAMILY} → 🚪 Leave family), then open the invite link again."
    ),
}


async def family_screen(user_id: int) -> tuple[str, types.InlineKeyboardMarkup]:
    """Builds the family overview text and keyboard for the user."""
    async with AsyncSessionLocal() as session:
        members = await get_family_members(session, user_id)

    if not members:
        text = (
            "👨‍👩‍👧 <b>Family</b>\n\n"
            "You're not in a family yet.\n"
            "Invite someone to share receipts and statistics: everyone in a family "
            "sees, edits and deletes all receipts of the family."
        )
        return text, get_family_keyboard(in_family=False)

    lines = [
        f"• {html.escape(member.display_name)}{' (you)' if member.telegram_id == user_id else ''}"
        for member in members
    ]
    text = (
        "👨‍👩‍👧 <b>Your family</b>\n\n"
        + "\n".join(lines)
        + "\n\nAll receipts and statistics are shared between members."
    )
    return text, get_family_keyboard(in_family=True)


@router.message(F.text == BTN_FAMILY)
@router.message(Command("family"))
async def show_family_handler(message: types.Message):
    """Handler for the family button or /family command."""
    text, keyboard = await family_screen(message.from_user.id)
    await message.answer(text, parse_mode="HTML", reply_markup=keyboard)


@router.callback_query(F.data == "family_menu")
async def family_menu_handler(callback: types.CallbackQuery):
    """Returns to the family overview (e.g. after cancelling leaving)."""
    text, keyboard = await family_screen(callback.from_user.id)
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data == "family_invite")
async def family_invite_handler(callback: types.CallbackQuery):
    """Creates a one-time invite link, creating the family on first use."""
    user = callback.from_user
    async with AsyncSessionLocal() as session:
        invite = await create_invite(session, user.id, user.username, user.full_name)

    bot_user = await callback.bot.me()
    link = f"https://t.me/{bot_user.username}?start={INVITE_PREFIX}{invite.token}"
    hours = int(INVITE_LIFETIME.total_seconds() // 3600)
    await callback.message.answer(
        "🔗 <b>Family invite</b>\n\n"
        f"Send this link to the person you want to add. It works once and expires in {hours} hours:\n\n"
        f"{html.escape(link)}",
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    await callback.answer()


@router.callback_query(F.data == "family_leave")
async def family_leave_handler(callback: types.CallbackQuery):
    """Asks for confirmation before leaving the family."""
    await callback.message.edit_text(
        "🚪 <b>Leave the family?</b>\n\n"
        "Your receipts stay yours, but you'll stop seeing the family's receipts and statistics.",
        parse_mode="HTML",
        reply_markup=get_family_leave_confirm_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "family_leave_confirm")
async def family_leave_confirm_handler(callback: types.CallbackQuery):
    """Removes the user from their family."""
    async with AsyncSessionLocal() as session:
        left = await leave_family(session, callback.from_user.id)

    text, keyboard = await family_screen(callback.from_user.id)
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
    await callback.answer("You left the family." if left else "You're not in a family.")


async def join_family_from_link(message: types.Message, token: str) -> None:
    """Handles /start join_<token>: joins the family and notifies the person who sent the invite."""
    user = message.from_user
    async with AsyncSessionLocal() as session:
        result = await join_family(session, token, user.id, user.username, user.full_name)
        new_member_name = await get_display_name(session, user.id) if result.status == JoinStatus.JOINED else None

    await message.answer(JOIN_REPLIES[result.status], parse_mode="HTML", reply_markup=get_main_reply_keyboard())

    if result.status == JoinStatus.JOINED and result.inviter_id:
        try:
            await message.bot.send_message(
                result.inviter_id,
                f"👨‍👩‍👧 <b>{html.escape(new_member_name)}</b> joined your family!",
                parse_mode="HTML",
            )
        except Exception:
            logging.warning(f"Could not notify inviter {result.inviter_id} about a new family member")
