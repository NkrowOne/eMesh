"""✨ Rich panels: the plain text of a panel becomes a rich message (a card, lists, a footer) and Telegram's refusal
falls back to the plain panel."""
from __future__ import annotations

from app.services import brand
from app.ui import common as ui_common
from app.ui.rich import to_rich, well_formed
from tests.conftest import MAIN_BOT_ID, SUPER_ID, App
from tests.test_chats_support import db_chat, start

CARD = "<table bordered><tr><th>{title}</th></tr><tr><td>{body}</td></tr></table>"


# --------------------------------------------------------------------------- the converter
def test_title_and_its_lines_become_a_card() -> None:
    text = "⚙️ <b>Ajustes</b>\n🗺 Zona horaria: Europe/Madrid\n🌍 Idioma: 🇪🇸 Español"
    assert to_rich(text) == CARD.format(title="⚙️ <b>Ajustes</b>",
                                        body="🗺 Zona horaria: Europe/Madrid<br>🌍 Idioma: 🇪🇸 Español")


def test_a_title_alone_takes_the_next_block_and_keeps_the_hint_indent() -> None:
    text = "🕸 <b>Tu red de distribución</b>\n\n📣 Canales y grupos: <b>0</b>\n   └ Añade el bot."
    assert to_rich(text) == CARD.format(
        title="🕸 <b>Tu red de distribución</b>",
        body="📣 Canales y grupos: <b>0</b><br>   └ Añade el bot.")


def test_numbered_list_legend_and_page() -> None:
    text = ("📣 <b>Canales y grupos</b>\n📣 Canales: 2\n\n"
            "11. 📣 Cine HD ✅\n   └👤 1,200 · 🏠\n12. 👥 Series ⏸\n   └👤 800 · 🤝 @pepe\n\n"
            "<i>✅ recibe mensajes · ⏸ pausado</i>\n\n📄 Página 2 de 2")
    assert to_rich(text) == (
        CARD.format(title="📣 <b>Canales y grupos</b>", body="📣 Canales: 2")
        + '<ol start="11"><li>📣 Cine HD ✅<br>└👤 1,200 · 🏠</li><li>👥 Series ⏸<br>└👤 800 · 🤝 @pepe</li></ol>'
        + "<footer>✅ recibe mensajes · ⏸ pausado</footer><p>📄 Página 2 de 2</p>")


def test_a_notice_stays_above_the_card() -> None:
    text = "✅ Guardado.\n\n⏰ <b>Horario</b> · 📝 Promo\n🕐 A las: <b>12:00</b>"
    assert to_rich(text) == ("<p>✅ Guardado.</p>"
                             + CARD.format(title="⏰ <b>Horario</b> · 📝 Promo", body="🕐 A las: <b>12:00</b>"))


def test_a_sentence_in_bold_is_not_a_title() -> None:
    assert to_rich("⏸ <b>La distribución está pausada.</b> No se envía nada.") == (
        "<p>⏸ <b>La distribución está pausada.</b> No se envía nada.</p>")


def test_bullets_and_an_example_keep_their_shape() -> None:
    text = "Reglas:\n\n• Una por línea\n• Máximo 30\n\nEjemplo:\n<pre>Web - https://example.com\n\nCanal - @micanal</pre>"
    assert to_rich(text) == ("<p>Reglas:</p><ul><li>Una por línea</li><li>Máximo 30</li></ul>"
                             "<p>Ejemplo:</p><pre>Web - https://example.com\n\nCanal - @micanal</pre>")


def test_text_that_cant_be_cut_safely_stays_plain() -> None:
    assert to_rich("Usa <b>negrita\n\ny cierra</b> después") is None  # a tag open across two blocks
    assert to_rich("Etiqueta <font>rara</font>") is None
    assert to_rich("   ") is None
    assert well_formed("<p>a<br>b</p>") and not well_formed("<p>a</b>") and not well_formed("<p>a\nb</p>")


# --------------------------------------------------------------------------- the panels
async def test_every_panel_goes_out_rich_and_buttons_edit_it(app: App) -> None:
    await start(app, SUPER_ID)
    await db_chat(app, -1001, "Cine HD", members=1200, username="cinehd")
    ui_common.rich_mode = ui_common.RICH_ALL
    await app.send(SUPER_ID, "/start")
    home = app.last_panel(SUPER_ID)
    assert home.method == "sendRichMessage"
    assert app.last_text(SUPER_ID).startswith("<table bordered><tr><th>🕸 <b>Tu red de distribución</b></th></tr><tr><td>")
    await app.press(SUPER_ID, "m:chats:0")
    chats = app.last_panel(SUPER_ID)
    assert chats.method == "editMessageText" and "text" not in chats.params  # the same message, edited
    html = app.last_text(SUPER_ID)
    assert html.startswith("<table bordered><tr><th>📣 <b>Canales y grupos</b></th></tr>")
    assert '<ol><li>📣 <a href="https://t.me/cinehd">Cine HD</a> ✅<br>└👤 1,200 · 🏠</li></ol>' in html
    assert "<footer>✅ recibe mensajes" in html and "\n" not in html
    assert [b["text"] for b in app.buttons(chats)][-1] == "🔙 Regresar"  # the keyboard is the same


async def test_the_plain_panel_is_shown_when_telegram_refuses_the_rich_one(app: App) -> None:
    await start(app, SUPER_ID)
    ui_common.rich_mode = ui_common.RICH_ALL
    app.fake.rich_refused = True
    await app.send(SUPER_ID, "/start")
    assert app.last_panel(SUPER_ID).method == "sendMessage"
    assert app.last_text(SUPER_ID).startswith("🕸 <b>Tu red de distribución</b>\n\n")
    await app.press(SUPER_ID, "m:settings:0")
    assert app.last_panel(SUPER_ID).method == "editMessageText"
    assert app.last_text(SUPER_ID).startswith("⚙️ <b>Ajustes</b>\n")


async def test_rich_panels_can_be_turned_off(app: App) -> None:
    await start(app, SUPER_ID)
    ui_common.rich_mode = ui_common.RICH_OFF
    await app.send(SUPER_ID, "/start")
    assert app.last_panel(SUPER_ID).method == "sendMessage"


async def test_the_home_image_goes_inside_the_rich_message(app: App) -> None:
    await start(app, SUPER_ID)
    async with app.db() as s:
        await brand.set_photo(s, brand.BOT, MAIN_BOT_ID, "AgADbanner")
    ui_common.rich_mode = ui_common.RICH_ALL
    await app.send(SUPER_ID, "/start")
    home = app.last_panel(SUPER_ID)
    assert home.method == "sendRichMessage"
    rich = home.params["rich_message"]
    assert rich["html"].startswith('<img src="tg://photo?id=panel"/><table bordered><tr><th>🕸 <b>Tu red')
    [media] = rich["media"]
    assert media["id"] == "panel" and media["media"]["type"] == "photo" and media["media"]["media"] == "AgADbanner"

    app.fake.rich_refused = True  # an older server: the photo with its caption, as always
    await app.send(SUPER_ID, "/start")
    photo = app.last_panel(SUPER_ID)
    assert photo.method == "sendPhoto" and photo.params["photo"] == "AgADbanner"
    assert str(photo.params["caption"]).startswith("🕸 <b>Tu red de distribución</b>")
