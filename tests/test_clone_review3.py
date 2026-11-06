"""Review probes (clones): each test proves a defect and FAILS on the current code."""
from __future__ import annotations

from app.db.models import BotStatus
from tests.conftest import USER_ID, App
from tests.test_clone import CLONE_ID, CLONE_USERNAME, get_bot, open_clone, set_policy


async def test_probe_pending_clone_does_not_start_when_the_policy_becomes_closed(app: App) -> None:
    """A clone waiting for approval must never start without a super admin's approval: re-sending its token after
    the platform was closed starts it."""
    await set_policy(app, "approval")
    token = app.fake.add_bot(CLONE_ID, CLONE_USERNAME)
    await open_clone(app)
    await app.click(USER_ID, "Usar token")
    await app.send(USER_ID, token)
    assert (await get_bot(app, CLONE_ID)).status == BotStatus.PENDING

    await set_policy(app, "closed")  # the super admin stops new bots; this one is still waiting
    await open_clone(app)
    await app.click(USER_ID, "Usar token")  # still offered: "re-connect one of your bots"
    await app.send(USER_ID, token)
    rec = await get_bot(app, CLONE_ID)
    assert rec.status == BotStatus.PENDING, "the pending clone was started without approval"
    assert not app.manager.is_running(CLONE_ID)
