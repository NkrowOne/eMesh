"""💎 Premium emoji in channels: the `post_premium` screen (canal almacén) and the forwards that arrive there.

See :mod:`app.services.vault`. Groups and private chats get the custom emoji directly (when the bot's owner has
Telegram Premium); channels get the premium copy forwarded from the canal almacén.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from aiogram import Bot, F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.exceptions import TelegramAPIError
from aiogram.filters.callback_data import CallbackData
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.context import Ctx
from app.bot.routers.posts import Event, admin_post, drop_panel, with_notice
from app.config import Settings
from app.db.models import ChatOrigin, Post
from app.i18n import t
from app.services import content, vault
from app.services import publisher as pubsvc
from app.services.chatinfo import add_to_channel_url
from app.services.notify import send_dm
from app.services.users import get_lang
from app.telegram.errors import short
from app.ui import fmt
from app.ui.callbacks import MenuCB
from app.ui.common import alert, back_row, btn, kb, show, toast
from app.ui.screens import screen

if TYPE_CHECKING:
    from app.db.session import SessionMaker
    from app.telegram.manager import BotManager

log = logging.getLogger(__name__)
router = Router(name="premium")


class PmCB(CallbackData, prefix="pm"):
    a: str
    id: int = 0


# ---------------------------------------------------------------------------------------------
# Screen
# ---------------------------------------------------------------------------------------------
async def render(event: Event, ctx: Ctx, session: AsyncSession, post: Post, *, notice: str | None = None,
                 new: bool = False) -> None:
    store = await vault.vault_chat(session, ctx.ws_id)
    lines = [ctx.t("pm.title", name=fmt.esc(post.name)), ctx.t("pm.intro")]
    if store is None:
        lines.append(ctx.t("pm.vault.none"))
    elif vault.usable(store):
        lines.append(ctx.t("pm.vault", name=fmt.esc(store.display_title)))
    else:
        lines.append(ctx.t("pm.vault.gone", name=fmt.esc(store.display_title)))
    ready = content.vault_copy(post) is not None
    if not content.has_premium(post):
        lines.append(ctx.t("pm.st.none"))
    elif ready:
        lines.append(ctx.t("pm.st.ready"))
        if await pubsvc.live_count(session, post.id):
            lines.append(ctx.t("pm.live_hint"))
    else:
        lines.append(ctx.t("pm.st.stale" if post.vault_msg_id else "pm.st.todo"))
    pid = post.id
    markup = kb(
        [btn(ctx.t("pm.b.prepare"), PmCB(a="prep", id=pid), style="success")] if content.has_premium(post) else None,
        [btn(ctx.t("pm.b.add"), url=add_to_channel_url(ctx.ws_rec.username))]
        if not vault.usable(store) and ctx.ws_rec.username else None,
        [btn(ctx.t("pm.b.change"), PmCB(a="chg", id=pid))] if store is not None else None,
        [btn(ctx.t("pm.b.remove"), PmCB(a="rm", id=pid), style="danger")] if post.vault_msg_id else None,
        back_row(ctx.lang, "post", pid),
    )
    if new:
        await drop_panel(event)
    await show(event, with_notice("\n\n".join(lines), notice), markup, new=new)


@screen("post_premium")
async def premium_screen(event: Event, ctx: Ctx, session: AsyncSession, arg: int = 0, **kw: Any) -> None:
    post = await admin_post(event, ctx, session, arg)
    if post is not None:
        await render(event, ctx, session, post, notice=kw.get("notice"))


@router.callback_query(PmCB.filter(F.a == "prep"))
async def on_prepare(call: CallbackQuery, callback_data: PmCB, ctx: Ctx, session: AsyncSession,
                     manager: BotManager, sm: SessionMaker) -> None:
    """📨 The premium message in the admin's private chat, to be forwarded to the canal almacén."""
    post = await admin_post(call, ctx, session, callback_data.id)
    if post is None:
        return
    if not content.has_premium(post):
        await alert(call, ctx.t("pm.st.none"))
        return
    try:
        sent = await content.send_post(call.bot, ctx.user_id, post, manager, sm, protect=False)
    except content.MediaError as exc:
        reason = str(exc) if str(exc) in ("too_big", "unavailable") else "unavailable"
        await alert(call, ctx.t(f"content.err.media_{reason}"))
        return
    except TelegramAPIError as exc:
        log.warning("Premium message of post %s not sent: %s", post.id, short(exc))
        await alert(call, ctx.t("po.preview.failed"))
        return
    if "<tg-emoji" in (post.text or "") and not content.custom_emoji_in(sent):
        # Telegram turned them into normal emoji: the owner of this bot has no Telegram Premium.
        await vault.delete_message(call.bot, sent.chat.id, sent.message_id)
        await alert(call, ctx.t("pm.err.no_premium"))
        return
    await vault.remember_pending(session, ctx.ws_id, sent, post, ctx.user_id)
    store = await vault.vault_chat(session, ctx.ws_id)
    notice = (ctx.t("pm.forward", name=fmt.esc(store.display_title)) if vault.usable(store)
              else ctx.t("pm.forward.first"))
    await render(call, ctx, session, post, notice=notice, new=True)


@router.callback_query(PmCB.filter(F.a == "chg"))
async def on_change(call: CallbackQuery, callback_data: PmCB, ctx: Ctx, session: AsyncSession) -> None:
    post = await admin_post(call, ctx, session, callback_data.id)
    if post is None:
        return
    store = await vault.vault_chat(session, ctx.ws_id)
    if store is None:
        await render(call, ctx, session, post)
        return
    markup = kb([btn(ctx.t("pm.b.change_ok"), PmCB(a="chg_ok", id=post.id), style="danger"),
                 btn(ctx.t("common.no"), MenuCB(screen="post_premium", arg=post.id))])
    await show(call, ctx.t("pm.change.ask", name=fmt.esc(store.display_title)), markup)


@router.callback_query(PmCB.filter(F.a == "chg_ok"))
async def on_change_confirm(call: CallbackQuery, callback_data: PmCB, ctx: Ctx, session: AsyncSession) -> None:
    """The canal almacén stops being one (it receives the network's posts again); the next forward picks another."""
    post = await admin_post(call, ctx, session, callback_data.id)
    if post is None:
        return
    store = await vault.vault_chat(session, ctx.ws_id)
    if store is not None:
        vault.release(store)
        log.info("Network %s: %s is no longer the canal almacén (by %s)", ctx.ws_id, store.chat_id, ctx.user_id)
    await render(call, ctx, session, post, notice=ctx.t("pm.change.done"))


@router.callback_query(PmCB.filter(F.a == "rm"))
async def on_remove(call: CallbackQuery, callback_data: PmCB, ctx: Ctx, session: AsyncSession) -> None:
    """✖️ The channels get the normal message again (the copy in the canal almacén is deleted when possible)."""
    post = await admin_post(call, ctx, session, callback_data.id)
    if post is None:
        return
    bot = ctx.ws_bot()
    if bot is not None and post.vault_chat_id and post.vault_msg_id:
        await vault.delete_message(bot, post.vault_chat_id, post.vault_msg_id)
    vault.unlink(post)
    await toast(call, ctx.t("pm.removed"))
    await render(call, ctx, session, post)


# ---------------------------------------------------------------------------------------------
# The forward arrives in the canal almacén
# ---------------------------------------------------------------------------------------------
@router.channel_post(F.forward_origin.type == "user")
async def on_forward(message: Message, bot: Bot, ctx: Ctx, session: AsyncSession, settings: Settings,
                     manager: BotManager) -> None:
    if ctx.bot_rec.is_main and settings.MAIN_BOT_MODE == "hub":
        raise SkipHandler
    entry = await vault.take_pending(session, bot.id, message.forward_origin)
    if entry is None:
        raise SkipHandler  # any other forward: the other handlers of channel posts
    out = await vault.link(bot, session, message, entry)
    if out.result == vault.LINKED:
        if out.old and out.old != (message.chat.id, message.message_id):
            await vault.delete_message(bot, *out.old)
    elif out.chat is not None and out.chat.origin == ChatOrigin.OWN:
        await vault.delete_message(bot, message.chat.id, message.message_id)  # a useless copy: tidy up
    log.info("Premium copy of post %s in %s: %s", entry.get("post"), message.chat.id, out.result)
    await _tell(ctx, session, manager, entry, out)


async def _tell(ctx: Ctx, session: AsyncSession, manager: BotManager, entry: dict[str, Any],
                out: vault.Outcome) -> None:
    """DM to the admin who prepared the message, from the bot that sent it to them."""
    sender = manager.get(int(entry.get("bot") or 0))
    user_id = int(entry.get("user") or 0)
    if sender is None or not user_id:
        return
    lang = await get_lang(session, sender.id, user_id, ctx.settings.DEFAULT_LANG)
    name = fmt.esc(out.post.name) if out.post is not None else ""
    vault_name = fmt.esc(out.vault.display_title) if out.vault is not None else ""
    text = t(f"pm.dm.{out.result}", lang, name=name, vault=vault_name)
    if out.result == vault.LINKED and out.new_vault:
        text += "\n\n" + t("pm.dm.new_vault", lang, vault=vault_name)
    markup = kb([btn(t("pm.b.open", lang), MenuCB(screen="post_premium", arg=out.post.id))]) \
        if out.post is not None and out.result != vault.CHANGED else None
    await send_dm(sender, session, user_id, text, markup)
