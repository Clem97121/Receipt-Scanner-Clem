from aiogram import Router

from handlers import common, edit, family, manual, photo, receipts, stats


def get_routers() -> list[Router]:
    """Returns all routers in the order the dispatcher must try them.

    common goes first: /cancel and the edit interrupter must see menu buttons and commands
    before the stats/receipts handlers do; edit's value handlers only match inside edit states.
    """
    return [
        common.router,
        stats.router,
        receipts.router,
        family.router,
        manual.router,
        edit.router,
        photo.router,
    ]
