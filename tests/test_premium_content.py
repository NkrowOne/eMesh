"""Premium (custom) emoji in posts: marked text, button icons, signature / vault copy and the plain fallback of
``deliver`` / ``edit_delivery``."""
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from aiogram.types import Chat as TgChat
from aiogram.types import Message, MessageEntity

from app.db.models import Post
from app.services import content
from tests.conftest import SUPER_ID, App
from tests.test_posts_buttons import open_editor
from tests.test_posts_helpers import (  # noqa: F401 - fixtures
    add_post,
    button_texts,
    engine_fixture,
    keyboard,
    load,
)

CID = "5368324170671202286"
CID2 = "5368324170671202287"


def u16(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


def entities_for(text: str, *pairs: tuple[str, str]) -> list[dict[str, Any]]:
    """Custom emoji entities (UTF-16 offsets) for ``(emoji, id)`` pairs, each found in order in ``text``."""
    out, pos = [], 0
    for emoji, cid in pairs:
        idx = text.index(emoji, pos)
        out.append({"type": "custom_emoji", "offset": u16(text[:idx]), "length": u16(emoji), "custom_emoji_id": cid})
        pos = idx + len(emoji)
    return out


def msg(text: str, *pairs: tuple[str, str], caption: bool = False) -> Message:
    ents = [MessageEntity(**e) for e in entities_for(text, *pairs)]
    key = "caption" if caption else "text"
    return Message(message_id=1, date=datetime.now(UTC), chat=TgChat(id=1, type="private"),
                   **{key: text, "caption_entities" if caption else "entities": ents})


def parse(text: str, *pairs: tuple[str, str]) -> list[list[dict[str, str]]]:
    return content.parse_buttons(content.marked_text(msg(text, *pairs)))


WEB = {"text": "Web", "icon": CID, "emoji": "🔥", "url": "https://example.com"}


# --------------------------------------------------------------------------- pure helpers
def test_icon_from_leading_custom_emoji() -> None:
    assert parse("🔥 Web - https://example.com", ("🔥", CID)) == [[WEB]]


def test_utf16_offsets_with_astral_emoji_before() -> None:
    # a regular emoji before the custom one: the custom one is not at the start, so no icon, text keeps plain emoji
    rows = parse("😀 🔥 Web - https://example.com", ("🔥", CID))
    assert rows == [[{"text": "😀 🔥 Web", "url": "https://example.com"}]]
    # on the second line the offsets of the first line (with a 2-unit emoji) must not shift the entity
    text = "😀 A - https://a.com\n🔥 Web - https://example.com"
    assert parse(text, ("🔥", CID)) == [[{"text": "😀 A", "url": "https://a.com"}], [WEB]]


def test_multi_codepoint_emoji() -> None:
    thumbs = "👍🏻"
    rows = parse(f"😀 x - https://x.com\n{thumbs} Web - https://example.com", (thumbs, CID))
    assert rows[1] == [{"text": "Web", "icon": CID, "emoji": thumbs, "url": "https://example.com"}]
    assert content.marked_text(msg(f"{thumbs} hi", (thumbs, CID))).startswith(f"\ue000{CID}\ue001{thumbs}\ue002")


def test_marked_text_roundtrip_and_unmark() -> None:
    text = "😀 a 🔥 b 👍🏻 c"
    marked = content.marked_text(msg(text, ("🔥", CID), ("👍🏻", CID2)))
    assert marked != text and CID in marked and CID2 in marked
    assert content.unmark(marked) == text
    assert content.marked_text(msg("sin nada")) == "sin nada"


def test_marked_text_caption_and_overlapping_entities() -> None:
    assert content.unmark(content.marked_text(msg("📸 foto", ("📸", CID), caption=True))) == "📸 foto"
    m = Message(message_id=1, date=datetime.now(UTC), chat=TgChat(id=1, type="private"), text="🔥🔥",
                entities=[MessageEntity(type="custom_emoji", offset=0, length=2, custom_emoji_id=CID),
                          MessageEntity(type="custom_emoji", offset=0, length=2, custom_emoji_id=CID2)])
    assert content.unmark(content.marked_text(m)) == "🔥🔥"


def test_custom_emoji_in_middle_or_in_copy_value_is_plain() -> None:
    assert parse("Web 🔥 oficial - https://example.com", ("🔥", CID)) == [
        [{"text": "Web 🔥 oficial", "url": "https://example.com"}]]
    assert parse("Código - copiar: 🔥PROMO", ("🔥", CID)) == [[{"text": "Código", "copy": "🔥PROMO"}]]


def test_only_the_emoji_keeps_plain_text() -> None:
    assert parse("🔥 - https://example.com", ("🔥", CID)) == [[{"text": "🔥", "url": "https://example.com"}]]
    assert content.label_of(content.marked_text(msg("🔥", ("🔥", CID)))) == {"text": "🔥"}
    assert content.label_of(content.marked_text(msg("🔥 Web", ("🔥", CID)))) == {"text": "Web", "icon": CID,
                                                                                  "emoji": "🔥"}


def test_bracketed_button_and_color_tail() -> None:
    assert parse("[🔥 Web - https://x.com]", ("🔥", CID)) == [
        [{"text": "Web", "icon": CID, "emoji": "🔥", "url": "https://x.com"}]]
    colored = parse("🔥 Web - https://example.com 🟢", ("🔥", CID))
    assert colored == [[{**WEB, "style": "success"}]]
    two = parse("🔥 A - https://a.com && 🔥 B - https://b.com 🔴", ("🔥", CID), ("🔥", CID2))
    assert two[0][0]["icon"] == CID and two[0][1] == {"text": "B", "icon": CID2, "emoji": "🔥",
                                                      "url": "https://b.com", "style": "danger"}


def test_format_buttons_and_roundtrip() -> None:
    rows = [[WEB], [{"text": "Código", "icon": CID, "emoji": "🔥", "copy": "X", "style": "primary"}]]
    assert content.format_buttons([[WEB]]) == "🔥 Web - https://example.com"
    assert content.button_label(WEB) == "🔥 Web" and content.button_label({"text": "Web"}) == "Web"
    assert content.format_buttons(rows).splitlines()[1] == "🔥 Código - copiar: X 🔵"


def test_make_button_and_markup_icons() -> None:
    on = content.make_button(WEB)
    assert on.text == "Web" and on.icon_custom_emoji_id == CID
    off = content.make_button(WEB, icons=False)
    assert off.text == "🔥 Web" and off.icon_custom_emoji_id is None
    markup = content.build_markup([[WEB]], icons=False)
    assert markup is not None and markup.inline_keyboard[0][0].text == "🔥 Web"
    assert content.make_button({"text": "A", "icon": "abc", "url": "https://a.com"}).icon_custom_emoji_id is None


def test_private_use_characters_cannot_forge_an_icon() -> None:
    forged = f"{CID}🔥 Web - https://example.com"
    marked = content.marked_text(msg(forged))
    assert not any(c in marked for c in "")
    assert content.parse_buttons(marked) == [[{"text": f"{CID}🔥 Web", "url": "https://example.com"}]]
    assert "icon" not in content.parse_buttons(marked)[0][0]
    assert "icon" not in content.label_of(marked)


# --------------------------------------------------------------------------- post helpers
def post_with(**values: Any) -> Post:
    base: dict[str, Any] = {"kind": "text", "text": "hola", "buttons": [], "media": {}, "link_preview": False,
                            "caption_above": False, "spoiler": False}
    return Post(**{**base, **values})


def test_has_premium() -> None:
    assert not content.has_premium(post_with())
    assert content.has_premium(post_with(text='x <tg-emoji emoji-id="1">🔥</tg-emoji>'))
    assert content.has_premium(post_with(buttons=[[WEB]]))
    assert not content.has_premium(post_with(buttons=[[{"text": "Web", "url": "https://example.com"}]]))


def test_signature_changes_and_ignores_extra_media() -> None:
    base = post_with(kind="photo", media={"1": "fileA"})
    sig = content.signature(base)
    assert content.signature(post_with(kind="photo", media={"1": "fileA", "2": "fileB"})) == sig
    assert content.signature(post_with(kind="photo", media={"1": "fileA"}, text="otro")) != sig
    assert content.signature(post_with(kind="photo", media={"1": "fileA"}, buttons=[[WEB]])) != sig
    assert content.signature(post_with(kind="photo", media={"1": "fileA"}, caption_above=True)) != sig
    assert content.signature(post_with(kind="photo", media={"1": "fileZ"})) != sig


def test_vault_copy() -> None:
    p = post_with(buttons=[[WEB]], vault_chat_id=-100, vault_msg_id=7)
    p.vault_sig = content.signature(p)
    assert content.vault_copy(p) == (-100, 7)
    p.text = "cambiado"
    assert content.vault_copy(p) is None  # signature differs
    p.vault_sig = content.signature(p)
    assert content.vault_copy(p) == (-100, 7)
    p.vault_msg_id = None
    assert content.vault_copy(p) is None
    p.vault_msg_id, p.vault_chat_id = 7, None
    assert content.vault_copy(p) is None
    plain = post_with(vault_chat_id=-100, vault_msg_id=7)
    plain.vault_sig = content.signature(plain)
    assert content.vault_copy(plain) is None  # nothing premium in it


def test_custom_emoji_in() -> None:
    assert content.custom_emoji_in(msg("🔥 hi", ("🔥", CID)))
    assert not content.custom_emoji_in(msg("hi"))
    assert content.custom_emoji_in(msg("🔥 hi", ("🔥", CID), caption=True))


# --------------------------------------------------------------------------- deliver / edit_delivery
TG_TEXT = '<tg-emoji emoji-id="5368324170671202286">🔥</tg-emoji> Hola'
PREMIUM_BUTTONS = [[WEB]]
CHAT = -1001234567890


async def channel(app: App) -> int:
    await app.add_chat(CHAT, SUPER_ID)
    return CHAT


def refuse_text(app: App, times: int = 1) -> None:
    app.fake.fail("sendMessage", description="Bad Request: custom emoji can't be used here", times=times,
                  when=lambda p: "tg-emoji" in str(p.get("text")))


async def test_deliver_falls_back_to_plain_text(app: App) -> None:
    chat = await channel(app)
    refuse_text(app)
    post = post_with(text=TG_TEXT)
    called: list[int] = []
    await content.deliver(app.main_bot, chat, post, on_plain=lambda: called.append(1))
    sent = app.fake.calls_of("sendMessage", chat_id=chat)
    assert len(sent) == 2 and "tg-emoji" in sent[0].params["text"]
    assert sent[1].params["text"] == "🔥 Hola" and called == [1]


async def test_deliver_premium_ok_does_not_call_on_plain(app: App) -> None:
    chat = await channel(app)
    called: list[int] = []
    await content.deliver(app.main_bot, chat, post_with(text=TG_TEXT), on_plain=lambda: called.append(1))
    sent = app.fake.calls_of("sendMessage", chat_id=chat)
    assert len(sent) == 1 and "tg-emoji" in sent[0].params["text"] and not called


async def test_deliver_premium_false_sends_plain_at_once(app: App) -> None:
    chat = await channel(app)
    called: list[int] = []
    post = post_with(text=TG_TEXT, buttons=PREMIUM_BUTTONS)
    await content.deliver(app.main_bot, chat, post, premium=False, on_plain=lambda: called.append(1))
    sent = app.fake.calls_of("sendMessage", chat_id=chat)
    assert len(sent) == 1 and sent[0].params["text"] == "🔥 Hola" and not called
    kb = sent[0].params["reply_markup"]["inline_keyboard"]
    assert kb[0][0]["text"] == "🔥 Web" and "icon_custom_emoji_id" not in kb[0][0]


async def test_deliver_icons_refused(app: App) -> None:
    chat = await channel(app)
    app.fake.fail("sendMessage", description="Bad Request: icon_custom_emoji_id is not allowed",
                  when=lambda p: "icon_custom_emoji_id" in str(p.get("reply_markup")))
    called: list[int] = []
    post = post_with(text="Hola", buttons=PREMIUM_BUTTONS)
    await content.deliver(app.main_bot, chat, post, on_plain=lambda: called.append(1))
    sent = app.fake.calls_of("sendMessage", chat_id=chat)
    assert len(sent) == 2 and "icon_custom_emoji_id" in str(sent[0].params["reply_markup"])
    kb = sent[1].params["reply_markup"]["inline_keyboard"]
    assert kb[0][0]["text"] == "🔥 Web" and "icon_custom_emoji_id" not in kb[0][0] and called == [1]


async def test_deliver_icons_sent_when_allowed(app: App) -> None:
    chat = await channel(app)
    await content.deliver(app.main_bot, chat, post_with(text="Hola", buttons=PREMIUM_BUTTONS))
    sent = app.fake.calls_of("sendMessage", chat_id=chat)
    assert len(sent) == 1
    button = sent[0].params["reply_markup"]["inline_keyboard"][0][0]
    assert button["text"] == "Web" and button["icon_custom_emoji_id"] == CID


async def test_deliver_unrelated_bad_request_is_raised(app: App) -> None:
    from aiogram.exceptions import TelegramBadRequest
    chat = await channel(app)
    app.fake.fail("sendMessage", description="Bad Request: chat not found")
    with pytest.raises(TelegramBadRequest, match="chat not found"):
        await content.deliver(app.main_bot, chat, post_with(text=TG_TEXT))
    assert len(app.fake.calls_of("sendMessage", chat_id=chat)) == 1


async def test_deliver_non_premium_post_is_not_retried(app: App) -> None:
    from aiogram.exceptions import TelegramBadRequest
    chat = await channel(app)
    app.fake.fail("sendMessage", description="Bad Request: custom emoji can't be used here")
    with pytest.raises(TelegramBadRequest):
        await content.deliver(app.main_bot, chat, post_with(text="Hola"))
    assert len(app.fake.calls_of("sendMessage", chat_id=chat)) == 1


async def test_edit_delivery_fallback(app: App) -> None:
    chat = await channel(app)
    sent = await content.deliver(app.main_bot, chat, post_with(text="viejo"))
    app.fake.fail("editMessageText", description="Bad Request: can't parse entities: emoji",
                  when=lambda p: "tg-emoji" in str(p.get("text")))
    post = post_with(text=TG_TEXT, buttons=PREMIUM_BUTTONS)
    await content.edit_delivery(app.main_bot, chat, sent.message_id, post)
    edits = app.fake.calls_of("editMessageText", chat_id=chat)
    assert len(edits) == 2 and "tg-emoji" in edits[0].params["text"]
    assert edits[1].params["text"] == "🔥 Hola"
    kb = edits[1].params["reply_markup"]["inline_keyboard"]
    assert kb[0][0]["text"] == "🔥 Web" and "icon_custom_emoji_id" not in kb[0][0]


async def test_edit_delivery_icons_refused_and_unrelated_error(app: App) -> None:
    from aiogram.exceptions import TelegramBadRequest
    chat = await channel(app)
    sent = await content.deliver(app.main_bot, chat, post_with(text="viejo"))
    app.fake.fail("editMessageText", description="Bad Request: icon not allowed",
                  when=lambda p: "icon_custom_emoji_id" in str(p.get("reply_markup")))
    await content.edit_delivery(app.main_bot, chat, sent.message_id, post_with(text="nuevo", buttons=PREMIUM_BUTTONS))
    edits = app.fake.calls_of("editMessageText", chat_id=chat)
    assert len(edits) == 2 and edits[1].params["reply_markup"]["inline_keyboard"][0][0]["text"] == "🔥 Web"

    app.fake.reset_calls()
    app.fake.fail("editMessageText", description="Bad Request: message to edit not found")
    with pytest.raises(TelegramBadRequest, match="not found"):
        await content.edit_delivery(app.main_bot, chat, sent.message_id, post_with(text=TG_TEXT))
    assert len(app.fake.calls_of("editMessageText", chat_id=chat)) == 1


# --------------------------------------------------------------------------- through the UI
async def test_add_button_step_by_step_keeps_icon(app: App, engine: SimpleNamespace) -> None:
    pid = await add_post(app)
    await open_editor(app, pid)
    await app.click(SUPER_ID, "Añadir botón")
    name = "🔥 Web oficial"
    await app.send(SUPER_ID, name, entities=entities_for(name, ("🔥", CID)))
    assert "➕ <b>Nuevo botón</b> · 2/4" in app.last_text(SUPER_ID)
    await app.send(SUPER_ID, "https://example.com")
    await app.click(SUPER_ID, "Verde")
    assert (await load(app, Post, pid)).buttons == [
        [{"text": "Web oficial", "icon": CID, "emoji": "🔥", "url": "https://example.com", "style": "success"}]]
    drawn = keyboard(app)[0][0]
    assert drawn["text"] == "Web oficial" and drawn["icon_custom_emoji_id"] == CID


async def test_rename_button_keeps_and_drops_icon(app: App, engine: SimpleNamespace) -> None:
    plain_btn = {"text": "Alfa", "url": "https://alfa.com"}
    pid = await add_post(app, buttons=[[plain_btn]])
    await open_editor(app, pid)
    await app.press(SUPER_ID, __import__("app.bot.routers.post_buttons", fromlist=["PbCB"]).PbCB(
        a="b", id=pid, r=0, c=0).pack())
    await app.click(SUPER_ID, "🏷 Nombre")
    name = "🔥 Beta"
    await app.send(SUPER_ID, name, entities=entities_for(name, ("🔥", CID)))
    assert (await load(app, Post, pid)).buttons == [[{"text": "Beta", "icon": CID, "emoji": "🔥",
                                                      "url": "https://alfa.com"}]]
    await app.click(SUPER_ID, "🏷 Nombre")
    await app.send(SUPER_ID, "Gamma")
    assert (await load(app, Post, pid)).buttons == [[{"text": "Gamma", "url": "https://alfa.com"}]]


async def test_write_all_keeps_icons(app: App, engine: SimpleNamespace) -> None:
    pid = await add_post(app)
    await open_editor(app, pid)
    await app.click(SUPER_ID, "Escribirlos todos")
    text = "🔥 Uno - https://uno.com 🔴 && Dos - @doscanal\n😀 x - https://x.com\n🚀 Tres - copiar: 3"
    await app.send(SUPER_ID, text, entities=entities_for(text, ("🔥", CID), ("🚀", CID2)))
    assert (await load(app, Post, pid)).buttons == [
        [{"text": "Uno", "icon": CID, "emoji": "🔥", "url": "https://uno.com", "style": "danger"},
         {"text": "Dos", "url": "https://t.me/doscanal"}],
        [{"text": "😀 x", "url": "https://x.com"}],
        [{"text": "Tres", "icon": CID2, "emoji": "🚀", "copy": "3"}],
    ]
    assert keyboard(app)[0][0]["icon_custom_emoji_id"] == CID
