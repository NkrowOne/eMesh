"""In-process fake Telegram Bot API server for end-to-end tests.

It speaks the real HTTP protocol used by aiogram (multipart form posts to /bot<token>/<method>),
keeps a small world model (bots, users, channels/groups, messages, invite links), records every
call, can inject errors (429, 403, 400...) and can enforce Telegram rate limits so tests prove
that the bot never floods.
"""
from __future__ import annotations

import asyncio
import itertools
import json
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Callable

from aiohttp import web

ADMIN_RIGHTS_FULL = {
    "can_be_edited": False,
    "is_anonymous": False,
    "can_manage_chat": True,
    "can_delete_messages": True,
    "can_manage_video_chats": False,
    "can_restrict_members": False,
    "can_promote_members": False,
    "can_change_info": False,
    "can_invite_users": True,
    "can_post_stories": False,
    "can_edit_stories": False,
    "can_delete_stories": False,
    "can_post_messages": True,
    "can_edit_messages": True,
    "can_pin_messages": True,
    "can_send_welcome_messages": False,
}

_JSON_FIELDS = {
    "reply_markup", "link_preview_options", "allowed_updates", "message_ids", "entities", "caption_entities",
    "reply_parameters", "commands", "scope", "media", "added_user_ids", "prices",
}


@dataclass
class Call:
    token: str
    method: str
    params: dict[str, Any]
    ts: float = field(default_factory=time.monotonic)
    result: Any = None

    @property
    def chat_id(self) -> Any:
        return self.params.get("chat_id")


@dataclass
class FakeChat:
    id: int
    type: str  # channel | supergroup | group | private
    title: str = ""
    username: str | None = None
    members: int = 1000
    # bot_id -> admin rights dict (None = bot is not admin / not member)
    bot_admin: dict[int, dict[str, Any] | None] = field(default_factory=dict)
    messages: dict[int, dict[str, Any]] = field(default_factory=dict)
    links: dict[str, dict[str, Any]] = field(default_factory=dict)
    pinned: list[int] = field(default_factory=list)
    first_name: str = ""
    creator: int | None = None  # user id of the creator (getChatAdministrators)
    description: str | None = None  # bio returned by getChat
    auto_delete: int | None = None  # message_auto_delete_time (seconds) returned by getChat
    kicked: set[int] = field(default_factory=set)  # users in "Removed users" (getChatMember: kicked)


@dataclass
class Failure:
    method: str
    predicate: Callable[[dict[str, Any]], bool]
    error: dict[str, Any]
    times: int = 1


class FakeTelegram:
    def __init__(self, *, strict_limits: bool = False, global_per_sec: int = 30, group_per_min: int = 20) -> None:
        self.calls: list[Call] = []
        self.bots: dict[str, dict[str, Any]] = {}  # token -> user json
        self.users: dict[int, dict[str, Any]] = {}
        self.blocked: set[tuple[int, int]] = set()  # (bot_id, user_id) the user blocked the bot
        self.chats: dict[int, FakeChat] = {}
        self.updates: dict[str, deque[dict[str, Any]]] = defaultdict(deque)
        self.failures: list[Failure] = []
        self.managed_tokens: dict[int, str] = {}
        self.star_balance: dict[int, int] = {}  # bot id -> stars (getMyStarBalance)
        self._invoice_ids = itertools.count(1)
        self.files: dict[str, bytes] = {}
        self.profile_photos: dict[int, str] = {}  # bot/user id -> file_unique_id of its profile photo
        self.profile_uploads: dict[int, bytes] = {}  # bot id -> bytes of the last setMyProfilePhoto
        self._photo_uids = itertools.count(1)
        self._msg_ids: dict[int, itertools.count] = defaultdict(lambda: itertools.count(1000))
        self._update_ids = itertools.count(1)
        self._file_ids = itertools.count(1)
        self.strict_limits = strict_limits
        self.global_per_sec = global_per_sec
        self.group_per_min = group_per_min
        self._sends: dict[str, deque[float]] = defaultdict(deque)
        self._chat_sends: dict[tuple[str, int], deque[float]] = defaultdict(deque)
        self.limit_violations = 0
        self.base_url = ""
        self._runner: web.AppRunner | None = None

    # ------------------------------------------------------------------ setup
    async def start(self) -> None:
        app = web.Application(client_max_size=50 * 1024 * 1024)
        app.router.add_post("/bot{token}/{method}", self._handle)
        app.router.add_get("/file/bot{token}/{path:.*}", self._file)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]
        self.base_url = f"http://127.0.0.1:{port}"

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()

    def add_bot(self, bot_id: int, username: str, *, first_name: str = "Bot", can_manage_bots: bool = False) -> str:
        token = f"{bot_id}:TEST{bot_id}"
        self.bots[token] = {
            "id": bot_id, "is_bot": True, "first_name": first_name, "username": username,
            "can_join_groups": True, "can_read_all_group_messages": False, "supports_inline_queries": False,
            "can_connect_to_business": False, "has_main_web_app": False, "can_manage_bots": can_manage_bots,
        }
        return token

    def add_user(self, user_id: int, first_name: str = "User", username: str | None = None, lang: str = "es") -> dict:
        user = {"id": user_id, "is_bot": False, "first_name": first_name, "language_code": lang}
        if username:
            user["username"] = username
        self.users[user_id] = user
        return user

    def add_chat(self, chat_id: int, title: str, *, type: str = "channel", members: int = 1000,
                 username: str | None = None, admin_bots: dict[int, dict[str, Any] | None] | None = None,
                 creator: int | None = None) -> FakeChat:
        chat = FakeChat(id=chat_id, type=type, title=title, username=username, members=members, creator=creator)
        for bot_id, rights in (admin_bots or {}).items():
            chat.bot_admin[bot_id] = dict(ADMIN_RIGHTS_FULL) if rights == "full" else rights
        self.chats[chat_id] = chat
        return chat

    def fail(self, method: str, *, code: int = 400, description: str = "Bad Request: error",
             retry_after: int | None = None, times: int = 1,
             when: Callable[[dict[str, Any]], bool] | None = None,
             parameters: dict[str, Any] | None = None) -> None:
        err: dict[str, Any] = {"ok": False, "error_code": code, "description": description}
        if retry_after is not None:
            err["parameters"] = {"retry_after": retry_after}
        if parameters:
            err["parameters"] = {**err.get("parameters", {}), **parameters}
        self.failures.append(Failure(method, when or (lambda p: True), err, times))

    # --------------------------------------------------------------- queries
    def calls_of(self, method: str, **match: Any) -> list[Call]:
        out = []
        for c in self.calls:
            if c.method != method:
                continue
            if all(str(c.params.get(k)) == str(v) for k, v in match.items()):
                out.append(c)
        return out

    def last(self, method: str, **match: Any) -> Call | None:
        found = self.calls_of(method, **match)
        return found[-1] if found else None

    def messages_to(self, chat_id: int) -> list[Call]:
        send = {"sendMessage", "sendPhoto", "sendVideo", "sendAnimation", "sendDocument", "sendAudio", "sendVoice",
                "copyMessage"}
        return [c for c in self.calls if c.method in send and str(c.chat_id) == str(chat_id)]

    def reset_calls(self) -> None:
        self.calls.clear()

    # ------------------------------------------------------------- updates
    def push_update(self, token: str, update: dict[str, Any]) -> None:
        update = {"update_id": next(self._update_ids), **update}
        self.updates[token].append(update)

    def new_update_id(self) -> int:
        return next(self._update_ids)

    # -------------------------------------------------------------- server
    async def _parse(self, request: web.Request) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if request.content_type.startswith("application/json"):
            params = await request.json()
        else:
            form = await request.post()
            for key, value in form.items():
                if isinstance(value, web.FileField):
                    data = value.file.read()
                    fid = f"upl{next(self._file_ids)}"
                    self.files[fid] = data
                    params[key] = fid
                    continue
                params[key] = value
        for key in list(params):
            value = params[key]
            if isinstance(value, str) and (key in _JSON_FIELDS or value[:1] in "[{"):
                try:
                    params[key] = json.loads(value)
                except ValueError:
                    pass
            if isinstance(value, str) and key in {"chat_id", "user_id", "message_id", "from_chat_id", "offset"}:
                if value.lstrip("-").isdigit():
                    params[key] = int(value)
        if isinstance(params.get("attach"), str):
            pass
        for key, value in list(params.items()):
            if isinstance(value, str) and value.startswith("attach://"):
                params[key] = params.get(value[len("attach://"):], value)
        return params

    async def _file(self, request: web.Request) -> web.Response:
        path = request.match_info["path"]
        data = self.files.get(path.split("/")[-1], b"FAKEFILE")
        return web.Response(body=data)

    def _check_limits(self, token: str, method: str, params: dict[str, Any]) -> dict[str, Any] | None:
        if not self.strict_limits or method not in {"sendMessage", "sendPhoto", "sendVideo", "sendAnimation",
                                                     "sendDocument", "sendAudio", "sendVoice", "copyMessage",
                                                     "editMessageText", "editMessageCaption",
                                                     "editMessageReplyMarkup"}:
            return None
        now = time.monotonic()
        g = self._sends[token]
        while g and now - g[0] > 1.0:
            g.popleft()
        chat_id = params.get("chat_id")
        violated = len(g) >= self.global_per_sec
        if isinstance(chat_id, int) and chat_id < 0:
            q = self._chat_sends[(token, chat_id)]
            while q and now - q[0] > 60.0:
                q.popleft()
            if len(q) >= self.group_per_min:
                violated = True
            else:
                q.append(now)
        if violated:
            self.limit_violations += 1
            return {"ok": False, "error_code": 429, "description": "Too Many Requests: retry after 1",
                    "parameters": {"retry_after": 1}}
        g.append(now)
        return None

    async def _handle(self, request: web.Request) -> web.Response:
        token = request.match_info["token"]
        method = request.match_info["method"]
        params = await self._parse(request)
        if token not in self.bots:
            return web.json_response({"ok": False, "error_code": 401, "description": "Unauthorized"}, status=401)
        call = Call(token, method, params)
        if method != "getUpdates":
            self.calls.append(call)
        for f in list(self.failures):
            if f.method == method and f.predicate(params):
                f.times -= 1
                if f.times <= 0:
                    self.failures.remove(f)
                return web.json_response(f.error, status=f.error["error_code"])
        limited = self._check_limits(token, method, params)
        if limited:
            return web.json_response(limited, status=429)
        handler = getattr(self, f"m_{method}", None)
        if handler is None:
            result: Any = True
        else:
            try:
                result = handler(token, params)
                if asyncio.iscoroutine(result):
                    result = await result
            except ApiError as exc:
                return web.json_response(
                    {"ok": False, "error_code": exc.code, "description": exc.description}, status=exc.code
                )
        call.result = result
        return web.json_response({"ok": True, "result": result})

    # ------------------------------------------------------------- helpers
    def bot_user(self, token: str) -> dict[str, Any]:
        return self.bots[token]

    def bot_id(self, token: str) -> int:
        return self.bots[token]["id"]

    def chat_json(self, chat_id: int, token: str | None = None) -> dict[str, Any]:
        if chat_id > 0:
            user = self.users.get(chat_id, {"id": chat_id, "first_name": "User"})
            return {"id": chat_id, "type": "private", "first_name": user.get("first_name", "User")}
        chat = self.chats[chat_id]
        out: dict[str, Any] = {"id": chat.id, "type": chat.type, "title": chat.title}
        if chat.username:
            out["username"] = chat.username
        return out

    def _require_chat(self, token: str, chat_id: Any, *, need: str | None = None) -> FakeChat | None:
        if not isinstance(chat_id, int):
            raise ApiError(400, "Bad Request: chat not found")
        if chat_id > 0:
            if (self.bot_id(token), chat_id) in self.blocked:
                raise ApiError(403, "Forbidden: bot was blocked by the user")
            if chat_id not in self.users:
                raise ApiError(400, "Bad Request: chat not found")
            return None
        chat = self.chats.get(chat_id)
        if chat is None:
            raise ApiError(400, "Bad Request: chat not found")
        bot_id = self.bot_id(token)
        if bot_id not in chat.bot_admin:
            raise ApiError(403, "Forbidden: bot is not a member of the channel chat")
        rights = chat.bot_admin[bot_id]
        if need and (rights is None or not rights.get(need)):
            raise ApiError(400, "Bad Request: not enough rights to send text messages to the chat")
        return chat

    def _new_message(self, token: str, chat_id: int, extra: dict[str, Any]) -> dict[str, Any]:
        mid = next(self._msg_ids[chat_id])
        msg = {"message_id": mid, "date": int(time.time()), "chat": self.chat_json(chat_id, token), **extra}
        if chat_id > 0:
            msg["from"] = self.bot_user(token)
        elif self.chats[chat_id].type != "channel":
            msg["from"] = self.bot_user(token)
        else:
            msg["sender_chat"] = self.chat_json(chat_id, token)
        if chat_id < 0:
            self.chats[chat_id].messages[mid] = msg
        return msg

    def _markup(self, params: dict[str, Any]) -> dict[str, Any]:
        return {"reply_markup": params["reply_markup"]} if isinstance(params.get("reply_markup"), dict) else {}

    def _photo(self, fid: str) -> list[dict[str, Any]]:
        return [{"file_id": fid, "file_unique_id": f"u{fid}", "width": 90, "height": 90}]

    # ------------------------------------------------------------- methods
    def m_getMe(self, token: str, p: dict[str, Any]) -> dict[str, Any]:
        return self.bot_user(token)

    async def m_getUpdates(self, token: str, p: dict[str, Any]) -> list[dict[str, Any]]:
        offset = p.get("offset")
        q = self.updates[token]
        if isinstance(offset, int):
            while q and q[0]["update_id"] < offset:
                q.popleft()
        if not q:
            await asyncio.sleep(0.05)
        return list(q)[:100]

    def _sender_check(self, token: str, p: dict[str, Any]) -> None:
        chat_id = p.get("chat_id")
        chat = self._require_chat(token, chat_id)
        if chat is not None and chat.type == "channel":
            rights = chat.bot_admin.get(self.bot_id(token))
            if not rights or not rights.get("can_post_messages"):
                raise ApiError(400, "Bad Request: need administrator rights in the channel chat")

    def m_sendMessage(self, token: str, p: dict[str, Any]) -> dict[str, Any]:
        self._sender_check(token, p)
        return self._new_message(token, p["chat_id"], {"text": p.get("text", ""), **self._markup(p)})

    def m_sendPhoto(self, token: str, p: dict[str, Any]) -> dict[str, Any]:
        self._sender_check(token, p)
        extra = {"photo": self._photo(str(p.get("photo"))), **self._markup(p)}
        if p.get("caption"):
            extra["caption"] = p["caption"]
        return self._new_message(token, p["chat_id"], extra)

    def _media(self, kind: str, token: str, p: dict[str, Any]) -> dict[str, Any]:
        self._sender_check(token, p)
        fid = str(p.get(kind))
        obj: dict[str, Any] = {"file_id": fid, "file_unique_id": f"u{fid}", "width": 10, "height": 10, "duration": 1}
        extra = {kind: obj, **self._markup(p)}
        if p.get("caption"):
            extra["caption"] = p["caption"]
        return self._new_message(token, p["chat_id"], extra)

    def m_sendVideo(self, token: str, p: dict[str, Any]) -> dict[str, Any]:
        return self._media("video", token, p)

    def m_sendAnimation(self, token: str, p: dict[str, Any]) -> dict[str, Any]:
        return self._media("animation", token, p)

    def m_answerCallbackQuery(self, token: str, p: dict[str, Any]) -> bool:
        text = str(p.get("text") or "")
        if len(text.encode("utf-16-le")) // 2 > 200:  # Telegram's limit for the popup text
            raise ApiError(400, "Bad Request: MESSAGE_TOO_LONG")
        return True

    def m_sendDocument(self, token: str, p: dict[str, Any]) -> dict[str, Any]:
        self._sender_check(token, p)
        fid = str(p.get("document"))
        extra: dict[str, Any] = {"document": {"file_id": fid, "file_unique_id": f"u{fid}"}, **self._markup(p)}
        if p.get("caption"):
            extra["caption"] = p["caption"]
        return self._new_message(token, p["chat_id"], extra)

    def m_sendAudio(self, token: str, p: dict[str, Any]) -> dict[str, Any]:
        return self._media("audio", token, p)

    def m_sendVoice(self, token: str, p: dict[str, Any]) -> dict[str, Any]:
        return self._media("voice", token, p)

    def m_copyMessage(self, token: str, p: dict[str, Any]) -> dict[str, Any]:
        self._sender_check(token, p)
        msg = self._new_message(token, p["chat_id"], {"text": "copy"})
        return {"message_id": msg["message_id"]}

    def _edit(self, token: str, p: dict[str, Any], fields: dict[str, Any]) -> Any:
        chat_id = p.get("chat_id")
        mid = p.get("message_id")
        if isinstance(chat_id, int) and chat_id < 0:
            chat = self._require_chat(token, chat_id)
            assert chat is not None
            msg = chat.messages.get(int(mid)) if mid is not None else None
            if msg is None:
                raise ApiError(400, "Bad Request: message to edit not found")
            same = all(msg.get(k) == v for k, v in fields.items())
            if same:
                raise ApiError(400, "Bad Request: message is not modified: specified new message content and "
                                    "reply markup are exactly the same as a current content and reply markup")
            msg.update(fields)
            return msg
        return {"message_id": int(mid or 1), "date": int(time.time()), "chat": self.chat_json(int(chat_id), token),
                "from": self.bot_user(token), **fields}

    def m_editMessageText(self, token: str, p: dict[str, Any]) -> Any:
        return self._edit(token, p, {"text": p.get("text", ""), **self._markup(p)})

    def m_editMessageCaption(self, token: str, p: dict[str, Any]) -> Any:
        return self._edit(token, p, {"caption": p.get("caption", ""), **self._markup(p)})

    def m_editMessageReplyMarkup(self, token: str, p: dict[str, Any]) -> Any:
        return self._edit(token, p, self._markup(p) or {"reply_markup": None})

    def m_deleteMessage(self, token: str, p: dict[str, Any]) -> bool:
        chat_id = p.get("chat_id")
        if isinstance(chat_id, int) and chat_id < 0:
            chat = self._require_chat(token, chat_id)
            assert chat is not None
            if chat.messages.pop(int(p["message_id"]), None) is None:
                raise ApiError(400, "Bad Request: message to delete not found")
        return True

    def m_deleteMessages(self, token: str, p: dict[str, Any]) -> bool:
        chat_id = p.get("chat_id")
        if isinstance(chat_id, int) and chat_id < 0:
            chat = self._require_chat(token, chat_id)
            assert chat is not None
            for mid in p.get("message_ids") or []:
                chat.messages.pop(int(mid), None)
        return True

    def m_pinChatMessage(self, token: str, p: dict[str, Any]) -> bool:
        chat = self._require_chat(token, p.get("chat_id"))
        if chat is not None:
            if int(p["message_id"]) not in chat.messages:
                raise ApiError(400, "Bad Request: message to pin not found")
            chat.pinned.append(int(p["message_id"]))
        return True

    def m_unpinChatMessage(self, token: str, p: dict[str, Any]) -> bool:
        chat = self._require_chat(token, p.get("chat_id"))
        if chat is not None and int(p.get("message_id", 0)) in chat.pinned:
            chat.pinned.remove(int(p["message_id"]))
        return True

    def m_getChat(self, token: str, p: dict[str, Any]) -> dict[str, Any]:
        chat_id = p.get("chat_id")
        if isinstance(chat_id, str) and chat_id.startswith("@"):
            # Public chats can be read by username even when the bot is not a member.
            chat_id = next((c.id for c in self.chats.values()
                            if c.username and c.username.lower() == chat_id[1:].lower()), None)
            if chat_id is None:
                raise ApiError(400, "Bad Request: chat not found")
        elif isinstance(chat_id, int) and chat_id < 0:
            self._require_chat(token, chat_id)
        out = self.chat_json(int(chat_id), token)
        chat = self.chats.get(int(chat_id))
        if chat is not None and chat.description:
            out["description"] = chat.description
        if chat is not None and chat.auto_delete:
            out["message_auto_delete_time"] = chat.auto_delete
        out.update({"accent_color_id": 0, "max_reaction_count": 11,
                    "accepted_gift_types": {"unlimited_gifts": False, "limited_gifts": False,
                                            "unique_gifts": False, "premium_subscription": False,
                                            "gifts_from_channels": False}})
        return out

    def m_getChatMemberCount(self, token: str, p: dict[str, Any]) -> int:
        chat = self._require_chat(token, p.get("chat_id"))
        return chat.members if chat else 1

    def m_getChatMember(self, token: str, p: dict[str, Any]) -> dict[str, Any]:
        chat_id = p.get("chat_id")
        user_id = int(p["user_id"])
        chat = self.chats.get(chat_id) if isinstance(chat_id, int) else None
        if chat is None:
            raise ApiError(400, "Bad Request: chat not found")
        if user_id in {b["id"] for b in self.bots.values()}:
            bot_user = next(b for b in self.bots.values() if b["id"] == user_id)
            if user_id not in chat.bot_admin:
                if self.bot_id(self._token_of(user_id)) == user_id and user_id not in chat.bot_admin:
                    raise ApiError(403, "Forbidden: bot is not a member of the channel chat")
            rights = chat.bot_admin.get(user_id)
            if rights is None:
                return {"status": "member", "user": bot_user}
            return {"status": "administrator", "user": bot_user, **rights}
        user = self.users.get(user_id, {"id": user_id, "is_bot": False, "first_name": "User"})
        if user_id in chat.kicked:
            return {"status": "kicked", "user": user, "until_date": 0}
        return {"status": "member", "user": user}

    def m_getChatAdministrators(self, token: str, p: dict[str, Any]) -> list[dict[str, Any]]:
        chat = self._require_chat(token, p.get("chat_id"))
        assert chat is not None
        out: list[dict[str, Any]] = []
        if chat.creator is not None:
            user = self.users.get(chat.creator, {"id": chat.creator, "is_bot": False, "first_name": "User"})
            out.append({"status": "creator", "user": user, "is_anonymous": False})
        for bot_id, rights in chat.bot_admin.items():
            if rights is not None:
                bot_user = next(b for b in self.bots.values() if b["id"] == bot_id)
                out.append({"status": "administrator", "user": bot_user, **rights})
        return out

    def _token_of(self, bot_id: int) -> str:
        return next(t for t, b in self.bots.items() if b["id"] == bot_id)

    def m_createChatInviteLink(self, token: str, p: dict[str, Any]) -> dict[str, Any]:
        chat = self._require_chat(token, p.get("chat_id"), need="can_invite_users")
        assert chat is not None
        code = f"+{abs(chat.id)}x{len(chat.links) + 1}"
        link = {
            "invite_link": f"https://t.me/{code}",
            "creator": self.bot_user(token),
            "creates_join_request": str(p.get("creates_join_request", "false")).lower() == "true",
            "is_primary": False,
            "is_revoked": False,
        }
        if p.get("name"):
            link["name"] = p["name"]
        chat.links[link["invite_link"]] = link
        return link

    def m_editChatInviteLink(self, token: str, p: dict[str, Any]) -> dict[str, Any]:
        chat = self._require_chat(token, p.get("chat_id"), need="can_invite_users")
        assert chat is not None
        link = chat.links.get(p.get("invite_link"))
        if link is None:
            raise ApiError(400, "Bad Request: INVITE_HASH_EXPIRED")
        if p.get("name"):
            link["name"] = p["name"]
        return link

    def revoke_links(self, chat_id: int) -> None:
        self.chats[chat_id].links.clear()

    def m_leaveChat(self, token: str, p: dict[str, Any]) -> bool:
        chat = self.chats.get(p.get("chat_id"))
        if chat:
            chat.bot_admin.pop(self.bot_id(token), None)
        return True

    def m_createInvoiceLink(self, token: str, p: dict[str, Any]) -> str:
        return f"https://t.me/$inv{self.bot_id(token)}_{next(self._invoice_ids)}"

    def m_getMyStarBalance(self, token: str, p: dict[str, Any]) -> dict[str, Any]:
        return {"amount": self.star_balance.get(self.bot_id(token), 0)}

    def m_getManagedBotToken(self, token: str, p: dict[str, Any]) -> str:
        return self.managed_tokens[int(p["user_id"])]

    def m_getMyName(self, token: str, p: dict[str, Any]) -> dict[str, Any]:
        return {"name": self.bots[token].get("first_name", "Bot")}

    def m_getMyDescription(self, token: str, p: dict[str, Any]) -> dict[str, Any]:
        return {"description": self.bots[token].get("description", "")}

    def m_getMyShortDescription(self, token: str, p: dict[str, Any]) -> dict[str, Any]:
        return {"short_description": self.bots[token].get("short_description", "")}

    def m_getUserProfilePhotos(self, token: str, p: dict[str, Any]) -> dict[str, Any]:
        uid = self.profile_photos.get(int(p.get("user_id") or 0))
        if uid is None:
            return {"total_count": 0, "photos": []}
        return {"total_count": 1,
                "photos": [[{"file_id": f"pf_{uid}", "file_unique_id": uid, "width": 640, "height": 640}]]}

    def m_setMyProfilePhoto(self, token: str, p: dict[str, Any]) -> bool:
        photo = p.get("photo") if isinstance(p.get("photo"), dict) else {}
        ref = str(photo.get("photo") or "")
        upload = p.get(ref[len("attach://"):]) if ref.startswith("attach://") else None
        if not isinstance(upload, str) or upload not in self.files or photo.get("type") != "static":
            raise ApiError(400, "Bad Request: photo must be uploaded as a new static file")
        bot_id = self.bot_id(token)
        self.profile_uploads[bot_id] = self.files[upload]
        self.profile_photos[bot_id] = f"profile{next(self._photo_uids)}"
        return True

    def m_removeMyProfilePhoto(self, token: str, p: dict[str, Any]) -> bool:
        self.profile_photos.pop(self.bot_id(token), None)
        return True

    def m_getFile(self, token: str, p: dict[str, Any]) -> dict[str, Any]:
        fid = str(p.get("file_id"))
        return {"file_id": fid, "file_unique_id": f"u{fid}", "file_size": 8, "file_path": f"photos/{fid}"}

    def m_copyMessages(self, token: str, p: dict[str, Any]) -> list[dict[str, Any]]:
        return [{"message_id": next(self._msg_ids[int(p["chat_id"])])}]

    def kick_user(self, chat_id: int, user_id: int) -> None:
        """Puts a user in the "Removed users" list of a chat: getChatMember answers ``kicked`` for them."""
        self.chats[chat_id].kicked.add(user_id)


class ApiError(Exception):
    def __init__(self, code: int, description: str) -> None:
        super().__init__(description)
        self.code = code
        self.description = description
