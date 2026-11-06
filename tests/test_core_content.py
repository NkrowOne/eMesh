"""Content of posts (services/content.py) and the audience / rotation helpers (services/audience.py)."""
from __future__ import annotations

import pytest

from app.db.models import Chat, ChatOrigin, ChatStatus, ChatGroup, Post, PostStatus, SchedMode
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


def test_targets_and_rotation() -> None:
    own, ext = _chat(1), _chat(2, ChatOrigin.EXTERNAL)
    assert audience.targets_chat(["all"], ext, set())
    assert audience.targets_chat(["own"], own, set()) and not audience.targets_chat(["own"], ext, set())
    assert audience.targets_chat(["g7"], ext, {7}) and not audience.targets_chat(["g7"], own, {3})
    assert audience.make_targets(["own", "ext"], [3]) == ["all"]
    assert audience.make_targets(["own"], [5, 3]) == ["own", "g3", "g5"]
    p1, p2, p3 = (Post(id=i, targets=["all"]) for i in (1, 2, 3))
    pool = audience.rotation_pool([p1, p2, p3], own, set())
    assert audience.next_in_rotation(pool, None).id == 1
    assert audience.next_in_rotation(pool, 1).id == 2
    assert audience.next_in_rotation(pool, 3).id == 1  # wraps around
    assert audience.next_in_rotation(pool, 2, "random").id != 2


def test_source_is_the_first_group_with_own_frequency() -> None:
    a = ChatGroup(id=1, name="A", freq=None, sort=0)
    b = ChatGroup(id=2, name="B", freq={"mode": "interval", "every": 60}, sort=5)
    c = ChatGroup(id=3, name="C", freq={"mode": "interval", "every": 30}, sort=1)
    groups = {g.id: g for g in (a, b, c)}
    assert audience.source_of({1}, groups) is None
    assert audience.source_of({1, 2, 3}, groups) is c


async def test_plan_slot_gives_each_chat_its_next_post(app: App) -> None:
    async with app.db() as s:
        chats = [Chat(bot_id=MAIN_BOT_ID, chat_id=-1001 - i, title=f"C{i}", status=ChatStatus.APPROVED,
                      rights_ok=True, origin=ChatOrigin.OWN) for i in range(3)]
        s.add_all(chats)
        await s.flush()
        chats[1].rot_last_post_id = None
        posts = [Post(bot_id=MAIN_BOT_ID, name=f"P{i}", text="x", targets=["all"], mode=SchedMode.ROTATION,
                      status=PostStatus.ACTIVE) for i in range(2)]
        s.add_all(posts)
        await s.flush()
        chats[0].rot_last_post_id = posts[0].id
        chats[2].admin_paused = True
        plan = await audience.plan_slot(s, MAIN_BOT_ID, None, "Europe/Madrid", "seq")
    assert {pid: sorted(c.title for c in cs) for pid, cs in plan.items()} == {posts[1].id: ["C0"],
                                                                                posts[0].id: ["C1"]}
    assert SUPER_ID  # the fixture user exists
