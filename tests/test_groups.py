"""🗂 Grupos de canales: list, create, detail, rename, open toggle, delete and the chats of each group."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.bot.routers.groups import GrCB
from app.db.base import utcnow
from app.db.models import DEFAULT_FREQ, ChatGroup, ChatStatus, GroupChat, Post
from app.services import freq
from app.ui import fmt
from app.ui.callbacks import MenuCB
from tests.conftest import MAIN_BOT_ID, OWNER2_ID, SUPER_ID, USER_ID, App
from tests.test_groups_helpers import (
    NO_PERMISSION,
    NOT_FOUND,
    TZ,
    add_chat,
    add_group,
    add_post,
    answers,
    button_data,
    button_texts,
    count_wakes,
    load,
    manage,
    members_of,
    open_menu,
    started,
)


@pytest.fixture
def wakes(app: App, monkeypatch: pytest.MonkeyPatch) -> list[int]:
    return count_wakes(app, monkeypatch)


TWO_HOURS = {"mode": "interval", "every": 120, "window": "", "days": "0123456"}


async def all_groups(app: App) -> list[ChatGroup]:
    async with app.db() as s:
        return list((await s.execute(select(ChatGroup).order_by(ChatGroup.id))).scalars())


async def test_create_group_asks_the_name_and_then_its_chats(app: App) -> None:
    await add_chat(app, -1001, "Cine HD", members=1200)
    await started(app, SUPER_ID)
    await open_menu(app, SUPER_ID, "groups")
    text = app.last_text(SUPER_ID)
    assert "🗂 <b>Grupos de canales</b>" in text and "Todavía no hay ningún grupo de canales" in text
    assert button_texts(app) == ["➕ Nuevo grupo de canales", "🔙 Regresar"]

    await app.click(SUPER_ID, "Nuevo grupo de canales")
    assert "<b>Nuevo grupo de canales</b>" in app.last_text(SUPER_ID)
    await app.feed(app.message_update(SUPER_ID, photo="ph_1"))
    assert "⚠️ Escribe el nombre como texto." in app.last_text(SUPER_ID)
    await app.send(SUPER_ID, "x" * 65)
    assert "máximo 64 caracteres" in app.last_text(SUPER_ID)
    assert await all_groups(app) == []

    await app.send(SUPER_ID, "  Cine   <Clásico>  ")
    text = app.last_text(SUPER_ID)
    assert "✅ Grupo de canales <b>Cine &lt;Clásico&gt;</b> creado" in text
    assert "📣 <b>Chats de 🗂 Cine &lt;Clásico&gt;</b>" in text and "1. 📣 Cine HD" in text
    groups = await all_groups(app)
    assert [(g.bot_id, g.name, g.freq, g.open) for g in groups] == [(MAIN_BOT_ID, "Cine <Clásico>", None, False)]
    # back from the chats goes to the new group's detail
    assert button_data(app, "Regresar") == MenuCB(screen="group", arg=groups[0].id).pack()

    await app.send(SUPER_ID, "Otro nombre")  # the input is over: no second group
    assert len(await all_groups(app)) == 1


async def test_name_prompt_ignores_commands_and_can_be_cancelled(app: App) -> None:
    await started(app, SUPER_ID)
    await app.press(SUPER_ID, GrCB(a="new").pack())
    await app.send(SUPER_ID, "/algo")  # not a name: the flow is left
    await app.send(SUPER_ID, "Cine")
    assert await all_groups(app) == []

    await app.press(SUPER_ID, GrCB(a="new").pack())
    await app.click(SUPER_ID, "Cancelar")
    assert "❌ Cancelado" in answers(app)
    assert "🗂 <b>Grupos de canales</b>" in app.last_text(SUPER_ID)
    await app.send(SUPER_ID, "Cine")
    assert await all_groups(app) == []


async def test_groups_list_shows_chats_frequency_and_open(app: App) -> None:
    a = await add_chat(app, -1001, "Cine HD")
    b = await add_chat(app, -1002, "Series", status=ChatStatus.PENDING)
    gone = await add_chat(app, -1003, "Ya no está", status=ChatStatus.LEFT)
    await add_group(app, "Cine", freq=TWO_HOURS, open=True, chats=[a, b, gone])
    await add_group(app, "Noticias", chats=[a])
    await started(app, SUPER_ID)
    await open_menu(app, SUPER_ID, "groups")
    text = app.last_text(SUPER_ID)
    assert "1. 🗂 <b>Cine</b> · 📣 2 · ⏰ cada 2 h · 🤝" in text  # a chat that left the network isn't counted
    assert "2. 🗂 <b>Noticias</b> · 📣 1 · 🌐 la global" in text
    assert "🤝 abierto a externos" in text  # the legend
    assert button_texts(app) == ["🗂 Cine", "🗂 Noticias", "➕ Nuevo grupo de canales", "🔙 Regresar"]
    assert button_data(app, "Regresar") == MenuCB(screen="home").pack()


async def test_groups_list_pages(app: App) -> None:
    for i in range(1, 12):
        await add_group(app, f"Grupo {i:02d}")
    await started(app, SUPER_ID)
    await open_menu(app, SUPER_ID, "groups")
    text = app.last_text(SUPER_ID)
    assert "10. 🗂 <b>Grupo 10</b>" in text and "Grupo 11" not in text and "📄 Página 1 de 2" in text
    await app.click(SUPER_ID, "Siguiente")
    text = app.last_text(SUPER_ID)
    assert "11. 🗂 <b>Grupo 11</b>" in text and "Grupo 10" not in text and "📄 Página 2 de 2" in text
    assert "⬅️ Anterior" in button_texts(app)


async def test_group_detail(app: App) -> None:
    a = await add_chat(app, -1001, "Cine HD", members=1000)
    b = await add_chat(app, -1002, "Series", members=500, status=ChatStatus.PENDING)
    await add_chat(app, -1003, "Fuera del grupo", members=50)
    g = await add_group(app, "Cine <HD>", open=True, chats=[a, b])
    await add_post(app, "Promo Cine", targets=[f"g{g}"])
    await add_post(app, "Mixto", targets=["own", f"g{g}"])
    await add_post(app, "Para todos", targets=["all"])
    await started(app, SUPER_ID)
    before = utcnow()
    await open_menu(app, SUPER_ID, "group", g)
    text = app.last_text(SUPER_ID)
    assert text.startswith("🗂 <b>Cine &lt;HD&gt;</b>")
    assert "📣 Chats: <b>2</b> (👤 1,500)" in text
    assert "⏰ Frecuencia: 🌐 la global (a las 12:00)" in text
    assert "└ Un canal sigue la frecuencia del primero de sus grupos de canales que tenga una propia" in text
    expected = [fmt.dt(s, TZ) for s in freq.upcoming(DEFAULT_FREQ, TZ, before, 2)]
    assert any(f"📅 Próximo turno: {e}" in text for e in expected)
    assert "📝 Mensajes que lo usan: <b>2</b>" in text
    assert "🤝 Abierto a externos: ✅" in text and "los nuevos entran solos" in text
    assert button_texts(app) == ["📣 Elegir chats", "⏰ Frecuencia", "✅ Abierto a externos", "✏️ Nombre",
                                 "🗑 Eliminar", "🔙 Regresar"]
    assert button_data(app, "Frecuencia") == MenuCB(screen="freq_edit", arg=g).pack()
    assert button_data(app, "Elegir chats") == MenuCB(screen="group_chats", arg=g).pack()

    async with app.db() as s:
        group = await s.get(ChatGroup, g)
        group.freq = {"mode": "interval", "every": 120, "window": "08:00-23:00", "days": "01234"}
    await open_menu(app, SUPER_ID, "group", g)
    assert "⏰ Frecuencia: cada 2 h · 08:00-23:00 · de lunes a viernes (propia)" in app.last_text(SUPER_ID)


async def test_rename_group(app: App) -> None:
    g = await add_group(app, "Cine")
    await started(app, SUPER_ID)
    await open_menu(app, SUPER_ID, "group", g)
    await app.click(SUPER_ID, "✏️ Nombre")
    assert "🗂 Ahora: <b>Cine</b>" in app.last_text(SUPER_ID)
    await app.send(SUPER_ID, "   ")
    assert "⚠️ Escribe el nombre como texto." in app.last_text(SUPER_ID)
    await app.send(SUPER_ID, "Películas & Series")
    text = app.last_text(SUPER_ID)
    assert text.startswith("✅ Guardado") and "🗂 <b>Películas &amp; Series</b>" in text
    assert (await load(app, ChatGroup, g)).name == "Películas & Series"

    await app.click(SUPER_ID, "✏️ Nombre")
    await app.click(SUPER_ID, "Cancelar")
    assert "🗂 <b>Películas &amp; Series</b>" in app.last_text(SUPER_ID)  # back in the detail


async def test_open_to_external_chats_toggle(app: App) -> None:
    g = await add_group(app, "Cine")
    await started(app, SUPER_ID)
    await open_menu(app, SUPER_ID, "group", g)
    text = app.last_text(SUPER_ID)
    assert "🤝 Abierto a externos: ✖️" in text and "Solo los admins eligen sus chats." in text
    await app.click(SUPER_ID, "Abierto a externos")
    assert (await load(app, ChatGroup, g)).open is True
    assert "✅ Abierto a externos" in answers(app)
    assert "🤝 Abierto a externos: ✅" in app.last_text(SUPER_ID)
    await app.click(SUPER_ID, "Abierto a externos")
    assert (await load(app, ChatGroup, g)).open is False
    assert "✖️ Abierto a externos" in answers(app)


async def test_delete_group_cleans_the_targets_of_its_posts(app: App, wakes: list[int]) -> None:
    a = await add_chat(app, -1001, "Cine HD")
    g = await add_group(app, "Cine", freq=TWO_HOURS, chats=[a])
    other = await add_group(app, "Series", chats=[a])
    only = await add_post(app, "Promo <Cine>", targets=[f"g{g}"])
    mixed = await add_post(app, "Mixto", targets=["own", f"g{g}"])
    both = await add_post(app, "Dos grupos", targets=[f"g{g}", f"g{other}"])
    untouched = await add_post(app, "Para todos", targets=["all"])
    await started(app, SUPER_ID)
    await open_menu(app, SUPER_ID, "group", g)
    await app.click(SUPER_ID, "🗑 Eliminar")
    text = app.last_text(SUPER_ID)
    assert "¿Eliminar el grupo de canales Cine?" in text
    assert "📝 Lo usan <b>3</b> mensajes" in text
    assert "⚠️ Se quedarán sin destino" in text and "<b>Promo &lt;Cine&gt;</b>" in text
    assert "Mixto" not in text and "Dos grupos" not in text
    assert "⏰ Sus chats pasarán a seguir la frecuencia global" in text

    await app.click(SUPER_ID, "❌ No")
    assert app.last_text(SUPER_ID).startswith("🗂 <b>Cine</b>")
    assert await load(app, ChatGroup, g) is not None

    await app.click(SUPER_ID, "🗑 Eliminar")
    await app.click(SUPER_ID, "Sí, eliminar")
    assert await load(app, ChatGroup, g) is None
    async with app.db() as s:
        rows = (await s.execute(select(GroupChat.group_id))).scalars().all()
    assert rows == [other]
    targets = {pid: (await load(app, Post, pid)).targets for pid in (only, mixed, both, untouched)}
    assert targets == {only: [], mixed: ["own"], both: [f"g{other}"], untouched: ["all"]}
    assert wakes == [1]
    assert "🗑 Grupo de canales eliminado" in answers(app)
    text = app.last_text(SUPER_ID)
    assert "🗂 <b>Grupos de canales</b>" in text and "<b>Series</b>" in text and "<b>Cine</b>" not in text


async def test_delete_confirmation_without_posts(app: App) -> None:
    g = await add_group(app, "Vacío")
    await started(app, SUPER_ID)
    await app.press(SUPER_ID, GrCB(a="del", id=g).pack())
    text = app.last_text(SUPER_ID)
    assert "¿Eliminar el grupo de canales Vacío?" in text
    assert "Lo usan" not in text and "sin destino" not in text and "frecuencia global" not in text


async def test_group_chats_toggles_all_none_and_pages(app: App) -> None:
    chats = [await add_chat(app, -1000 - i, f"Canal {i:02d}", members=100 * i) for i in range(1, 12)]
    async with app.db() as s:  # some states shown in the list
        from app.db.models import Chat

        (await s.get(Chat, chats[1])).admin_paused = True
        (await s.get(Chat, chats[2])).rights_ok = False
    pending = await add_chat(app, -2000, "Pendiente", status=ChatStatus.PENDING, username="pendiente")
    gone = await add_chat(app, -3000, "Fuera", status=ChatStatus.LEFT)
    g = await add_group(app, "Cine", chats=[gone])
    await started(app, SUPER_ID)
    await open_menu(app, SUPER_ID, "group_chats", g)
    text = app.last_text(SUPER_ID)
    assert "✅ En el grupo de canales: <b>0</b> de 12" in text and "📄 Página 1 de 2" in text
    assert "1. 📣 Canal 01\n   └👤 100 · 🏠" in text
    assert "2. 📣 Canal 02\n   └👤 200 · 🏠 · ⏸ pausado" in text
    assert "3. 📣 Canal 03\n   └👤 300 · 🏠 · ⚠️ faltan permisos" in text
    assert "Canal 11" not in text and "Fuera" not in text
    texts = button_texts(app)
    assert texts[:2] == ["⚪ 1. Canal 01", "⚪ 2. Canal 02"] and texts[-1] == "🔙 Regresar"
    assert "✅ Todos" in texts and "✖️ Ninguno" in texts and "Siguiente ➡️" in texts

    await app.press(SUPER_ID, GrCB(a="tg", id=g, c=chats[0]).pack())
    assert await members_of(app, g) == {gone, chats[0]}
    assert "✅ Añadido: Canal 01" in answers(app)
    assert "✅ 1. Canal 01" in button_texts(app)
    assert "<b>1</b> de 12" in app.last_text(SUPER_ID)
    await app.press(SUPER_ID, GrCB(a="tg", id=g, c=chats[0]).pack())
    assert await members_of(app, g) == {gone}
    assert "✖️ Quitado: Canal 01" in answers(app)

    await app.click(SUPER_ID, "Siguiente")
    text = app.last_text(SUPER_ID)
    assert "11. 📣 Canal 11" in text and "📄 Página 2 de 2" in text
    assert '12. 📣 <a href="https://t.me/pendiente">Pendiente</a>\n   └👤 1,000 · 🏠 · ⏳ pendiente' in text
    await app.click(SUPER_ID, "12. Pendiente")
    assert pending in await members_of(app, g)
    assert "📄 Página 2 de 2" in app.last_text(SUPER_ID)  # it stays on the same page

    await app.click(SUPER_ID, "✅ Todos")
    assert await members_of(app, g) == {*chats, pending, gone}
    assert "✅ Chats añadidos: 11" in answers(app)
    assert "<b>12</b> de 12" in app.last_text(SUPER_ID) and "📄 Página 2 de 2" in app.last_text(SUPER_ID)
    await app.click(SUPER_ID, "Ninguno")
    assert await members_of(app, g) == set()  # also the chat that left the network
    assert "✖️ Chats quitados: 12" in answers(app)
    assert button_data(app, "Regresar") == MenuCB(screen="group", arg=g).pack()


async def test_group_chats_of_an_empty_network(app: App) -> None:
    g = await add_group(app, "Cine")
    await started(app, SUPER_ID)
    await open_menu(app, SUPER_ID, "group_chats", g)
    assert "Todavía no hay chats en la red" in app.last_text(SUPER_ID)
    assert button_texts(app) == ["🔙 Regresar"]


async def test_non_admins_cannot_use_groups(app: App) -> None:
    a = await add_chat(app, -1001, "Cine HD")
    g = await add_group(app, "Cine")
    await started(app, USER_ID)
    for data in (GrCB(a="new"), GrCB(a="open", id=g), GrCB(a="ren", id=g), GrCB(a="tg", id=g, c=a),
                 GrCB(a="all", id=g), GrCB(a="none", id=g), GrCB(a="del", id=g), GrCB(a="del_ok", id=g),
                 GrCB(a="pg", id=g, p=1)):
        await app.press(USER_ID, data.pack())
    for name, arg in (("groups", 0), ("group", g), ("group_chats", g)):
        await open_menu(app, USER_ID, name, arg)
    assert answers(app) == [NO_PERMISSION] * 12
    await app.send(USER_ID, "Hackers")  # no input was ever asked
    groups = await all_groups(app)
    assert [(x.name, x.open) for x in groups] == [("Cine", False)]
    assert await members_of(app, g) == set()


async def test_an_admin_manages_groups(app: App) -> None:
    from app.db.models import BotUser, Role

    await started(app, OWNER2_ID)
    async with app.db() as s:
        (await s.get(BotUser, (MAIN_BOT_ID, OWNER2_ID))).role = Role.ADMIN
    await app.press(OWNER2_ID, GrCB(a="new").pack())
    await app.send(OWNER2_ID, "Noticias")
    assert [g.name for g in await all_groups(app)] == ["Noticias"]


async def test_rows_of_another_network_are_not_found(app: App) -> None:
    clone = 7_000_000_101
    await app.add_clone(clone, "clon_series_bot", OWNER2_ID)
    clone_chat = await add_chat(app, -5001, "Canal del clon", bot_id=clone)
    clone_group = await add_group(app, "Del clon", bot_id=clone)
    mine = await add_group(app, "Mío")
    await started(app, SUPER_ID)
    await app.press(SUPER_ID, GrCB(a="open", id=clone_group).pack())
    await app.press(SUPER_ID, GrCB(a="tg", id=mine, c=clone_chat).pack())
    await open_menu(app, SUPER_ID, "group", clone_group)
    assert answers(app) == [NOT_FOUND] * 3
    assert (await load(app, ChatGroup, clone_group)).open is False
    assert await members_of(app, mine) == set()


async def test_super_admin_manages_the_groups_of_a_clone(app: App) -> None:
    clone = 7_000_000_102
    await app.add_clone(clone, "clon_cine_bot", OWNER2_ID)
    clone_chat = await add_chat(app, -5001, "Canal del clon", bot_id=clone)
    main_chat = await add_chat(app, -5002, "Canal principal")
    main_group = await add_group(app, "Del principal")
    await manage(app, clone)
    await open_menu(app, SUPER_ID, "groups")
    text = app.last_text(SUPER_ID)
    assert "Gestionando <b>@clon_cine_bot</b>" in text and "Del principal" not in text

    await app.press(SUPER_ID, GrCB(a="new").pack())
    await app.send(SUPER_ID, "Grupo del clon")
    text = app.last_text(SUPER_ID)
    assert "Canal del clon" in text and "Canal principal" not in text
    group = next(g for g in await all_groups(app) if g.name == "Grupo del clon")
    assert group.bot_id == clone
    await app.click(SUPER_ID, "1. Canal del clon")
    assert await members_of(app, group.id) == {clone_chat}

    await app.press(SUPER_ID, GrCB(a="tg", id=group.id, c=main_chat).pack())  # a chat of another network
    await app.press(SUPER_ID, GrCB(a="open", id=main_group).pack())  # a group of the main bot
    assert answers(app)[-2:] == [NOT_FOUND, NOT_FOUND]
    assert await members_of(app, group.id) == {clone_chat}
    assert (await load(app, ChatGroup, main_group)).open is False


async def test_delete_confirmation_with_one_post(app: App) -> None:
    g = await add_group(app, "Cine")
    await add_post(app, "Mixto", targets=["own", f"g{g}"])
    await started(app, SUPER_ID)
    await app.press(SUPER_ID, GrCB(a="del", id=g).pack())
    text = app.last_text(SUPER_ID)
    assert "📝 Lo usa <b>1</b> mensaje: dejará de tenerlo como destino." in text and "sin destino" not in text
