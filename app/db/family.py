import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.crud import _month_filter, visible_to
from db.models import Family, FamilyInvite, Receipt, User

INVITE_LIFETIME = timedelta(hours=24)
INVITE_PREFIX = "join_"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class JoinStatus(Enum):
    JOINED = "joined"
    ALREADY_MEMBER = "already_member"
    INVALID_INVITE = "invalid_invite"
    IN_OTHER_FAMILY = "in_other_family"


@dataclass
class JoinResult:
    status: JoinStatus
    inviter_id: Optional[int] = None


async def ensure_user(
    session: AsyncSession, telegram_id: int, username: Optional[str] = None, full_name: Optional[str] = None
) -> User:
    """Returns the user row, creating it if needed and refreshing the display names Telegram sent."""
    user = await session.get(User, telegram_id)
    if user is None:
        user = User(telegram_id=telegram_id)
        session.add(user)
    if username is not None:
        user.username = username[:64]
    if full_name is not None:
        user.full_name = full_name[:128]
    await session.flush()
    return user


async def get_family_members(session: AsyncSession, user_id: int) -> List[User]:
    """Returns all members of the user's family (including the user), or an empty list if not in a family."""
    user = await session.get(User, user_id)
    if user is None or user.family_id is None:
        return []
    result = await session.execute(
        select(User).where(User.family_id == user.family_id).order_by(User.created_at, User.telegram_id)
    )
    return list(result.scalars().all())


async def create_invite(
    session: AsyncSession, user_id: int, username: Optional[str] = None, full_name: Optional[str] = None
) -> FamilyInvite:
    """Creates a one-time invite; a user without a family gets a new family first."""
    user = await ensure_user(session, user_id, username, full_name)
    if user.family_id is None:
        family = Family()
        session.add(family)
        await session.flush()
        user.family_id = family.id

    invite = FamilyInvite(
        token=secrets.token_urlsafe(12),
        family_id=user.family_id,
        created_by=user_id,
        expires_at=utc_now() + INVITE_LIFETIME,
    )
    session.add(invite)
    await session.commit()
    return invite


async def _count_members(session: AsyncSession, family_id: int) -> int:
    result = await session.execute(select(func.count(User.telegram_id)).where(User.family_id == family_id))
    return result.scalar_one()


async def join_family(
    session: AsyncSession, token: str, user_id: int, username: Optional[str] = None, full_name: Optional[str] = None
) -> JoinResult:
    """Adds the user to the family of a valid, unused, unexpired invite and marks the invite as used.

    A user who is alone in their own family moves over (the empty family is deleted);
    a user sharing a family with others must leave it first.
    """
    invite = (await session.execute(
        select(FamilyInvite).where(
            FamilyInvite.token == token,
            FamilyInvite.used_by.is_(None),
            FamilyInvite.expires_at > utc_now(),
        )
    )).scalar_one_or_none()
    if invite is None:
        return JoinResult(JoinStatus.INVALID_INVITE)

    user = await ensure_user(session, user_id, username, full_name)
    if user.family_id == invite.family_id:
        await session.commit()
        return JoinResult(JoinStatus.ALREADY_MEMBER)

    old_family_id = user.family_id
    if old_family_id is not None and await _count_members(session, old_family_id) > 1:
        await session.commit()
        return JoinResult(JoinStatus.IN_OTHER_FAMILY)

    user.family_id = invite.family_id
    invite.used_by = user_id
    invite.used_at = utc_now()
    await session.flush()

    if old_family_id is not None:
        old_family = await session.get(Family, old_family_id)
        if old_family is not None:
            await session.delete(old_family)

    await session.commit()
    return JoinResult(JoinStatus.JOINED, inviter_id=invite.created_by)


async def leave_family(session: AsyncSession, user_id: int) -> bool:
    """Removes the user from their family; an empty family is deleted. Returns False if not in a family."""
    user = await session.get(User, user_id)
    if user is None or user.family_id is None:
        return False

    family_id = user.family_id
    user.family_id = None
    await session.flush()

    if await _count_members(session, family_id) == 0:
        family = await session.get(Family, family_id)
        if family is not None:
            await session.delete(family)

    await session.commit()
    return True


async def get_monthly_member_totals(
    session: AsyncSession, user_id: int, year: int, month: int
) -> List[tuple[str, Decimal]]:
    """Returns (display name, total) per family member who has receipts in the month, largest first."""
    result = await session.execute(
        select(User, func.sum(Receipt.total_amount))
        .join(Receipt, Receipt.user_id == User.telegram_id)
        .where(visible_to(user_id), _month_filter(year, month))
        .group_by(User.telegram_id)
        .order_by(func.sum(Receipt.total_amount).desc())
    )
    return [(user.display_name, Decimal(str(total or 0))) for user, total in result.all()]


async def get_display_name(session: AsyncSession, user_id: int) -> Optional[str]:
    user = await session.get(User, user_id)
    return user.display_name if user else None
