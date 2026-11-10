"""Content of posts (services/content.py) and the audience helpers (services/audience.py)."""
from __future__ import annotations

import pytest

from app.db.models import Chat, ChatGroup, ChatOrigin, ChatStatus, GroupChat, Post, PostStatus, SchedMode
from app.services import audience, content
from tests.conftest import MAIN_BOT_ID, SUPER_ID, App


def test_parse_buttons_rows_colors_and_copy() -> None:
    rows = content.parse_buttons(
        "Web - https://example.com 🟢\n"
        "Canal - @micanal && Grupo - t.me/migrupo #rojo\n"
        "Código - copiar: PROMO10 🔵"
    )
    assert rows == [
        [{"text": "Web", "url": "https://example.com", "style": "success"}],
        [{"text": "Canal", "url": "https://t.me/micanal"},
         {"text": "Grupo", "url": "https://t.me/migrupo", "style": "danger"}],
        [{"text": "Código", "copy": "PROMO10", "style": "primary"}],
    ]
    assert content.parse_buttons(content.format_buttons(rows)) == rows
    markup = content.build_markup(rows)
    assert markup is not None
    first = markup.inline_keyboard[0][0]
    assert first.style == "success" and first.url == "https://example.com"
    assert markup.inline_keyboard[2][0].copy_text is not None


@pytest.mark.parametrize(("text", "key"), [
    ("Sin enlace", "content.err.format"),
    ("Web - https://nohost", "content.err.url"),
    ("", "content.err.empty_buttons"),
    ("A - https://a.com && " * 8 + "B - https://b.com", "content.err.row"),
])
def test_parse_buttons_errors(text: str, key: str) -> None:
    with pytest.raises(content.ButtonsError) as err:
        content.parse_buttons(text)
    assert err.value.key == key


def test_default_name() -> None:
    post = Post(kind="photo", text="<b>Oferta</b> de hoy\nmás texto", media={})
    assert content.default_name(post, "es") == "Oferta de hoy"
    assert content.default_name(Post(kind="video", text=None), "es") == "🎬 Vídeo"


def _chat(pk: int, origin: str = ChatOrigin.OWN) -> Chat:
    return Chat(id=pk, bot_id=1, chat_id=-100 - pk, origin=origin, status=ChatStatus.APPROVED, rights_ok=True,
                admin_paused=False, owner_paused=False)


def test_targets() -> None:
    own, ext = _chat(1), _chat(2, ChatOrigin.EXTERNAL)
    assert audience.targets_chat(["all"], ext, set())
    assert audience.targets_chat(["own"], own, set()) and not audience.targets_chat(["own"], ext, set())
    assert audience.targets_chat(["g7"], ext, {7}) and not audience.targets_chat(["g7"], own, {3})
    assert audience.make_targets(["own", "ext"], [3]) == ["all"]
    assert audience.make_targets(["own"], [5, 3]) == ["own", "g3", "g5"]


async def test_audience_is_the_sendable_chats_it_targets(app: App) -> None:
    async with app.db() as s:
        chats = [Chat(bot_id=MAIN_BOT_ID, chat_id=-1001 - i, title=f"C{i}", status=ChatStatus.APPROVED,
                      rights_ok=True, origin=ChatOrigin.OWN) for i in range(3)]
        s.add_all(chats)
        group = ChatGroup(bot_id=MAIN_BOT_ID, name="Cine")
        s.add(group)
        await s.flush()
        s.add_all([GroupChat(group_id=group.id, chat_pk=chats[i].id) for i in (0, 2)])
        chats[2].admin_paused = True
        post = Post(bot_id=MAIN_BOT_ID, name="P", text="x", targets=[f"g{group.id}"], mode=SchedMode.OWN,
                    status=PostStatus.ACTIVE)
        s.add(post)
        await s.flush()
        assert [c.title for c in await audience.audience(s, post)] == ["C0"]
        assert [c.title for c in await audience.audience(s, post, sendable_only=False)] == ["C0", "C2"]
        post.targets = ["all"]
        assert [c.title for c in await audience.audience(s, post)] == ["C0", "C1"]
    assert SUPER_ID  # the fixture user exists
