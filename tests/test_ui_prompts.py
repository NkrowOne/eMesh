"""Input prompts are always the newest message of the chat, so nothing covers them: the panel they replace is
deleted, a new prompt replaces the previous one, and once answered the next panel takes its place."""
from __future__ import annotations

from app.ui import common
from tests.conftest import MAIN_BOT_ID, SUPER_ID, App


def deleted(app: App) -> list[int]:
    return [int(c.params["message_id"]) for c in app.fake.calls_of("deleteMessage", chat_id=SUPER_ID)]


def last_sent(app: App) -> tuple[int, str]:
    call = app.fake.calls_of("sendMessage", chat_id=SUPER_ID)[-1]
    return int(call.result["message_id"]), str(call.params["text"])


async def open_groups(app: App) -> int:
    """The 🗂 groups panel (edited in place from the home); returns its message id."""
    await app.send(SUPER_ID, "/start")
    await app.click(SUPER_ID, "Grupos de canales")
    return int(app.last_panel(SUPER_ID).params["message_id"])


async def test_a_prompt_is_a_new_message_and_the_panel_is_deleted(app: App) -> None:
    panel = await open_groups(app)
    await app.click(SUPER_ID, "Nuevo grupo")
    prompt_id, text = last_sent(app)
    assert "Nuevo grupo de canales" in text
    assert prompt_id != panel
    assert deleted(app) == [panel]
    assert common._prompts[(MAIN_BOT_ID, SUPER_ID)] == prompt_id
    assert not [c for c in app.fake.calls_of("editMessageText", chat_id=SUPER_ID)
                if "Nuevo grupo de canales" in str(c.params.get("text"))]


async def test_a_new_prompt_replaces_the_previous_one(app: App) -> None:
    await open_groups(app)
    await app.click(SUPER_ID, "Nuevo grupo")
    first, _ = last_sent(app)
    await app.send(SUPER_ID, "x" * 80)  # too long: asked again, with the error
    second, text = last_sent(app)
    assert "⚠️" in text and second != first
    assert deleted(app)[-1] == first
    assert common._prompts[(MAIN_BOT_ID, SUPER_ID)] == second


async def test_the_answer_replaces_the_prompt_with_the_next_panel(app: App) -> None:
    await open_groups(app)
    await app.click(SUPER_ID, "Nuevo grupo")
    prompt_id, _ = last_sent(app)
    await app.send(SUPER_ID, "Cine")
    panel_id, text = last_sent(app)
    assert "Cine" in text and panel_id != prompt_id
    assert deleted(app)[-1] == prompt_id
    assert (MAIN_BOT_ID, SUPER_ID) not in common._prompts


async def test_cancel_turns_the_prompt_into_the_panel(app: App) -> None:
    await open_groups(app)
    await app.click(SUPER_ID, "Nuevo grupo")
    prompt_id, _ = last_sent(app)
    deletions = len(deleted(app))
    await app.click(SUPER_ID, "Cancelar")
    edit = app.last_panel(SUPER_ID)
    assert edit.method == "editMessageText" and int(edit.params["message_id"]) == prompt_id
    assert len(deleted(app)) == deletions  # nothing else is deleted
    assert (MAIN_BOT_ID, SUPER_ID) not in common._prompts


async def test_a_command_deletes_the_prompt_it_leaves(app: App) -> None:
    await open_groups(app)
    await app.click(SUPER_ID, "Nuevo grupo")
    prompt_id, _ = last_sent(app)
    await app.send(SUPER_ID, "/start")
    assert deleted(app)[-1] == prompt_id
    assert "Tu red de distribución" in last_sent(app)[1]
