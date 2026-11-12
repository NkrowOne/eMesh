"""Records what the eMesh promo videos show: real bot screens (texts, rich panels, buttons, edits).

Runs the whole bot against the fake Telegram of the tests and writes, in ``tools/promo_video/``:

* ``guion_<lang>.json``: the step-by-step guion (scenes, captions, taps) of the walkthrough video (player.html);
* ``spot_<lang>.json``: the named screens of the spot cut to the music (spot.html).

Run through ``tools/promo_video/make.sh`` (or see the README there).
"""
from __future__ import annotations

import base64
import json
import os
import re
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from app.db.base import utcnow
from app.db.models import Bot as BotRecord
from app.db.models import ChatOrigin, Run
from app.services import brand
from app.ui import common as ui_common
from tests.conftest import MAIN_BOT_ID, OWNER2_ID, SUPER_ID, USER_ID, App
from tests.fake_tg import ADMIN_RIGHTS_FULL
from tests.test_chats_support import db_chat, set_bot, start
from tests.test_posts_helpers import add_post

HERE = Path(__file__).parent
OUT = Path(os.environ.get("PROMO_VIDEO_OUT", HERE))
LANGS = ("es",)
BANNER_ID = "AgADpromoBanner"
# The images the bot sends, by file id: the videos show the files of assets/ (real photos in the posts).
ASSETS = {BANNER_ID: "assets/logo_banner.jpg", "AgADpostEstreno": "assets/post_estreno.jpg",
          "AgADpostSorteo": "assets/post_sorteo.jpg", "AgADpostNoche": "assets/post_noche.jpg"}
NEW_CHANNEL = -1001987650001
PARTNER_CHANNEL = -1001987650002

TEXT: dict[str, dict[str, Any]] = {
    "es": {
        "bot": "eMesh", "username": "eMeshBot", "viewer": "tu_usuario",
        "brand.tagline": "Tu red de distribución en Telegram",
        "intro.title": "Publica en todos tus canales a la vez",
        "intro.sub": "Escribes el mensaje una vez. eMesh lo lleva a toda tu red, a su hora.",
        "outro.title": "Crea tu red en un minuto",
        "outro.sub": "Tu propio bot, tus canales y tus reglas.",
        "outro.cta": "Búscalo en Telegram: eMesh",
        "s1.title": "Toda tu red, de un vistazo", "s1.sub": "Canales, miembros, mensajes activos y el próximo envío.",
        "s2.title": "Añade canales en dos toques", "s2.sub": "El bot entra como administrador y el canal queda en la red.",
        "s3.title": "Escribe una vez, publica en todos",
        "s3.sub": "Texto, fotos o vídeo, con botones de colores. Un toque y sale en toda la red.",
        "s4.title": "Cada mensaje, a su hora", "s4.sub": "Horario propio por mensaje y anti-spam para no saturar ningún chat.",
        "s5.title": "Tus asociados suman sus canales",
        "s5.sub": "Piden unirse, tú decides. Pueden pausar sus envíos y siempre te enteras.",
        "s6.title": "Mide cada envío", "s6.sub": "Entregados, fallos y alcance real de tu red.",
        "c.home": "Abre el bot y pulsa /start", "c.add": "➕ Añadir canal o grupo", "c.pick": "Elige tu canal",
        "c.rights": "Deja los permisos marcados", "c.added": "✅ Ya está en la red",
        "c.posts": "📝 Tus mensajes", "c.send": "🚀 Enviar ahora", "c.channel": "Publicado en tus canales",
        "c.sched": "⏰ A sus horas, sin que hagas nada", "c.request": "📨 Llega una solicitud", "c.accept": "✅ Aceptado",
        "c.list": "📣 Toda la red, con su estado", "c.stats": "📊 Resultados del día",
        "new.channel": "Estrenos de Cine", "partner.channel": "Series en Casa", "partner.name": "Laura",
        "channels": ["Cine Clásico", "Documentales HD", "Cortos de Autor", "Cine en Familia", "Terror Nocturno"],
        "post.name": "Estreno de la semana",
        "post.text": ("🎬 <b>Estreno de la semana</b>\n\nLa película de la que todos hablan llega este viernes. "
                      "Tráiler, horarios y entradas con <b>-20 %</b> solo hoy.\n\n🍿 ¿Te la vas a perder?"),
        "post.buttons": [[{"text": "▶️ Ver tráiler", "url": "https://example.com/trailer", "style": "primary"}],
                         [{"text": "🎟 Entradas -20 %", "url": "https://example.com/entradas", "style": "success"},
                          {"text": "⭐ Opiniones", "url": "https://example.com/opiniones"}]],
        "post2.name": "Sorteo: 2 entradas dobles",
        "post2.text": "🍿 <b>Sorteo: 2 entradas dobles</b>\n\nParticipa con un toque. El ganador sale el domingo.",
        "post3.name": "Noche de cine",
        "post3.text": "🌃 <b>Noche de cine</b>\n\nSesión doble este sábado. Aforo limitado: reserva tu butaca.",
        "picker.title": "Elegir un canal", "picker.cancel": "Cancelar", "picker.search": "Buscar",
        "picker.subs": "{n} suscriptores",
        "rights.title": "Permisos de administrador", "rights.header": "¿Qué puede hacer este administrador?",
        "rights.list": [("Cambiar información del canal", False), ("Publicar mensajes", True),
                        ("Editar mensajes de otros", True), ("Eliminar mensajes de otros", True),
                        ("Invitar usuarios con enlace", True), ("Añadir administradores", False)],
        "rights.button": "Añadir bot como administrador",
        "rights.alert": "¿Añadir a {bot} como administrador de «{chat}»?", "rights.ok": "Añadir",
        "cancel": "Cancelar", "channel.subs": "{n} suscriptores", "channel.mute": "Silenciar", "chat.bot": "bot",
        "chats": "Chats", "message": "Mensaje", "views": "1,2 K", "today": "Hoy", "menu": "Menú", "edited": "editado",
        "back": "Atrás", "channel.old": "🎞 Esta noche, sesión doble de cine clásico.",
    },
}


def realistic(text: str) -> str:
    """Test ids and invite links look fake on screen: show believable ones."""
    text = re.sub(r"https://t\.me/\+\w+", "https://t.me/+Xq3mZ9vK2Lw0", text)
    return re.sub(r"-100\d{10}", "-1001987654321", text)


def keyboard(params: dict[str, Any]) -> list[list[dict[str, Any]]] | None:
    markup = params.get("reply_markup")
    if not isinstance(markup, dict) or "inline_keyboard" not in markup:
        return None
    return [[{"text": b["text"], "style": b.get("style"), "url": "url" in b, "disabled": "disabled" in b}
             for b in row] for row in markup["inline_keyboard"]]


class Recorder:
    """Collects what the viewer sees in their private chat with the bot, plus the scripted moments of the story."""

    def __init__(self, app: App, viewer: int, lang: str) -> None:
        self.app, self.viewer, self.lang = app, viewer, lang
        self.token = next(tok for tok, b in app.fake.bots.items() if b["id"] == MAIN_BOT_ID)
        self.events: list[dict[str, Any]] = []
        self.seen = len(app.fake.calls)
        self.user_ids: set[int] = set()

    def t(self, key: str, **kw: Any) -> Any:
        value = TEXT[self.lang][key]
        return value.format(**kw) if kw and isinstance(value, str) else value

    def _photo(self, file_id: Any) -> str | None:
        """Where the player finds an image the bot sent: its file in assets/, else the image itself."""
        if str(file_id) in ASSETS:
            return ASSETS[str(file_id)]
        data = self.app.fake.files.get(str(file_id))
        return "data:image/jpeg;base64," + base64.b64encode(data).decode() if data else None

    def _content(self, p: dict[str, Any]) -> dict[str, Any]:
        """The text of a panel: its rich HTML (with the image it carries) or its plain text."""
        rich = p.get("rich_message")
        if isinstance(rich, dict) and rich.get("html"):
            out: dict[str, Any] = {"rich": realistic(rich["html"])}
            for media in rich.get("media") or []:
                if photo := self._photo(media.get("media", {}).get("media")):
                    out["photo"] = photo
            return out
        return {"text": realistic(p.get("text") or p.get("caption") or "")}

    def collect(self, *, toasts: bool = False) -> None:
        for call in self.app.fake.calls[self.seen:]:
            p = call.params
            if toasts and call.method == "answerCallbackQuery" and p.get("text"):
                self.events.append({"t": "toast", "text": p["text"]})
                continue
            if str(p.get("chat_id")) != str(self.viewer) or call.token != self.token:
                continue
            if call.method in ("sendMessage", "sendRichMessage", "sendPhoto") and call.result:
                event = {"t": "msg", "id": call.result["message_id"], **self._content(p), "kb": keyboard(p)}
                if call.method == "sendPhoto" and (photo := self._photo(p.get("photo"))):
                    event["photo"] = photo
                self.events.append(event)
            elif call.method in ("editMessageText", "editMessageCaption"):
                self.events.append({"t": "edit", "id": int(p["message_id"]), **self._content(p), "kb": keyboard(p)})
            elif call.method == "editMessageReplyMarkup":
                self.events.append({"t": "edit", "id": int(p["message_id"]), "kb": keyboard(p)})
            elif call.method == "deleteMessage":
                mid = int(p["message_id"])
                self.events.append({"t": "delete", "id": mid, "user": mid in self.user_ids})
        self.seen = len(self.app.fake.calls)

    def skip(self) -> None:
        """Forget what happened meanwhile (things the viewer doesn't see)."""
        self.seen = len(self.app.fake.calls)

    async def say(self, text: str) -> None:
        update = self.app.message_update(self.viewer, text)
        mid = update["message"]["message_id"]
        self.user_ids.add(mid)
        self.events.append({"t": "user", "text": text, "id": mid})
        await self.app.feed(update, MAIN_BOT_ID)
        self.collect()

    async def home(self) -> None:
        """The home panel again, without typing /start on screen: a new scene starts from the menu."""
        await self.app.feed(self.app.message_update(self.viewer, "/start"), MAIN_BOT_ID)
        before = len(self.events)
        self.collect()
        for event in self.events[before:]:
            if event["t"] == "msg":
                event["quick"] = True  # straight to its buttons: the viewer already saw the whole home

    async def tap(self, contains: str) -> dict[str, Any]:
        button, call = self.app.find_button(self.viewer, contains)
        mid = int(call.params.get("message_id") or (call.result or {}).get("message_id", 1))
        self.events.append({"t": "tap", "text": button["text"], "id": mid})
        if "callback_data" in button:
            await self.app.press(self.viewer, button["callback_data"], mid, MAIN_BOT_ID)
            self.collect(toasts=True)
        return button

    def scene(self, n: int) -> None:
        self.events.append({"t": "scene", "n": n, "title": self.t(f"s{n}.title"), "sub": self.t(f"s{n}.sub")})

    def caption(self, key: str) -> None:
        self.events.append({"t": "caption", "text": self.t(key)})

    def ui(self, screen: str, **data: Any) -> None:
        self.events.append({"t": "ui", "screen": screen, **data})

    def wait(self, seconds: float) -> None:
        self.events.append({"t": "wait", "s": seconds})

    def clear(self) -> None:
        """A new scene starts with an empty chat (the conversation so far scrolls away)."""
        self.events.append({"t": "clear"})

    def save(self) -> None:
        OUT.mkdir(parents=True, exist_ok=True)
        ui = {k: v for k, v in TEXT[self.lang].items()
              if k.split(".")[0] in ("picker", "rights", "channel", "chat", "brand", "intro", "outro")
              or k in ("cancel", "chats", "message", "views", "today", "menu", "edited", "back")}
        data = {"video": "emesh_promo", "lang": self.lang, "header": {"name": self.t("bot")}, "ui": ui,
                "scenes": 6, "events": self.events}
        (OUT / f"guion_{self.lang}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def channel_post(rec: Recorder, chat_id: int) -> dict[str, Any]:
    """The post as it was published in a channel: its photo, its text and its buttons."""
    sent = rec.app.fake.calls_of("sendPhoto", chat_id=chat_id) or rec.app.fake.calls_of("sendMessage", chat_id=chat_id)
    p = sent[-1].params
    return {"text": realistic(p.get("caption") or p.get("text") or ""), "kb": keyboard(p),
            "photo": rec._photo(p.get("photo"))}  # noqa: SLF001


async def prepare(app: App, lang: str) -> None:
    """A believable network: its name, its image, a few channels (own and of partners), messages and a day of runs."""
    words = TEXT[lang]
    ADMIN_RIGHTS_FULL["can_send_welcome_messages"] = False
    app.fake.users[SUPER_ID].update(username=words["viewer"], first_name="Admin", language_code=lang)
    app.fake.users[USER_ID].update(username="laura_cine", first_name=words["partner.name"], language_code=lang)
    app.fake.users[OWNER2_ID].update(username="marcos_tv", first_name="Marcos", language_code=lang)
    for file_id, path in ASSETS.items():
        app.fake.files[file_id] = (HERE / path).read_bytes()
    await start(app, SUPER_ID, USER_ID, OWNER2_ID)
    async with app.db() as s:
        rec = await s.get(BotRecord, MAIN_BOT_ID)
        assert rec is not None
        rec.username, rec.name = words["username"], words["bot"]
        await brand.set_photo(s, brand.BOT, MAIN_BOT_ID, BANNER_ID)
    await set_bot(app, join_open=True, join_approval=True)
    members = [18450, 9320, 4210, 12780, 6540]
    for i, name in enumerate(words["channels"]):
        partner = i >= 3
        app.fake.add_chat(-1001987651000 - i, name, members=members[i], creator=OWNER2_ID if partner else SUPER_ID,
                          admin_bots={MAIN_BOT_ID: dict(ADMIN_RIGHTS_FULL)})
        await db_chat(app, -1001987651000 - i, name, members=members[i], username=None,
                      origin=ChatOrigin.EXTERNAL if partner else ChatOrigin.OWN,
                      owner=OWNER2_ID if partner else SUPER_ID,
                      **({"owner_paused": True, "owner_paused_until": utcnow() + timedelta(hours=6)} if i == 4 else {}))
    for name, text, file_id, buttons in (
            (words["post.name"], words["post.text"], "AgADpostEstreno", words["post.buttons"]),
            (words["post2.name"], words["post2.text"], "AgADpostSorteo", []),
            (words["post3.name"], words["post3.text"], "AgADpostNoche", [])):
        await add_post(app, name=name, kind="photo", text=text, media={str(MAIN_BOT_ID): file_id}, buttons=buttons)
    async with app.db() as s:
        now = utcnow()
        for hours, sent, failed, reach in ((3, 5, 0, 51300), (9, 4, 1, 44760), (20, 5, 0, 51300)):
            s.add(Run(bot_id=MAIN_BOT_ID, post_name=words["post.name"], total=sent + failed, sent=sent, failed=failed,
                      skipped=0, reach=reach, status="done", started_at=now - timedelta(hours=hours)))
    ui_common.rich_mode = ui_common.RICH_ALL


@pytest.mark.parametrize("lang", LANGS)
async def test_guion(app: App, lang: str) -> None:
    await prepare(app, lang)
    words = TEXT[lang]
    rec = Recorder(app, SUPER_ID, lang)
    rec.events.append({"t": "intro", "title": words["intro.title"], "sub": words["intro.sub"]})

    # 1 · the home: the whole network at a glance
    rec.scene(1)
    rec.caption("c.home")
    await rec.say("/start")
    rec.wait(1.4)

    # 2 · a channel joins in two taps
    rec.scene(2)
    rec.caption("c.add")
    await rec.tap("➕")
    rec.wait(0.9)
    await rec.tap("canal")  # ➕ Añadir canal: Telegram's own screens follow
    rec.caption("c.pick")
    app.fake.add_chat(NEW_CHANNEL, words["new.channel"], members=7815, creator=SUPER_ID)
    rec.ui("picker", pick=0, channels=[{"name": n, "subs": words["picker.subs"].format(n=m)} for n, m in (
        (words["new.channel"], "7.815"), ("Cine de Verano", "2.104"), ("Making of", "936"), ("Bandas Sonoras", "5.480"))])
    rec.caption("c.rights")
    rec.ui("rights", chat=words["new.channel"], bot=words["bot"])
    await app.feed(app.my_chat_member_update(NEW_CHANNEL, SUPER_ID), MAIN_BOT_ID)
    rec.collect()
    rec.caption("c.added")
    rec.wait(2.2)

    # 3 · one message, every channel
    rec.clear()
    rec.scene(3)
    rec.caption("c.posts")
    await rec.home()
    await rec.tap("📝")
    rec.wait(1.0)
    await rec.tap(words["post.name"][:12])
    rec.wait(0.6)
    rec.caption("c.send")
    await rec.tap("🚀")
    rec.wait(0.8)
    await rec.tap("✅")
    await app.publisher.wait_idle(15)
    rec.collect(toasts=True)
    rec.caption("c.channel")
    rec.events.append({"t": "channel", "title": words["channels"][0], "subs": words["channel.subs"].format(n="18.450"),
                       "old": words["channel.old"], "post": channel_post(rec, -1001987651000)})
    rec.wait(3.0)
    rec.events.append({"t": "back"})

    # 4 · each message at its own times
    rec.clear()
    rec.scene(4)
    rec.caption("c.sched")
    await rec.home()
    await rec.tap("⏰")
    rec.wait(1.8)
    await rec.tap("🛡")
    rec.wait(1.0)

    # 5 · partners add their channels
    rec.clear()
    rec.scene(5)
    rec.caption("c.request")
    app.fake.add_chat(PARTNER_CHANNEL, words["partner.channel"], members=3460, creator=USER_ID)
    await app.feed(app.my_chat_member_update(PARTNER_CHANNEL, USER_ID), MAIN_BOT_ID)
    rec.collect()
    rec.wait(1.8)
    await rec.tap("✅")
    rec.caption("c.accept")
    rec.wait(1.4)
    rec.clear()
    rec.caption("c.list")
    await rec.home()
    await rec.tap("📣")
    rec.wait(1.2)

    # 6 · results
    rec.clear()
    rec.scene(6)
    rec.caption("c.stats")
    await rec.home()
    await rec.tap("📊")
    rec.wait(3.0)

    rec.events.append({"t": "outro", "title": words["outro.title"], "sub": words["outro.sub"], "cta": words["outro.cta"]})
    rec.save()


@pytest.mark.parametrize("lang", LANGS)
async def test_spot(app: App, lang: str) -> None:
    """The screens of the spot, by name: the spot's timeline (spot.html) decides when each one is on the phone."""
    await prepare(app, lang)
    words = TEXT[lang]
    rec = Recorder(app, SUPER_ID, lang)
    states: dict[str, Any] = {}

    def snap(name: str) -> None:
        """The panel the viewer has on screen now."""
        panel = next(e for e in reversed(rec.events) if e["t"] in ("msg", "edit") and ("rich" in e or "text" in e))
        states[name] = {k: panel[k] for k in ("rich", "text", "photo", "kb") if panel.get(k) is not None}

    await rec.say("/start")
    snap("home")
    await rec.tap("➕")
    snap("add")
    app.fake.add_chat(NEW_CHANNEL, words["new.channel"], members=7815, creator=SUPER_ID)
    await app.feed(app.my_chat_member_update(NEW_CHANNEL, SUPER_ID), MAIN_BOT_ID)
    rec.collect()
    snap("added")
    await rec.home()
    await rec.tap("📝")
    snap("posts")
    await rec.tap(words["post.name"][:12])
    snap("post")
    await rec.tap("🚀")
    snap("confirm")
    await rec.tap("✅")
    await app.publisher.wait_idle(15)
    rec.collect(toasts=True)
    states["channel"] = channel_post(rec, -1001987651000)
    await rec.home()
    await rec.tap("⏰")
    snap("schedule")
    app.fake.add_chat(PARTNER_CHANNEL, words["partner.channel"], members=3460, creator=USER_ID)
    await app.feed(app.my_chat_member_update(PARTNER_CHANNEL, USER_ID), MAIN_BOT_ID)
    rec.collect()
    snap("request")
    await rec.tap("✅")
    states["accepted"] = {**states["request"], "kb": next(e for e in reversed(rec.events) if e["t"] == "edit")["kb"]}
    await rec.home()
    await rec.tap("📣")
    snap("chats")
    await rec.home()
    await rec.tap("📊")
    snap("stats")
    channels = [{"name": n, "members": m} for n, m in zip(words["channels"], (18450, 9320, 4210, 12780, 6540))]
    channels.insert(1, {"name": words["new.channel"], "members": 7815})
    data = {"lang": lang, "bot": words["bot"], "states": states, "channels": channels,
            "partner": {"name": words["partner.name"], "channel": words["partner.channel"]},
            "ui": {k: words[k] for k in ("chats", "message", "menu", "today", "edited", "chat.bot", "channel.mute",
                                         "channel.subs", "views", "picker.title", "picker.cancel", "picker.search",
                                         "picker.subs", "rights.title", "rights.header", "rights.list",
                                         "rights.button", "rights.alert", "rights.ok", "cancel", "back")}}
    (OUT / f"spot_{lang}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
