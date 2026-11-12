"""Posts: the buttons editor (keyboard with the real colors, add step by step, move, recolor, rename, relink, remove,
write them all, remove all, preview)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.bot.routers.post_buttons import DOWN, LEFT, RIGHT, UP, PbCB, move, parse_link
from app.db.models import Post
from tests.conftest import SUPER_ID, App
from tests.test_posts_helpers import (  # noqa: F401 - fixtures
    EXPIRED,
    add_post,
    answers,
    button_texts,
    engine_fixture,
    keyboard,
    load,
    open_menu,
    started,
)


def b(text: str, style: str | None = None, **target: str) -> dict[str, str]:
    out = {"text": text, **(target or {"url": f"https://{text.lower()}.com"})}
    if style:
        out["style"] = style
    return out


ALFA, BETA, GAMMA = b("Alfa"), b("Beta", "success"), b("Gamma", copy="PROMO10")


async def open_editor(app: App, post_id: int) -> str:
    await started(app, SUPER_ID)
    await open_menu(app, SUPER_ID, "post_buttons", post_id)
    return app.last_text(SUPER_ID)


async def buttons_of(app: App, post_id: int) -> list[list[dict[str, str]]]:
    return (await load(app, Post, post_id)).buttons


async def press_button(app: App, post_id: int, r: int, c: int) -> None:
    await app.press(SUPER_ID, PbCB(a="b", id=post_id, r=r, c=c).pack())


# --------------------------------------------------------------------------- helpers
def test_move() -> None:
    a, b_, c = {"text": "A"}, {"text": "B"}, {"text": "C"}
    assert move([[a, b_], [c]], 0, 1, LEFT) == ([[b_, a], [c]], 0, 0)
    assert move([[a, b_], [c]], 0, 0, RIGHT) == ([[b_, a], [c]], 0, 1)
    assert move([[a, b_], [c]], 0, 0, LEFT) == "pb.edge"
    assert move([[a], [b_], [c]], 1, 0, UP) == ([[a, b_], [c]], 0, 1)  # joins the row above, at its end
    assert move([[a], [b_], [c]], 1, 0, DOWN) == ([[a], [b_, c]], 1, 0)  # joins the row below, first
    assert move([[a, b_]], 0, 1, UP) == ([[b_], [a]], 0, 0)  # leaves the first row for a new one on top
    assert move([[a, b_]], 0, 0, DOWN) == ([[b_], [a]], 1, 0)  # leaves the last row for a new one below
    assert move([[a]], 0, 0, UP) == "pb.edge" and move([[a]], 0, 0, DOWN) == "pb.edge"
    assert move([[a] * 8, [c]], 1, 0, UP) == "pb.row_full"


@pytest.mark.parametrize(("text", "target"), [
    ("https://example.com", {"url": "https://example.com"}), ("t.me/canal", {"url": "https://t.me/canal"}),
    ("@micanal", {"url": "https://t.me/micanal"}), ("copiar: PROMO10", {"copy": "PROMO10"}),
    ("Copy:  CODE 2", {"copy": "CODE 2"}),
])
def test_parse_link(text: str, target: dict[str, str]) -> None:
    assert parse_link(text) == target


@pytest.mark.parametrize(("text", "key"), [("hola", "pb.err.link"), ("example.com", "pb.err.link"),
                                           ("copiar: " + "x" * 257, "pb.err.copy"), ("", "pb.err.link")])
def test_parse_link_errors(text: str, key: str) -> None:
    with pytest.raises(ValueError, match=key):
        parse_link(text)


# --------------------------------------------------------------------------- screen
async def test_keyboard_is_drawn_with_the_real_colors(app: App, engine: SimpleNamespace) -> None:
    pid = await add_post(app, buttons=[[ALFA, BETA], [b("Gamma", "danger", copy="X")]])
    text = await open_editor(app, pid)
    assert "🔘 <b>Botones</b> · Promo Cine" in text and "🔘 3 de 30 botones" in text
    assert "Actualizar publicados" not in text
    rows = keyboard(app)
    assert [[x["text"] for x in row] for row in rows[:2]] == [["Alfa", "Beta"], ["Gamma"]]
    assert "style" not in rows[0][0] and rows[0][1]["style"] == "success" and rows[1][0]["style"] == "danger"
    assert rows[0][1]["callback_data"] == PbCB(a="b", id=pid, r=0, c=1).pack()
    assert [[x["text"] for x in row] for row in rows[2:]] == [["➕ Añadir botón"], ["✍️ Escribirlos todos"],
                                                              ["🗑 Quitar todos"], ["👁 Vista previa"], ["🔙 Regresar"]]
    engine.live = 4
    await open_menu(app, SUPER_ID, "post_buttons", pid)
    assert "🔄 Actualizar publicados" in app.last_text(SUPER_ID)

    empty = await add_post(app, name="Sin botones")
    text = await open_editor(app, empty)
    assert "Todavía no tiene botones" in text and "🗑 Quitar todos" not in button_texts(app)
    await app.click(SUPER_ID, "Regresar")
    assert "📝 <b>Sin botones</b>" in app.last_text(SUPER_ID)


async def test_add_buttons_step_by_step(app: App, engine: SimpleNamespace) -> None:
    pid = await add_post(app)
    await open_editor(app, pid)
    await app.click(SUPER_ID, "Añadir botón")
    assert "➕ <b>Nuevo botón</b> · 1/4" in app.last_text(SUPER_ID) and button_texts(app) == ["❌ Cancelar"]
    await app.send(SUPER_ID, "x" * 65)
    assert "⚠️ El nombre debe tener entre 1 y 64 caracteres." in app.last_text(SUPER_ID)
    await app.send(SUPER_ID, "Web  oficial")
    assert "➕ <b>Nuevo botón</b> · 2/4" in app.last_text(SUPER_ID)
    await app.send(SUPER_ID, "hola")
    assert "⚠️ El enlace no es válido." in app.last_text(SUPER_ID)
    await app.send(SUPER_ID, "https://example.com")
    assert "🎨 Elige el color de <b>Web oficial</b>" in app.last_text(SUPER_ID)
    colors = keyboard(app)[0]
    assert [x["text"] for x in colors] == ["⬜ Normal", "🔵 Azul", "🟢 Verde", "🔴 Rojo"]
    assert [x.get("style") for x in colors] == [None, "primary", "success", "danger"]
    await app.send(SUPER_ID, "verde")
    assert "👇 Usa los botones de abajo." in app.last_text(SUPER_ID)
    await app.click(SUPER_ID, "Verde")  # the first button: no place to choose
    assert answers(app)[-1] == "✅ Botón añadido"
    assert await buttons_of(app, pid) == [[{"text": "Web oficial", "url": "https://example.com", "style": "success"}]]
    assert keyboard(app)[0][0]["text"] == "Web oficial"

    await app.click(SUPER_ID, "Añadir botón")
    await app.send(SUPER_ID, "Código")
    await app.send(SUPER_ID, "copiar: PROMO10")
    await app.click(SUPER_ID, "Azul")
    assert "➕ <b>Nuevo botón</b> · 4/4" in app.last_text(SUPER_ID)
    assert button_texts(app)[:2] == ["⬇️ En una fila nueva", "➡️ Al lado del último"]
    await app.click(SUPER_ID, "Al lado del último")
    await app.click(SUPER_ID, "Añadir botón")
    await app.send(SUPER_ID, "Grupo")
    await app.send(SUPER_ID, "@migrupo")
    await app.click(SUPER_ID, "Normal")
    await app.click(SUPER_ID, "En una fila nueva")
    assert await buttons_of(app, pid) == [
        [{"text": "Web oficial", "url": "https://example.com", "style": "success"},
         {"text": "Código", "copy": "PROMO10", "style": "primary"}],
        [{"text": "Grupo", "url": "https://t.me/migrupo"}],
    ]
    assert "🔘 3 de 30 botones" in app.last_text(SUPER_ID)


async def test_add_flow_back_cancel_stale_and_limits(app: App, engine: SimpleNamespace) -> None:
    pid = await add_post(app, buttons=[[ALFA]])
    await open_editor(app, pid)
    await app.click(SUPER_ID, "Añadir botón")
    await app.send(SUPER_ID, "Nuevo")
    await app.send(SUPER_ID, "https://nuevo.com")
    await app.click(SUPER_ID, "Rojo")
    await app.click(SUPER_ID, "Regresar")
    assert "🎨 Elige el color" in app.last_text(SUPER_ID)
    await app.click(SUPER_ID, "Regresar")
    assert "➕ <b>Nuevo botón</b> · 2/4" in app.last_text(SUPER_ID)
    await app.click(SUPER_ID, "Regresar")
    assert "➕ <b>Nuevo botón</b> · 1/4" in app.last_text(SUPER_ID)
    await app.click(SUPER_ID, "Cancelar")
    assert "🔘 <b>Botones</b> · Promo Cine" in app.last_text(SUPER_ID)
    await app.press(SUPER_ID, PbCB(a="acol", id=pid, v=1).pack())  # not adding any more
    await app.press(SUPER_ID, PbCB(a="aplace", id=pid, v=1).pack())
    assert answers(app)[-2:] == [EXPIRED, EXPIRED]
    assert await buttons_of(app, pid) == [[ALFA]]

    full_row = await add_post(app, buttons=[[b(f"B{i}") for i in range(8)]])
    await open_editor(app, full_row)
    await app.click(SUPER_ID, "Añadir botón")
    await app.send(SUPER_ID, "Noveno")
    await app.send(SUPER_ID, "https://noveno.com")
    await app.click(SUPER_ID, "Normal")  # the last row is full: a new row, no question
    assert [len(row) for row in await buttons_of(app, full_row)] == [8, 1]

    many = await add_post(app, buttons=[[b(f"B{r}{c}") for c in range(6)] for r in range(5)])  # 30 buttons
    await open_editor(app, many)
    await app.click(SUPER_ID, "Añadir botón")
    assert answers(app)[-1] == "⚠️ Como máximo 30 botones."


async def test_move_recolor_rename_relink_and_remove(app: App, engine: SimpleNamespace) -> None:
    pid = await add_post(app, buttons=[[ALFA, BETA], [GAMMA]])
    await open_editor(app, pid)
    await press_button(app, pid, 0, 1)
    text = app.last_text(SUPER_ID)
    for expected in ("🔘 <b>Botón</b> · Promo Cine", "🏷 Nombre: Beta", "🔗 Enlace: https://beta.com",
                     "🎨 Color: 🟢 Verde", "📍 Fila 1 · posición 2"):
        assert expected in text, expected
    assert button_texts(app) == ["🏷 Nombre", "🔗 Enlace", "⚪ Normal", "⚪ Azul", "✅ Verde", "⚪ Rojo", "⬅️", "➡️",
                                 "⬆️", "⬇️", "🗑 Quitar botón", "🔙 Regresar"]

    await app.click(SUPER_ID, "⬅️")
    assert await buttons_of(app, pid) == [[BETA, ALFA], [GAMMA]]
    assert "📍 Fila 1 · posición 1" in app.last_text(SUPER_ID)
    await app.click(SUPER_ID, "⬅️")
    assert answers(app)[-1] == "↔️ No se puede mover más hacia ese lado."
    await app.click(SUPER_ID, "⬇️")
    assert await buttons_of(app, pid) == [[ALFA], [BETA, GAMMA]]
    await app.click(SUPER_ID, "⬇️")
    assert await buttons_of(app, pid) == [[ALFA], [GAMMA], [BETA]]
    assert "📍 Fila 3 · posición 1" in app.last_text(SUPER_ID)
    await app.click(SUPER_ID, "⬇️")
    assert answers(app)[-1] == "↔️ No se puede mover más hacia ese lado."
    await app.click(SUPER_ID, "⬆️")
    assert await buttons_of(app, pid) == [[ALFA], [GAMMA, BETA]]
    await app.click(SUPER_ID, "➡️")
    assert answers(app)[-1] == "↔️ No se puede mover más hacia ese lado."
    await app.click(SUPER_ID, "⬆️")
    assert await buttons_of(app, pid) == [[ALFA, BETA], [GAMMA]]

    await app.click(SUPER_ID, "Rojo")
    assert (await buttons_of(app, pid))[0][1]["style"] == "danger" and "🎨 Color: 🔴 Rojo" in app.last_text(SUPER_ID)
    await app.click(SUPER_ID, "Normal")
    assert "style" not in (await buttons_of(app, pid))[0][1]

    await app.click(SUPER_ID, "🏷 Nombre")
    assert "Actual: Beta" in app.last_text(SUPER_ID)
    await app.send(SUPER_ID, "x" * 65)
    assert "⚠️ El nombre debe tener entre 1 y 64 caracteres." in app.last_text(SUPER_ID)
    await app.send(SUPER_ID, "Beta <2>")
    assert (await buttons_of(app, pid))[0][1]["text"] == "Beta <2>"
    assert app.last_text(SUPER_ID).startswith("✅ Guardado") and "🏷 Nombre: Beta &lt;2&gt;" in app.last_text(SUPER_ID)

    await app.click(SUPER_ID, "🔗 Enlace")
    assert "Actual: https://beta.com" in app.last_text(SUPER_ID)
    await app.send(SUPER_ID, "no es un enlace")
    assert "⚠️ El enlace no es válido." in app.last_text(SUPER_ID)
    await app.send(SUPER_ID, "copiar: CINE20")
    assert (await buttons_of(app, pid))[0][1] == {"text": "Beta <2>", "copy": "CINE20"}
    assert "📋 Copia el texto: <code>CINE20</code>" in app.last_text(SUPER_ID)
    await app.click(SUPER_ID, "🔗 Enlace")
    await app.send(SUPER_ID, "t.me/canal")
    assert (await buttons_of(app, pid))[0][1] == {"text": "Beta <2>", "url": "https://t.me/canal"}

    await app.click(SUPER_ID, "Quitar botón")
    assert answers(app)[-1] == "🗑 Botón quitado" and await buttons_of(app, pid) == [[ALFA], [GAMMA]]
    assert "🔘 <b>Botones</b>" in app.last_text(SUPER_ID)
    await press_button(app, pid, 1, 0)
    await app.click(SUPER_ID, "Quitar botón")
    assert await buttons_of(app, pid) == [[ALFA]]  # empty rows go away

    await press_button(app, pid, 3, 0)  # a button that no longer exists
    assert answers(app)[-1] == EXPIRED and "🔘 <b>Botones</b>" in app.last_text(SUPER_ID)


async def test_row_full_and_edit_of_a_removed_button(app: App, engine: SimpleNamespace) -> None:
    pid = await add_post(app, buttons=[[b(f"B{i}") for i in range(8)], [ALFA]])
    await open_editor(app, pid)
    await press_button(app, pid, 1, 0)
    await app.click(SUPER_ID, "⬆️")
    assert answers(app)[-1] == "⚠️ Esa fila ya tiene 8 botones."
    await app.click(SUPER_ID, "🏷 Nombre")
    async with app.db() as s:  # someone else removes it meanwhile
        post = await s.get(Post, pid)
        assert post is not None
        post.buttons = [post.buttons[0]]
    await app.send(SUPER_ID, "Nuevo nombre")
    assert app.last_text(SUPER_ID).startswith(EXPIRED) and "🔘 <b>Botones</b>" in app.last_text(SUPER_ID)
    assert len(await buttons_of(app, pid)) == 1


async def test_write_all_the_buttons(app: App, engine: SimpleNamespace) -> None:
    pid = await add_post(app, buttons=[[BETA, GAMMA]])
    await open_editor(app, pid)
    await app.click(SUPER_ID, "Escribirlos todos")
    text = app.last_text(SUPER_ID)
    assert "✍️ <b>Escribir todos los botones</b> · Promo Cine" in text
    assert "<pre>Beta - https://beta.com 🟢 &amp;&amp; Gamma - copiar: PROMO10</pre>" in text
    assert "⚠️ Lo que envíes sustituye a todos los botones actuales." in text
    await app.feed(app.message_update(SUPER_ID, photo="ph"))
    assert "⚠️ Envíalo como texto." in app.last_text(SUPER_ID)
    await app.send(SUPER_ID, "Uno - https://uno.com\nDos sin enlace")
    assert "⚠️ Línea 2: escribe cada botón así" in app.last_text(SUPER_ID)
    await app.send(SUPER_ID, "A - https://a.com && " * 8 + "B - https://b.com")
    assert "⚠️ Línea 1: como máximo 8 botones por fila." in app.last_text(SUPER_ID)
    await app.send(SUPER_ID, "\n".join(f"B{i} - https://b{i}.com" for i in range(31)))
    assert "⚠️ Como máximo 30 botones." in app.last_text(SUPER_ID)
    await app.send(SUPER_ID, "Uno - https://uno.com 🔴 && Dos - @doscanal\nTres - copiar: 3")
    assert await buttons_of(app, pid) == [
        [{"text": "Uno", "url": "https://uno.com", "style": "danger"}, {"text": "Dos", "url": "https://t.me/doscanal"}],
        [{"text": "Tres", "copy": "3"}],
    ]
    assert app.last_text(SUPER_ID).startswith("✅ Guardado\n\n🔘 <b>Botones</b>")


async def test_remove_all_and_preview(app: App, engine: SimpleNamespace) -> None:
    pid = await add_post(app, buttons=[[ALFA, BETA]])
    await open_editor(app, pid)
    before = len(app.fake.calls_of("sendMessage", chat_id=SUPER_ID))
    await app.click(SUPER_ID, "Vista previa")
    sent = app.fake.calls_of("sendMessage", chat_id=SUPER_ID)[before:]
    assert sent[0].params["text"] == "<b>Promo</b> de cine"
    assert [x["text"] for x in sent[0].params["reply_markup"]["inline_keyboard"][0]] == ["Alfa", "Beta"]
    assert "🔘 <b>Botones</b> · Promo Cine" in sent[1].params["text"]  # the editor again, below the preview

    await app.click(SUPER_ID, "Quitar todos")
    assert app.last_text(SUPER_ID) == "🗑 ¿Quitar todos los botones de <b>Promo Cine</b> (2 botones)?"
    await app.click(SUPER_ID, "No")
    assert await buttons_of(app, pid) == [[ALFA, BETA]]
    await app.click(SUPER_ID, "Quitar todos")
    await app.click(SUPER_ID, "🗑 Quitar todos")
    assert await buttons_of(app, pid) == [] and answers(app)[-1] == "🗑 Botones quitados"
    assert "Todavía no tiene botones" in app.last_text(SUPER_ID)
