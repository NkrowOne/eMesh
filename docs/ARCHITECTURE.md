# eMesh — Architecture & build spec

eMesh is a Telegram **distribution network** platform. An owner adds their bot to their channels and groups (and,
if they want, lets other people add theirs: *partners*), writes **posts** (text or media with colored buttons) and
the bot publishes them into the chats on a schedule. **Frequencies** say how often each chat receives a post: one
global frequency, or a custom one per **group of chats**. Posts in *rotation* take turns in each chat. Partners can
**pause** the distribution in their chats whenever they want; the owner is alerted and sees it in their panel.
One process runs the **main bot** (the platform: creates clones, 👑 panel, and its own network) plus any number of
**clones** (bots of other owners, each one with its own network). A super admin controls every clone from the main
bot and can even manage a clone's network from there (🛠 Gestionar).

Stack: Python 3.12+, **aiogram 3.31 (Bot API 10.3)**, SQLAlchemy 2.1 async (PostgreSQL in prod, SQLite in tests),
Alembic, pydantic-settings. Run: `python -m app`. The infrastructure comes from eButtons (same author): multi-bot
manager, rate limiter, FSM storage, `show()`/`btn()` UI helpers, screens registry, i18n, fake Telegram for tests.

Vocabulary (code → UI, Spanish):

| Code | UI | What |
|---|---|---|
| `Bot` | bot / red | a bot run by the platform; its *network* = its chats, groups, posts and settings |
| `Chat` | 📣 Canal / 👥 Grupo | a channel or group of a bot. `origin` own (🏠 Propio) or ext (🤝 Externo, a partner's) |
| `ChatGroup` | 🗂 Grupo de canales | custom set of chats: a target for posts and, optionally, its own frequency |
| `Post` | 📝 Mensaje | content + buttons + targets + schedule + options |
| `Run` | envío | one distribution of a post to a set of chats |
| `Delivery` | — | the post inside one chat (Telegram message id, auto delete) |
| `Event` | 📜 Actividad | log of what happened to chats (and alerts to admins) |
| partner | dueño de un canal externo | a user (role `user`) whose external chat is in the network |

Never write "grupo" alone for a `ChatGroup` in the UI: always "grupo de canales" or the 🗂 icon + its name, so it is
never confused with a Telegram group (👥).

---------------------------------------------------------------------------------------------------
## 1. Ground rules (read before writing code)

* **Only edit the files you own** (section 9). Need something from another module? Use the documented interfaces
  (section 7) and the screen names (section 5). If an interface is missing, write a tiny private helper in your own
  file and mention it in your final report. **Never edit core files** (section 2): report what you need instead.
* Handler signature: aiogram injects `ctx: Ctx`, `session: AsyncSession`, `state: FSMContext`, `bot`, and
  `manager`, `publisher`, `scheduler`, `settings`, `sm` (sessionmaker). Just declare the parameters you need.
* The DB session of a handler is committed by the middleware after the handler (rolled back on error). Don't commit
  inside handlers unless you must (e.g. before starting a background task that reads the row).
* **Background tasks** (anything not answering the user right now) open their own sessions with
  `session_scope(sm)`, call `app.telegram.context.set_low_priority()` first, keep transactions short (never hold a
  session open across many Telegram calls; commit in batches). Keep a reference to tasks you create
  (`asyncio.create_task`) in a module/instance set so they aren't garbage collected.
* **JSON columns**: never mutate in place; assign a new list/dict (`post.buttons = new_rows`).
* All user visible text goes through i18n: `ctx.t("key", **kw)` / `t("key", lang)`. Strings are HTML
  (`parse_mode=HTML` is the default). **Escape every user provided value** with `app.ui.fmt.esc()` (chat titles,
  names, post names, usernames). Post content (`Post.text`) is HTML produced by Telegram (`message.html_text`):
  never escape it again, never show it inside other HTML except with `content.plain()` + `esc()` for summaries.
* **Impersonal tone**: the bot never speaks in first person. «Se ha pausado…», «No se ha podido enviar…»,
  «Faltan permisos…», «Se avisará…» (not «He pausado», «No he podido»). English: passive voice.
* **Name the kind of chat** in sentences: «tu canal <b>X</b>», «el grupo <b>X</b>» (`chatstate.kind_word(chat, lang)`).
* **Wording**: Spanish says «multimedia» / «contenido multimedia», never «la media». No option is ever marked
  «(recomendado)».
* UI helpers (`app/ui/common.py`): `show(event, text, markup, media_id=, media_type=, new=)` renders a panel (edits
  on callbacks, sends on messages), `prompt(event, ctx, text, cancel_screen=, cancel_arg=, extra_rows=, back=,
  media_id=, media_type=)` asks for input with a Cancel button: **a prompt is always a new message at the bottom of
  the chat** (nothing covers it) and the message it replaces is deleted (the panel of the pressed button, or the
  previous prompt); once answered, the next panel replaces it. `btn(text, cb|url=, style=, disabled=)`, `kb(*rows)`, `grid()`, `paginate()`,
  `nav_row()`, `back_row(lang, screen, arg)`, `toggle_label`, `choice_label`, `toast(event, text)`,
  `alert(event, text)`, `visible_len`. **Never call `callback.answer()` directly** — use `toast/alert`; a middleware
  answers the rest. Only one popup per button press.
* **Screens**: every panel reachable from other modules is registered with `@screen("name")`
  (`async def fn(event, ctx, session, arg=0, **kw)`) and opened with `MenuCB(screen="name", arg=N)` buttons or
  `await open_screen("name", event, ctx, session, arg=N)`. `MenuCB` clears the FSM state. Use screens for
  "Regresar" buttons. A screen that needs other services (publisher, manager…) gets them from
  `event.bot`/`ctx.manager` or receives them through `**kw` when you call it yourself; via `MenuCB` only `arg` is
  available (use `ctx.manager`).
* **Callback data**: each module defines its own `CallbackData` classes with its assigned prefixes (section 9).
  Max 64 bytes: use ids and short action names. Bot ids are big integers (fine in `int` fields).
* **FSM**: each module defines its own `StatesGroup` whose class name starts with the module name (`PostsFSM`,
  `ChatsFSM`...). Clear the state when done. Text input handlers must ignore commands
  (`~F.text.startswith("/")`, the start module handles `/cancel`) and the Cancel button (`prompt()` adds it).
* **Permissions**: check `ctx.is_admin` / `ctx.is_owner` / `ctx.is_super` in every handler that changes data
  (callback data can be forged). **Always check that loaded rows belong to `ctx.ws_id`** (`chat.bot_id == ctx.ws_id`,
  `post.bot_id == ctx.ws_id`...). A partner (role user) may only touch external chats whose
  `owner_user_id == ctx.user_id`.
* **Workspace** (section 11): network data is the data of `ctx.ws_id`, not `ctx.bot_id`. Chat API calls on network
  chats (send, leave, getChat…) go through `ctx.ws_bot()` (None → `alert(common.not_running)`); answers to the user
  go through the update's bot (`show`, `prompt`, `event.bot`). "Add to channel" URLs use `ctx.ws_rec.username`.
* **Telegram limits** are handled centrally (`app/telegram/ratelimit.py`): just call the API, never add sleeps.
  Use `app/telegram/errors.py` helpers to classify exceptions. Catch `TelegramAPIError` around calls that can fail
  for reasons outside our control (chats, other users).
* Message limits: text 4096, caption 1024 (visible chars, `visible_len`), callback data 64 bytes, button text ≤ 64,
  inline keyboard ≤ 100 buttons.
* Style: English identifiers, Spanish/English UI via i18n, type hints, small functions, comments only for non
  obvious logic, no prints (use `logging`). Keep it simple; no speculative features.
* Content: never seed/example adult content. Demo names like "Canal de Cine", "Promo Cine".

---------------------------------------------------------------------------------------------------
## 2. Core (already written — use it, don't change it)

| File | What |
|---|---|
| `app/config.py` | `Settings`: `super_admin_ids`, `MAIN_BOT_MODE` (`full`/`hub`), `SCHEDULER_TICK_SECONDS`, `LATE_SKIP_MINUTES`, `SEND_CONCURRENCY`, `MAINTENANCE_INTERVAL_HOURS`, `SUMMARY_HOUR`, `RETENTION_DAYS`, `CLONE_POLICY`, `MAX_CLONES_PER_USER`, `DEFAULT_LIMIT_CHATS/POSTS`. |
| `app/db/models.py` | All tables + constants (`BotStatus`, `Role`, `ChatOrigin`, `ChatStatus`, `PostStatus`, `SchedMode`, `RotationOrder`, `RunKind`, `RunStatus`, `DeliveryStatus`, `EventKind`, `DEFAULT_FREQ`). `Chat.owner_pause_active(now)`, `Chat.is_paused(now)`, `Chat.is_external`, `display_title`. |
| `app/db/session.py` | `session_scope(sm)`, `LeaderLock`. `app/db/base.py`: `utcnow()`. |
| `app/telegram/manager.py` | `BotManager`: `get(bot_id) -> Bot`, `main_bot`, `main_bot_id`, `main_bot_ids`, `add_bot(token, owner_id, managed=, pending=)`, `validate_token`, `stop_bot(bot_id, withdraw=)`, `disable_bot(bot_id, reason)` (deletes pending auto deletes first through `Publisher.withdraw_bot`), `enable_bot`, `is_running`, `on_bot_invalid` callbacks, `cipher`, `BotTokenError(code)`: format/unauthorized/network/not_bot/is_main/taken. |
| `app/telegram/ratelimit.py`, `context.py`, `errors.py` | Rate limits per bot (global 27/s, bulk 20/s LOW priority, 1/s per private chat, 19/min per group/channel, 429/5xx retries); `set_low_priority()`, `bot_scope()`; error classifiers `is_not_modified`, `is_message_gone`, `is_cant_delete`, `is_chat_gone`, `is_user_blocked`, `is_rights_error`, `is_parse_error`, `is_topic_error`, `is_button_error`, `is_outcome_unknown`, `migrated_to`, `short`. |
| `app/bot/context.py` | `Ctx`: `bot_rec`, `bot_id`, `ws_rec`, `ws_id`, `in_ws`, `ws_bot()`, `user`, `user_id`, `bu`, `role`, `lang`, `settings`, `manager`, `is_super/is_owner/is_admin/is_main/is_hub`, `bot_tz` (workspace timezone), `tz` (display timezone of the user), `t()`. |
| `app/bot/filters.py` | `IsAdmin`, `IsOwner`, `IsSuper`, `RoleFilter`, `MainBotFilter`, `PrivateFilter`. |
| `app/bot/routers/core.py` | `MenuCB` → screens, `NoopCB`, `CloseCB` (deletes its message), `InputCancelCB`, fallbacks, error handler. |
| `app/ui/*` | `common.py` (above; `ws_banner` is added on top of every panel while managing a clone), `fmt.py` (`esc`, `num` → `270,934`, `dt` → `01/11/2026 11:00 AM`, `hm`, `onoff`, `user_link`, `link`, `truncate`, `zone`, `to_local`), `callbacks.py`, `screens.py` (`HUB_HIDDEN`). |
| `app/i18n` | `t(key, lang, **kw)`, `LANG_NAMES`, `LANG_FLAGS`, `SUPPORTED_LANGS` (es, en), `normalize_lang`. Core keys: `common.*`, `weekday.*`, `color.*`, `rights.*`, `ws.banner`, `ev.*`, `cs.*`, `freq.*`, `content.*`. |
| `app/services/users.py` | `admin_ids(session, bot_rec)` (owner first), `admins`, `find_bot_user(session, bot_id, "@user"/id)`, `get_lang`. |
| `app/services/notify.py` | `send_dm(bot, session, user_id, text, markup)` (never raises, marks blocked), `notify_admins(bot, session, bot_rec, render(lang)->(text, markup))`. |
| `app/services/chatinfo.py` | `add_to_channel_url(username)`, `add_to_group_url(username)` (rights pre-selected: channels post+edit+delete, groups delete+pin), `inspect_chat(bot, chat)`, `check_access(bot, chat)`, `missing_rights`, `apply_rights(chat, member)`, `chat_type_of`, `REQUIRED_CHANNEL/GROUP`. |
| `app/services/chatstate.py` | `mark_left(bot, session, ws_rec, chat)` (a conditional update: only an approved or pending chat becomes left, never a banned one; it closes its request notices), `mark_rights(bot, session, ws_rec, chat, missing)`, `rights_restored(...)`, `refresh(bot, session, ws_rec, chat) -> RefreshResult` (title, members, rights; gone → left), `rights_text(missing, lang)`, `kind_word(chat, lang)`. They log events, alert admins and DM partners. |
| `app/services/events.py` | `emit(bot, session, ws_rec, kind, chat=, actor_id=, data=, notify=, skip_user=, markup=)` stores an `Event` and alerts the owner + admins with 🔔 alerts on (defaults per kind: `ALERT_KINDS`); `describe(session, ev, lang, tz)` one entry for 📜 Actividad; `recent(session, bot_id, limit=, offset=, chat_pk=, kinds=)`. Data conventions: pause `{"by": "owner"|"admin", "until": iso|None}`, resume `{"by": "owner"|"admin"|"auto"}`, removed `{"by": "owner"|"admin"}`. |
| `app/services/freq.py` | Frequencies (dict in JSON): `normalize`, `next_slot(freq, tz, after)`, `upcoming(freq, tz, after, n)`, `per_day`, `refresh_bot(ws_rec, now)`, `refresh_group(group, tz, now)`, `refresh_post(post, tz, now)`, `in_dates(post, tz, now)`, `ended`, parsers `parse_every` / `parse_times` / `parse_window` / `parse_date` / `parse_datetime` (ValueError with an i18n key), `describe(freq, lang)`, `every_text`, `days_text`, `times_text`, `join_list`, `EVERY_CHOICES`, `MIN_EVERY`, `MAX_EVERY`. |
| `app/services/audience.py` | Targets tokens (`all`, `own`, `ext`, `g<id>`): `split_targets`, `make_targets`, `group_token`, `targets_chat`, `is_sendable`, `sendable_chats`, `bot_chats`, `bot_groups`, `memberships`, `chat_group_ids`, `group_chat_pks`, `group_counts`, `set_member(session, group_id, chat_pk, on)`, `join_open_groups`, `leave_all_groups`, `audience(session, post, sendable_only=)`, `audience_size`, `targets_size`, `source_of`, `chat_source`, `chats_of_source`, `source_counts`, `source_key`, `rotation_posts`, `rotation_pool`, `next_in_rotation`, `plan_slot`. |
| `app/services/content.py` | Post content: `from_message(message) -> Content | None`, `content_error(c)` (i18n key), `apply(post, content, bot_id)` (**bot_id = the bot that received the message**, `ctx.bot_id`), `default_name`, `kind_label`, `plain`, buttons `parse_buttons(text)` (ButtonsError key/line), `format_buttons`, `button_line`, `clean_rows`, `count_buttons`, `build_markup`, `make_button`, `COLORS`, `COLOR_EMOJI`, `MAX_BUTTONS`, `MAX_PER_ROW`; sending `media_for(bot, post, manager)` (MediaError too_big/unavailable), `deliver(bot, chat_id, post, media=, reply_markup=, silent=, protect=)`, `send_post(bot, chat_id, post, manager, sm)` (one-off: previews), `edit_delivery(bot, chat_id, message_id, post)`, `file_id_of`, `remember_media(sm, post_id, bot_id, file_id)`. |
| `app/services/limits.py` | Platform settings (KV `platform:settings`): `platform(session, settings) -> Platform(clone_policy, max_clones, limit_chats, limit_posts)`, `save_platform`; per bot `max_chats`, `max_posts`, `count_chats`, `count_posts`, `can_add_chat`, `can_add_post`, `unlimited`. |
| `app/services/stats.py` | `summary(session, bot_id, hours=24) -> Summary` (chats own/external/members/sendable/pending/owner_paused/admin_paused/no_rights, groups, posts, runs/sent/failed/skipped/reach, top_posts), `chat_received(session, chat_pk, days=7)`. |
| `app/services/brand.py` | 🖼 Platform images chosen by a super admin (KV `platform:photo:<name>` = `{"<bot id>": "<file id>"}`, file ids are per bot): `BOT` (profile photo of the main bots, given to the clones without a photo of their own) and `TZ` (photo of the 🗺 timezone picker, every bot). `photo_ids`, `has_photo`, `set_photo`, `clear_photo`, `photo_for(session, bot, name, manager)` (own file id or a downloaded upload) + `remember(..., source=source_of(photo))`, `fetch_one`, `fetch`, `set_profile_photo`, `set_main_photos`, `give_to_clone` / `give_to_clones` (background, `spawn`). |
| `app/services/blast.py` | `copy_to_users(bot, sm, from_chat_id, message_id, user_ids, on_progress=) -> BlastResult(sent, failed, blocked)` (background, low priority). |
| `app/services/kv.py` | `get`, `put`, `delete` JSON values. |
| `app/services/moderation.py` | `check_chat(session, title, username, description) -> word | None` (platform blocked words: abuse of minors, non consensual content). |
| `app/services/clones.py` | Shared clone helpers (owned by the clones module, which may extend it): `count_user_bots(session, user_id)`, `user_bots`, `main_username(session, settings)`, `clone_limit(session, settings, user_id)`, `connect_bot(manager, session, settings, token, owner_id, managed=, pending=)`, `status_key`, `can_manage_bots`, `suggest_username`, `newbot_url`, `notify_new_clone`, `REASON_OWNER/ADMIN/REMOVED`. |
| `tests/fake_tg.py`, `tests/conftest.py` | Fake Telegram server + `app` fixture (section 10). |

Roles: **super admin** (`SUPER_ADMIN_IDS`, owner rights in every bot + 👑 panel in the main bots), **owner**
(`bots.owner_id`), **admin** (`bot_users.role == "admin"`, promoted with `/admin @user`), **user** (partners and
visitors). Times: frequencies and dates are in the workspace timezone (`ctx.bot_tz`); dates are displayed with
`ctx.tz` using `fmt.dt()`.

---------------------------------------------------------------------------------------------------
## 3. Visual style (same as eButtons)

* Emojis at line start, `Label: value`, values bold when numeric (`👤 Miembros: <b>500</b>`).
* Toggles shown as ✅ / ✖️ in texts. On buttons the mark goes **first**, in place of the label's emoji
  (`toggle_label("📌 Fijar", True)` → `✅ Fijar`; `choice_label(label, selected)` → `✅ Label` / `⚪ Label`).
* Back button always last: `🔙 Regresar` (`back_row`). It goes to the **previous step**, never further. Multi-step
  flows (create wizard) show `[🔙 Regresar][❌ Cancelar]` (`prompt(..., back=cb)`).
* Group long menus in sections; each section lists its values with a short `   └ …` line under the non-obvious ones.
  **Explain what isn't obvious in the menu text itself**, in one short line.
* Pagination: `⬅️ Anterior` / `Siguiente ➡️` and `📄 Página 1 de 6` (`common.page`).
* Lists of chats: `1. 📣 <a href="link">Name</a> ✅` + new line `   └👤 1,234 · …` (📣 channel, 👥 group; link =
  `chat.public_link` when it has one).
* Button colors (Bot API 9.4 `style`): `primary` 🔵, `success` 🟢, `danger` 🔴. Use `success` for create/confirm
  buttons and `danger` for delete/reject/remove.
* Disabled buttons (Bot API 10.3, `btn(..., disabled=True)`) for "done" states (a decided request).
* Status icons of chats: ✅ recibe mensajes, ⏸ pausado, ⏳ pendiente, ⚠️ faltan permisos, 🚪 fuera (left),
  ❌ rechazado, 🚫 bloqueado. Origin: 🏠 propio, 🤝 externo. Posts: ▶️ activo, ⏸ pausado, ✅ terminado; modes
  🔁 rotación, ⏰ horario propio, 📆 una vez, ✋ manual.

---------------------------------------------------------------------------------------------------
## 4. How the distribution works (all modules must describe it the same way)

* **Sendable chat**: approved, the bot has its rights, not paused by an admin, not paused by its owner (a past
  `owner_paused_until` counts as not paused). The whole network can be paused (`Bot.paused`, "⏸ Pausar todo"):
  no run starts (🚀 Enviar ahora is refused with a hint), a run in progress stops before its next batch, and only
  the announced auto deletes still happen.
* **Targets of a post** (`Post.targets`): `all` (🌐 Todos), `own` (🏠 Solo propios), `ext` (🤝 Solo externos),
  `g<id>` (🗂 a group of chats). Several may be combined (union). An empty list targets nobody (show ⚠️).
* **Frequencies**: the global one (`Bot.freq`, 🌐; a new network starts with once a day at 12:00, `DEFAULT_FREQ`)
  and a group's own one (`ChatGroup.freq`, None = the chats follow the global one). A chat follows the frequency of the first of its groups (by `sort`, then id) that has its own
  frequency, otherwise the global one: that is its **source**. Every slot of a source, each sendable chat following
  it receives **one** post: the next of its **rotation** (the active rotation posts that target it, inside their
  campaign dates, in order of creation — or random when `Bot.rotation == "random"`; never the same twice in a row
  when there are more). `Chat.rot_last_post_id` remembers the last one. UI text: «Cada canal recibe un mensaje en
  cada turno de su frecuencia; los mensajes en rotación se van turnando.»
* **Schedule modes of a post** (`Post.mode`): 🔁 `rotation` (default, above), ⏰ `own` (its own frequency
  `Post.freq`: at each of its slots it goes to its whole audience, outside the rotation), 📢 `once` («Difusión
  puntual»: `Post.send_at`, right now or a date, then status `done`), ✋ `manual` (only with 🚀 Enviar ahora). Campaign dates (`starts_on`, `ends_on`, optional,
  bot timezone) limit rotation and own posts; after `ends_on` the post becomes `done`.
* **🛡 Anti-spam** (per bot, applies to every automatic run and to 🚀 Enviar ahora): at most `max_per_day` posts per
  chat per day (bot timezone), at least `min_gap` minutes between two posts in a chat, `one_at_a_time` (the previous
  post of the network in that chat is deleted before sending a new one). Chats left out are counted as skipped.
* **Options of a post**: 📌 `pin` (silently), 🔕 `silent`, 🛡 `protect` (no forwarding/saving), 🔗 `link_preview`
  (text posts), 🔼 `caption_above` and 🫣 `spoiler` (photo/video/GIF), 🗑 `delete_after` minutes (default
  `DEFAULT_DELETE_AFTER` = 0 = never; max 2880 = 48 h because Telegram doesn't let bots delete older messages), ♻️ `delete_previous` (its own previous copy
  in that chat is deleted when it is sent again). New posts take `Bot.post_defaults`.
* **Partners**: when the bot accepts external chats (`Bot.join_open`), anyone can add it to their channel or group.
  With `join_approval` the chat waits for an admin (`pending` + a request to the admins), otherwise it is approved
  at once. External chats join every 🤝 open group (`ChatGroup.open`) and can leave / join open groups from their
  panel.
* **The admins rule over the partners.** A partner can pause the distribution in their chat only when the admins
  allow it (`Bot.partners_can_pause`, default yes) and for at most `Bot.pause_max_hours` (0 = until they resume
  it, the default `DEFAULT_PAUSE_MAX_HOURS`; or 1, 3, 7 days): the pause menu only offers the allowed
  durations among 1 h, 6 h, 24 h, 3 días, 7 días and «hasta que la reanude» (a forged callback for another one is
  refused). The partner resumes their own pause whenever they want. Every change is an event that alerts the owner
  and admins (`events.emit`) and the admins **always** see every pause: the status line of the home, ⏸ Pausados (who
  paused, since, until), the chat list (⏸), 📜 Actividad. **Admins can resume a partner's pause at any time**
  (`chats.resume_by_admin` lifts both kinds of pause; the partner is told), while partners can't resume an admin's
  pause. A rule changed later applies to new pauses.

---------------------------------------------------------------------------------------------------
## 5. Screens and flows

Screen names (owner module in brackets): `home`, `guide`, `settings`, `notifications`, `admins`, `lang`,
`timezone`, `support`, `externals`, `stats`, `activity` [start]; `chats`, `chat`, `chat_groups`, `requests`,
`paused`, `partners_msg`, `join`, `my_chats`, `my_chat` [chats]; `posts`, `post`, `post_new`,
`post_content`, `post_buttons`, `post_targets`, `post_sched`, `post_opts`, `post_defaults` [posts]; `groups`,
`group`, `group_chats`, `freqs`, `freq_edit`, `antispam` [groups]; `clone`, `mybots`, `panel`, `panel_bots`,
`panel_bot`, `panel_settings`, `panel_blast` [clones].

`freq_edit` arg: `0` = global frequency, `+N` = group N, `-N` = post N (own frequency). Its back button returns to
`freqs`, `group` (arg N) or `post_sched` (arg N).

Deep links (`/start <payload>`, start module): `join` → `join`; `c<pk>` → `chat` (admins) or `my_chat` (partners);
`p<id>` → `post` (admins); `clone` → `clone`; anything else → `home`.

### 5.1 Home (start) — `home`
Admin view (admins of the network, and a super admin managing a clone):
```
🕸 <b>Tu red de distribución</b>

📣 Canales y grupos: <b>12</b> (👤 45,320)
   └ 🏠 8 propios · 🤝 4 externos
📝 Mensajes activos: <b>5</b>
⏰ Frecuencia global: cada 4 h · 08:00-23:00
📅 Próximo turno: <b>07/11/2026 11:00 AM</b>
⏸ Pausados por su dueño: <b>2</b>          (only when > 0)
⏳ Solicitudes pendientes: <b>1</b>        (only when > 0)
⚠️ Sin permisos: <b>1</b>                  (only when > 0)
⏸ <b>La distribución está pausada.</b> No se envía nada hasta que la reanudes.   (Bot.paused)
```
Buttons: `[📝 Mensajes][📣 Canales]`, `[🗂 Grupos de canales][⏰ Frecuencias]`, `[📊 Estadísticas][📜 Actividad]`,
`[⏳ Solicitudes (N)]` / `[⏸ Pausados (N)]` (only when > 0, screens `requests` / `paused`),
`[➕ Añadir canal ↗][➕ Añadir grupo ↗]` (urls for `ctx.ws_rec.username`), `[⏸ Pausar todo]` /
`[▶️ Reanudar todo]` (success) (`StCB` toggles `Bot.paused`, `events.emit(BOT_PAUSED/BOT_RESUMED)`),
`[⚙️ Ajustes][📖 Guía]`, main bot: `[🤖 Crear mi bot]` (screen `clone`) and `[🤖 Mis bots (N)]` (`mybots`, when
N > 0), super admin in a main bot: `[👑 Panel]`, and while managing a clone: `[🚪 Salir de @clone]` (danger;
clears `bu.ws_bot_id`, back to the main bot's home).
Partner / visitor view (role user):
* the bot accepts external chats (`join_open`): `Bot.join_text` (premium-free custom HTML, may be None) or the
  default «🤝 <b>Únete a la red de @bot</b>\n\nAñade este bot a tu canal o grupo y recibirá las publicaciones de la
  red.\n⏸ Puedes pausarlas cuando quieras desde 📣 Mis canales.» + `[➕ Añadir a mi canal ↗][➕ Añadir a mi grupo ↗]`;
* it doesn't: «🔒 Esta red es privada.»;
* `[📣 Mis canales (N)]` (screen `my_chats`) when the user has external chats in this bot (any status but left);
* `[📖 Guía][🛟 Soporte ↗]` (support url: `https://t.me/<Bot.support_username>` or the owner's @username, hidden
  when unknown), `[⚙️ Ajustes]`, and `[🤖 Crea tu propio bot]`: main bot → screen `clone`; clone → url
  `https://t.me/<main username>?start=clone` (hidden when the clone policy is `closed`).
Hub mode (`ctx.is_hub`): informational text (what eMesh is, you own your bot) + `[✨ Crear mi bot]` (`clone`),
`[🤖 Mis bots (N)]`, `[📖 Guía]`, `[⚙️ Ajustes]`, super admins `[👑 Panel]`. No network buttons.
Commands (start module): `/start`, `/cancel` (clear state + home), `/id`, `/help` (guide), `/admin @user`,
`/deladmin @user` (owner).

New clone: its owner gets the `timezone` screen (onboarding, no back button) on the first `/start` when
`bots.timezone_set` is False (port of eButtons `timezone.py` + `app/data/timezones.py`), then the **setup wizard**
(`setup`, below) while `bots.setup_done` is False, then home. Only the bot's owner in the bot itself gets them (not
a super admin managing it); main bots are marked done at startup.
Admin home extras: one status line always (when the network has chats): «📊 Estado: ✅ 10 reciben · ⏸ 2 pausados ·
⚠️ 1 sin permisos · ⏳ 1 pendiente» (from `stats.summary`), and `[⏸ Pausados (N)]` always shown to admins when the
network accepts external chats or has any (even with 0).

### 5.1b Setup wizard of a new bot (start module) — `setup` (arg = step)
Step by step, one question per screen, the current value pre-selected (✅), `[🔙 Regresar]` to the previous step
(the first one has `[⏭ Saltar el asistente]`: the defaults stay). Each answer is saved at once. Owner only.
1. «🤝 <b>¿Aceptas canales de otras personas?</b>» `[✅ Sí, con mi aprobación]`, `[⚡ Sí, entran
   solos]`, `[🔒 No, solo los míos]` → `join_open` / `join_approval`.
2. Only when they are accepted: «⏸ <b>¿Pueden pausar la distribución en sus canales?</b>» (└ «Tú siempre ves quién
   pausa y puedes reanudarlo.») `[Hasta 1 día]`, `[Hasta 3 días]`, `[Hasta 7 días]`, `[Sin límite]`,
   `[🚫 No pueden pausar]` → `partners_can_pause` / `pause_max_hours`.
3. «⏰ <b>¿Cada cuánto recibe un mensaje cada canal?</b>» `[1 al día (12:00)]` (the default), then
   `[Cada 2 h][Cada 4 h][Cada 6 h][Cada 12 h]` (from 08:00 to 22:00) → `Bot.freq` + `freq.refresh_bot`.
4. «🗑 <b>¿Cuánto tiempo siguen publicados los mensajes?</b>» `[1 h][6 h][12 h][1 día][2 días]`,
   `[♾ No se borran]` → `Bot.post_defaults["delete_after"]` (a new dict).
5. «✅ <b>Todo listo</b>» + a summary of the answers + `[➕ Añadir canal ↗][➕ Añadir grupo ↗]`,
   `[📝 Crear el primer mensaje]` (`post_new`), `[🏠 Ir al inicio]`. `setup_done` becomes True.
It can be run again from ⚙️ Ajustes › `[🧭 Asistente de configuración]` (owner).

### 5.2 Guide (start) — `guide` (arg = page)
Admins: 5 short pages (1 Cómo funciona: red, canales, mensajes, grupos de canales, frecuencias; 2 Canales propios y
externos, pausas; 3 Mensajes, botones con colores y opciones; 4 Frecuencias, rotación y anti-spam; 5 Clones, admins
y ajustes). Partners: 2 pages (cómo unirse y permisos; pausar, categorías y salir). Hub: 2 pages (qué es eMesh;
crear tu bot). Footer `📄 Página X de N`, `[⬅️ Anterior][Siguiente ➡️]`, `[🔙 Regresar]`.

### 5.3 Settings (start)
`settings` admin view:
```
⚙️ <b>Ajustes</b>
🗺 Zona horaria: Europe/Madrid (UTC+1)
🌍 Idioma: 🇪🇸 Español
👮 Admins: 2
🔔 Mis avisos: alertas ✅ · resumen diario ✅ · informe de cada envío ✖️
🤝 Canales externos: ✅ admitidos (con aprobación)
🛟 Soporte: @user
```
`[🗺 Zona horaria][🌍 Idioma]`, `[🔔 Mis avisos][👮 Admins]`, `[🤝 Canales externos]` (owner), `[🛟 Soporte]`
(owner), `[🔙]`. User view: `[🗺 Zona horaria][🌍 Idioma]`, `[🔔 Mis avisos]`, `[🔙]`. Bot level settings are
owner-only (admins see them read only).
* `notifications` («🔔 Mis avisos», per user `bot_users`): `[✅ Alertas de la red]` (`notify`: pauses, joins,
  removals, lost rights…; partners: their own chat notices are always sent), admins also `[✅ Resumen diario]`
  (`summary`) and `[✖️ Informe de cada envío]` (`run_reports`). One `└` hint per toggle.
* `externals` («🤝 Canales externos», owner): explanation line, `[✅ Admitir canales externos]` (`join_open`),
  `[✅ Aprobación manual]` (`join_approval`; └ "Las solicitudes llegan a los admins…" / "Entran solos…"),
  `[🔢 Mínimo de miembros: 500]` (input, 0 = none), `[💬 Texto de bienvenida]` (input HTML via `message.html_text`,
  max 1000 visible chars, `[↩️ Texto predeterminado]`), the invite deep link `https://t.me/<ws username>?start=join`
  shown in the text, `[🗂 Grupos abiertos]` (screen `groups`), `[✅ Los socios pueden pausar]` (`partners_can_pause`) and, when they
  can, `⏸ Pausa máxima` choices `[1 día][3 días][7 días][Sin límite]` (`pause_max_hours`, └ «Tú siempre puedes
  reanudar una pausa.»), `[🔙]` → `settings`.
* `admins`: as eButtons («👮 Administradores», `#1 ⚜️ @owner (id)`, `#2 🔰 @x (id)`, hint `/admin @usuario`),
  `[🗑 #2 @x]` per admin (owner). The user must have started the bot.
* `support` (owner): current contact + `[✏️ Cambiar contacto]` (`@user`, `t.me/user`) + `[↩️ Usar mi cuenta]`.
* `lang` (per user `bu.lang`), `timezone` (admins: the bot's, `Bot.timezone` + `timezone_set`, then
  `freq.refresh_bot` + refresh every group and own/once post; users: their own `bu.timezone`).

### 5.4 Statistics & activity (start)
`stats` (arg 0 = 24 h, 1 = 7 días, 2 = 30 días; admins), from `stats.summary`:
```
📊 <b>Estadísticas</b> · últimas 24 h
📤 Envíos: <b>12</b>
✅ Entregados: <b>340</b>
❌ Fallidos: <b>3</b>
🛡 Omitidos por anti-spam: <b>5</b>
👁 Alcance: <b>1,234,567</b>
   └ Miembros de los chats que recibieron los mensajes.

📣 Chats: 12 (🏠 8 · 🤝 4) · 👤 45,320
⏸ Pausados: 2 · ⚠️ Sin permisos: 1 · ⏳ Pendientes: 1

🏆 <b>Mensajes más enviados</b>
1. Promo Cine — 120
```
`[24 h][7 días][30 días]` (choice), `[📜 Actividad]`, `[🔙]` → home.
`activity` (arg page, admins): `events.recent` 10 per page, each `events.describe`; nav; `[🔙]` → home.

### 5.5 Posts (posts module)
Long lists never pass Telegram's limits: target and group names are summarised («Cine, Series +3», at most 2 names
per row in lists and 10 in a detail, each cut to 30 characters) and the target picker shows at most 60 groups of
chats (the chosen ones first).
`posts` (arg page): «📝 <b>Mensajes</b>» + one line «🔁 rotación · ⏰ horario propio · 📆 una vez · ✋ manual», then
per post `1. ▶️ 🔁 <b>Promo Cine</b> · 🖼` + `   └🎯 Todos · 📤 12 envíos` (or `📅 next send`). Active and paused
first, done last. Buttons: one per post (`#1 Promo Cine`, 2 per row), `[➕ Nuevo mensaje]` (success),
`[⚙️ Opciones por defecto]` (`post_defaults`), nav, `[🔙]` → home. Limit: `limits.can_add_post` (alert when full).

`post_new` — wizard (FSM, create the row only at the end; `[🔙 Regresar][❌ Cancelar]` from step 2):
1. «📝 <b>Nuevo mensaje</b> · 1/4\n\nEnvía el mensaje tal como quieres que se publique: texto, foto, vídeo, GIF,
   archivo, audio o nota de voz, con su formato (<b>negrita</b>, <i>cursiva</i>, enlaces, emojis). También puedes
   reenviarlo desde un canal.» `content.from_message` + `content_error`.
2. «🔘 <b>Botones</b> · 2/4» with the syntax (`Nombre - https://enlace`, `&&` same row, color at the end
   🔵 🟢 🔴, `Código - copiar: PROMO10`) + `[⏭ Sin botones]`. `content.parse_buttons` (error → show it and ask again).
3. «🎯 <b>¿A quién se envía?</b> · 3/4»: toggles `[🌐 Todos]` (selected by default), `[🏠 Solo propios]`,
   `[🤝 Solo externos]`, one per group of chats `[🗂 Cine (5)]`, live count «👥 Lo recibirán: 23 chats · 👤 45,320»
   (`audience.targets_size`), `[✅ Continuar]` (needs a target).
4. «⏰ <b>¿Cuándo se envía?</b> · 4/5»: `[🔁 En rotación]` (└ «Se turna con los demás mensajes según
   la frecuencia de cada canal (global: 1 al día a las 12:00).»), `[⏰ Con su propio horario]`,
   `[📢 Difusión puntual]` (still step 4: `[🚀 Ahora mismo]` — created with `send_at` = now, the scheduler sends it
   once at once — or a typed date: `freq.parse_datetime`), `[✋ Solo cuando lo envíe yo]`.
5. «🗑 <b>¿Cuánto tiempo sigue publicado?</b> · 5/5» (└ «Pasado ese tiempo se borra solo de los canales.»):
   `[1 h][3 h][6 h][12 h][1 día][2 días]`, `[♾ No borrar]`, the default of the network pre-selected
   (`Bot.post_defaults["delete_after"]`, else `DEFAULT_DELETE_AFTER`: no borrar). Steps 1-3 say «· 1/5» … «· 3/5».
Then: create the `Post` (`apply` content with `ctx.bot_id`, `name = default_name`, `ws.post_defaults`, `targets`,
`mode`; own mode starts with a copy of the global frequency), `freq.refresh_post`, `scheduler.wake()`, show «✅
Mensaje guardado» + the `post` detail; own mode opens `freq_edit` (arg -id) right away.

`post` (arg id):
```
📝 <b>Promo Cine</b>
📌 Estado: ▶️ Activo
🧩 Tipo: 🖼 Foto · 🔘 3 botones
🎯 Destino: 🌐 Todos → 23 chats (👤 45,320)
⏰ Envío: 🔁 En rotación
   └ Cada canal lo recibe por turnos según su frecuencia.
📅 Próximo envío: <b>07/11/2026 08:00 PM</b>          (own / once)
📆 Campaña: del 01/11/2026 al 30/11/2026              (when set)
📤 Enviado: 12 veces · 340 entregas · último 07/11/2026 10:00 AM
🟢 Publicado ahora en: 23 chats                       (publisher.live_count)
<blockquote expandable>⚙️ Opciones
📌 Fijar: ✖️ …</blockquote>
```
`[👁 Vista previa][🚀 Enviar ahora]`, `[✏️ Contenido][🔘 Botones]`, `[🎯 Destino][⏰ Programación]`,
`[⚙️ Opciones][🧬 Duplicar]`, live > 0: `[🔄 Actualizar publicados (23)][🔚 Retirar (23)]`,
`[⏸ Pausar | ▶️ Activar][🗑 Eliminar]`, `[🔙]` → `posts`.
* 👁 Vista previa: `content.send_post(event.bot, ctx.user_id, post, manager, sm)` (the real buttons; MediaError →
  alert), then the `post` panel again below it (`show(..., new=True)`).
* 🚀 Enviar ahora: confirm «🚀 Se enviará ahora a <b>23</b> chats (👤 45,320).» `[✅ Enviar][❌ No]` →
  `publisher.send_now(post_id, user_id=)` → toast «🚀 Enviando…». Busy (`publisher.is_busy`) or no audience → alert.
* 🔚 Retirar (confirm) → background `publisher.retire(post_id)`; 🔄 Actualizar publicados (confirm) → background
  `publisher.update_live(post_id)`: the text and buttons of the copies already sent are updated (not the media).
* 🧬 Duplicar: a copy named «X (copia)», **paused** (so nothing is sent before it is reviewed) → its detail.
* 🗑 Eliminar: confirm with `[🗑 Eliminar y retirar lo publicado (N)]` (background retire, then delete the row) and
  `[🗑 Eliminar solo el mensaje]` (the copies already sent stay and their auto delete still happens), `[❌ No]`.
* ⏸/▶️: status paused/active (a `done` post can be re-activated: once → asks a new date) + `freq.refresh_post`.
`post_content` (arg id): `[✏️ Cambiar el mensaje]` (new text + media), `[📝 Cambiar solo el texto]` (keeps the media;
caption limit), `[🏷 Nombre interno]` (≤ 64), `[🖼 Quitar multimedia]` (media posts, becomes text; needs text), `[🔙]`.
After a change of a post with live copies: hint «🔄 Pulsa Actualizar publicados para aplicarlo a los ya enviados.».
`post_buttons` (arg id, `post_buttons.py`): the current keyboard drawn with the real colors where every button is a
callback that opens its editor (`PbCB`), then `[➕ Añadir botón]`, `[✍️ Escribirlos todos][🗑 Quitar todos]`,
`[👁 Vista previa]`, `[🔙]` → `post`. «➕ Añadir botón»: name → link (`https://`, `t.me/`, `@user`, or
`copiar: TEXTO`) → color `[⬜ Normal][🔵 Azul][🟢 Verde][🔴 Rojo]` → place `[⬇️ En una fila nueva][➡️ Al lado del
último]`. Button editor: name, link, color (choice), `[⬅️][➡️]` move inside the row, `[⬆️][⬇️]` move row,
`[🗑 Quitar botón]`, `[🔙]`. «✍️ Escribirlos todos»: current buttons in a `<pre>` (`format_buttons`) + syntax help;
the input replaces them. Max `content.MAX_BUTTONS`, `MAX_PER_ROW`.
`post_targets` (arg id): same toggles and count as wizard step 3, saved at once; at least one target; `[🔙]`.
`post_sched` (arg id): mode choice rows with a `└` line each; `[⏰ Horario propio: cada 3 h]` → `freq_edit` arg -id;
`[📆 Fecha: 07/11 20:00]` → date input; campaign `[📆 Desde: —][📆 Hasta: —]` (input `dd/mm/aaaa`, `0` clears);
`[🔙]` → `post`. Every change → `freq.refresh_post` + `scheduler.wake()`.
`post_opts` (arg id): toggles `📌 Fijar`, `🔕 Sin sonido`, `🛡 Proteger contenido`, `🔗 Vista previa de enlaces`
(text), `🔼 Texto encima del multimedia` and `🫣 Spoiler` (photo/video/GIF), `♻️ Borrar su envío anterior`; auto delete
choice `[Nunca][1 h][3 h][6 h][12 h][1 día][2 días]` + `[✏️ Otro]` (input, 15 min - 48 h, `freq.parse_every`-like).
`post_defaults` (arg 0): the same options as defaults of new posts (`Bot.post_defaults`), `[🔙]` → `posts`.

### 5.6 Chats, requests and partners (chats module)
`chats` (arg page; filter with `ChCB`: all / 🏠 / 🤝 / ⏸ / ⚠️):
```
📣 <b>Canales y grupos</b> 👥
📣 Canales: 10 · 👥 Grupos: 2 · 👤 45,320
🏠 Propios: 8 · 🤝 Externos: 4

1. 📣 <a href="https://t.me/x">Cine HD</a> ✅
   └👤 12,000 · 🏠 · 🗂 Cine
2. 👥 Grupo Series ⏸
   └👤 800 · 🤝 @pepe · hasta 08/11/2026 10:00 AM
```
10 per page, one button per chat (`#1 📣 Cine HD`, 2 per row), filter row, `[➕ Añadir canal ↗][➕ Añadir grupo ↗]`,
`[📢 Avisar a los dueños]` (when there are partners), `[⏳ Solicitudes (N)]` (when > 0), nav,
`[🔙]` → home. Left, rejected and banned chats are not listed (pending ones are, with ⏳).
`chat` (arg pk):
```
📣 <b>Cine HD</b>
🆔 <code>-100123</code>
🔗 https://t.me/cinehd
👤 Miembros: <b>12,000</b>
🏷 Origen: 🏠 Propio | 🤝 Externo · @pepe
📌 Estado: ✅ Recibe mensajes | ⏸ Pausado por su dueño hasta 08/11/2026 10:00 AM | ⏸ Pausado por un admin |
           ⏳ Pendiente de aprobación | ⚠️ Faltan permisos: publicar mensajes
🗂 Grupos de canales: Cine, Estrenos
⏰ Frecuencia: cada 2 h (🗂 Cine) | 🌐 la global (cada 4 h)
📨 Recibidos: 120 · últimos 7 días: 14
🕐 Último: 07/11/2026 10:00 AM
```
`[🗂 Grupos de canales]` (`chat_groups`: toggles per group), `[🔄 Comprobar]` (`chatstate.refresh` + a summary),
`[⏸ Pausar | ▶️ Reanudar]` (admin pause), pending: `[✅ Aceptar][❌ Rechazar]`, `[🗑 Quitar de la red]` (confirm:
`publisher.drop_chat` first, then the bot leaves, status `left`, event `chat_removed` by admin, DM to a partner),
`[🚫 Bloquear]` (confirm: like remove, status `banned`: adding the bot again is refused), `[↗️ Abrir]` (when it
has a link), `[🔙]` → `chats`.
Bot added / promoted / removed (`my_chat_member`, `chat_events.py`), channels & groups:
1. Hub main bot (`ctx.is_hub`): leave and DM «ℹ️ Este bot no distribuye mensajes. Crea tu propio bot con 🤖 Crear
   mi bot.».
2. Who added it (`from_user`): an admin of the bot (`ctx.is_admin`) → origin `own`; anyone else → `ext`
   (refused when `join_open` is off: leave + DM «🔒 Este bot no admite canales de otras personas.» + a
   «🤖 Crea tu propio bot» button when clones can be created).
3. Upsert `Chat` (ws id, chat id); re-adding a `banned` chat → leave again (no DM spam: one short DM). A chat that
   comes back after `left`/`rejected` keeps its groups and origin; `owner_user_id` = who added it.
4. Rights (`chatinfo.apply_rights`), members (`getChatMemberCount`), limit (`limits.can_add_chat`, else leave +
   DM), external: `min_members` (reject + leave + DM «ℹ️ Tu canal necesita al menos 500 miembros…»),
   platform words (`moderation.check_chat` → reject + leave, no word shown).
5. Missing rights → status `pending` + DM with what is missing and `[🔄 Comprobar de nuevo]`; when a later update
   (or the button) shows the rights, continue with 6.
6. Own → `approved` + DM to the admin «✅ <b>Cine HD</b> añadido a la red. Recibirá los mensajes para 🌐 Todos y
   🏠 Propios.» + `[🗂 Añadir a grupos de canales]` (`chat_groups`) + event `chat_added` (alerts the other admins).
   External without approval → `approved`, `audience.join_open_groups`, DM to the partner (welcome: what will happen,
   how to pause: `[📣 Mis canales]`), event `chat_joined` (alert). External with approval → `pending`, DM «📨 Solicitud
   enviada…», event `chat_request` (no alert) and request notices to the admins (`RequestNotice`):
   ```
   📨 <b>Solicitud para unirse a la red</b>
   👤 @pepe
   📣 <b>Cine HD</b> · 👤 12,000
   🆔 <code>-100123</code> · 🔗 https://t.me/cinehd
   ```
   `[✅ Aceptar (success)][❌ Rechazar (danger)]`; deciding edits every notice to a disabled button
   `✅ Aceptada · @admin` / `❌ Rechazada · @admin`. Rejecting asks a reason (prompt with `[Sin motivo]`), DMs the
   partner and the bot leaves. Accepting: `approved`, open groups, DM, event `chat_joined` (alert others).
7. Bot removed (`left`/`kicked`) → `chatstate.mark_left`. Rights reduced → `chatstate.mark_rights`; rights back →
   `chatstate.rights_restored` (and a pending chat continues with 6).
Also in `chat_events.py`: `migrate_to_chat_id` (group → supergroup) updates the chat id; the "pinned message"
service message the bot's own pin creates is deleted (groups: `from_user` is the bot; channels: the pinned message
is one of the bot's live deliveries); **discovery**: a `channel_post` or group `message` from a chat with no row →
`services.chats.register_existing` (at most once per hour per chat, in memory), so a bot that was already admin in
chats (connected with a token) finds them.
`requests` (arg page): pending chats with `[✅][❌]` per row. `paused` (arg page): **every** paused chat, by its
owner or by an admin: name, who paused it, since, until, and `[▶️ #n]` per row to resume it (`resume_by_admin`).
In `chat`, a chat paused by its partner shows `[▶️ Reanudar (anula la pausa del socio)]` (confirm: «El dueño lo ha
pausado hasta …. Se le avisará.»). There is no import screen: chats join when the bot is added to them, or by
discovery (above). `partners_msg` («📢 Avisar a los dueños»):
prompt the message → confirm «Se enviará a <b>N</b> personas.» → background `blast.copy_to_users` → report DM.
Partners (`partners.py`):
* `join` (also `/start join`): how to join (the add buttons, the rights it needs and why, that they can pause
  anytime) or «🔒 Esta red es privada.».
* `my_chats` (arg page): the user's external chats in this network (not left) with status.
* `my_chat` (arg pk, only the partner who owns it — or admins):
  ```
  📣 <b>Cine HD</b>
  📌 Estado: ✅ Recibe los mensajes de la red | ⏸ Pausado hasta 08/11/2026 10:00 AM | ⏸ Pausado por la
             administración | ⏳ Pendiente de aprobación | ⚠️ Faltan permisos: …
  📨 Recibidos: 120 · últimos 7 días: 14
  🕐 Último: 07/11/2026 10:00 AM
  🗂 Categorías: Cine, Series        (open groups it is in)
  ```
  `[⏸ Pausar]` → the allowed durations among `[⏸ 1 h][⏸ 6 h][⏸ 24 h]`, `[⏸ 3 días][⏸ 7 días]`,
  `[⏸ Hasta que la reanude]` (section 4: the admins' rules), `[🔙]`; no pause button when partners can't pause
  («⏸ La administración no permite pausar en esta red.»);
  `[▶️ Reanudar]` (own pause only); `[🗂 Categorías]` (open groups: join / leave); `[🚪 Salir de la red]`
  (confirm: `publisher.drop_chat`, the bot leaves, status `left`, event `chat_removed` by owner); `[🔙]` → `my_chats`.
  Pausing: `owner_paused=True`, `owner_paused_until`, `paused_at`, event `chat_paused` (by owner, until) →
  the admins are alerted; toast «⏸ Pausado. Se ha avisado a la administración.». Resuming: event `chat_resumed`
  (by owner). The scheduler ends expired pauses by itself (event by `auto`).

### 5.7 Groups of chats & frequencies (groups module)
`groups` (arg page): «🗂 <b>Grupos de canales</b>\nAgrupa canales y grupos para enviarles mensajes concretos y darles
su propia frecuencia.» + `1. 🗂 <b>Cine</b> · 📣 5 · ⏰ cada 2 h · 🤝` per group; one button per group,
`[➕ Nuevo grupo de canales]` (name prompt ≤ 64, then `group_chats`; at most 50 groups of chats per network), `[🔙]`
→ home.
`group` (arg id):
```
🗂 <b>Cine</b>
📣 Chats: <b>5</b> (👤 23,000)
⏰ Frecuencia: cada 2 h · 08:00-23:00 (propia) | 🌐 la global (cada 4 h)
📅 Próximo turno: 07/11/2026 12:00 PM
📝 Mensajes que lo usan: 3
🤝 Abierto a externos: ✅
   └ Los canales externos pueden unirse o salir desde su panel, y los nuevos entran solos.
```
`[📣 Elegir chats]` (`group_chats`), `[⏰ Frecuencia]` (`freq_edit` +id), `[🤝 Abierto a externos]` (toggle),
`[✏️ Nombre]`, `[🗑 Eliminar]` (confirm: the posts that targeted it lose that target; a post left with no target is
named in the confirmation), `[🔙]` → `groups`.
`group_chats` (arg id): the network's chats (approved and pending) with `✅`/`⚪` toggles, 10 per page,
`[✅ Todos][✖️ Ninguno]`, `[🔙]` → `group`.
`freqs` («⏰ Frecuencias», the place to manage every frequency at once):
```
⏰ <b>Frecuencias</b>
Cada canal recibe un mensaje en cada turno de su frecuencia; los mensajes en rotación se van turnando.

🌐 <b>Global</b>: cada 4 h · 08:00-23:00
   └ 9 chats · ≈ 6 al día · próximo: 11:00
🗂 <b>Cine</b>: cada 2 h
   └ 5 chats · ≈ 8 al día · próximo: 12:00
🗂 <b>Noticias</b>: 🌐 la global
⏰ Mensajes con su propio horario: 2

🔀 Orden de la rotación: en orden
🛡 Anti-spam: máx. 6 al día · 30 min entre mensajes · 🧹 uno a la vez ✖️
```
`[🌐 Global: cada 4 h]` (`freq_edit` 0), one button per group `[🗂 Cine: cada 2 h]`, `[🔀 En orden | Al azar]`
(toggle `Bot.rotation`), `[🛡 Anti-spam]`, `[🔙]` → home.
`freq_edit` (arg 0 / +group / -post):
```
⏰ <b>Frecuencia</b> · 🌐 Global | 🗂 Cine | 📝 Promo Cine
🔁 Cada: <b>3 h</b> | 🕐 A las: <b>10:00, 14:00 y 22:00</b>
🕐 Horario: 08:00-23:00 | todo el día                (interval mode)
🔄 Días: todos los días
📅 Próximos: 07/11 11:00 AM, 02:00 PM, 05:00 PM
≈ 6 envíos al día por chat
```
Group: `[✅ 🌐 Usar la global]` choice first (on → `freq = None`, the rest hidden). Mode choice
`[⏱ Cada cierto tiempo][🕐 A horas fijas]`; interval: quick choices `freq.EVERY_CHOICES`
(`[30 min][1 h][2 h]…[24 h]`, 3 per row) + `[✏️ Otro intervalo]` + `[🕐 Horario activo]` (input, `0` = all day);
times: `[✏️ Escribir las horas]`; days: `[L][M][X][J][V][S][D]` toggles + `[Todos][L-V][S-D]`; `[🔙]`. Every change:
`normalize`, store (new dict), `freq.refresh_bot/group/post`, `scheduler.wake()`.
`antispam`: three settings with a `└` line each: `📊 Máximo al día por chat` (choice `[Sin límite][2][4][6][8][12]`
+ `✏️`), `⏱ Separación mínima` (`[Ninguna][15 min][30 min][1 h][2 h]` + `✏️`), `[🧹 Uno a la vez]` toggle;
`[🔙]` → `freqs`.

### 5.8 Clones and 👑 panel (clones module)
`clone` (main bot): what a clone is (your own bot with its own network, managed from Telegram) + `[✨ Crear bot ↗]`
(managed bot link when `can_manage_bots`) + `[🔑 Usar token]` (paste a @BotFather token, deleted from the chat at
once) + `[🤖 Mis bots (N)]` + `[🔙]`. Policy (`limits.platform`): `closed` → «🔒 Ahora mismo no se pueden crear bots
nuevos.» (super admins can); `approval` → «⏳ Tu bot quedará pendiente hasta que la administración lo apruebe.»
(`connect_bot(pending=True)`, super admins get `[✅ Aprobar][❌ Rechazar]`); limit `clone_limit`. In a clone,
`clone` points to the main bot (`https://t.me/<main>?start=clone`).
Managed bot update (`managed_bot`, main bot): `getManagedBotToken` → `connect_bot(managed=True, pending=…)` → DM
`✅ ¡Tu bot @x está listo! Ábrelo y pulsa /start.` (or pending notice); `notify_new_clone` to super admins.
`mybots`: status (✅ activo / ⏳ pendiente / ⏸ pausado / 🔒 desactivado por la administración / ❌ token no válido),
`[⏸ / ▶️][🗑 Desconectar]` per bot (`manager.disable_bot(reason=REASON_OWNER / REASON_REMOVED)`).
`manager.on_bot_invalid`: DM the owner through the main bot (register the callback once).
`panel` (super admins, main bots):
```
👑 <b>Panel de la plataforma</b>
🤖 Bots: 15 (✅ 12 · ⏸ 2 · ⏳ 1 · ❌ 0)
👥 Usuarios: 1,234
📣 Chats: 345 (👤 5,600,000) · ⏸ pausados por su dueño: 7
📝 Mensajes activos: 89
📤 Últimas 24 h: 230 envíos · 12,345 entregas
⚙️ Clonación: 🌐 abierta | ⏳ con aprobación | 🔒 cerrada
```
`[🤖 Clones]` (`panel_bots`), `[⏳ Pendientes (N)]`, `[⚙️ Plataforma]` (`panel_settings`), `[📢 Aviso a los dueños]`
(`panel_blast`: copy a message to the owners of clones through the main bot, `blast.copy_to_users`),
`[📄 Errores]` (logbook as a .txt document), `[🔙]`.
`panel_bots` (arg page; filter all/active/paused/pending/invalid; `[🔎 Buscar]` by @username or id):
`1. ✅ @clon_bot · 👤 @owner\n   └📣 12 · 📝 5 · ⏸ 2`. `panel_bot` (arg bot id):
```
🤖 <b>@clon_bot</b> (Nombre)
👤 Dueño: @owner (id)
📌 Estado: ✅ Activo
📅 Creado: 01/11/2026
📣 Chats: 12 (🏠 8 · 🤝 4) · 👤 45,320
⏸ Pausados por su dueño: 2 · ⏳ Pendientes: 1
📝 Mensajes activos: 5 · ⏰ cada 4 h
📤 Últimas 24 h: 12 envíos · 340 entregas · 3 fallos
🔒 Límites: 50 chats · 20 mensajes | sin límites
```
`[🛠 Gestionar]` (sets `bu.ws_bot_id` of the super admin in this main bot, opens `home`: the clone's network inside
the main bot, with the banner), `[⏸ Desactivar | ▶️ Activar]` (`disable_bot(reason=REASON_ADMIN)` /
`enable_bot`), pending: `[✅ Aprobar][❌ Rechazar]` (approve = `enable_bot` + DM owner; reject = status disabled
`REASON_ADMIN` + DM), `[🔒 Límites]` (input «chats mensajes», e.g. `50 20`, `0` = sin límite, `-` = the platform
default), `[💬 Escribir al dueño]` (prompt → DM via the main bot), `[📜 Actividad]` (its `events.recent`),
`[🗑 Eliminar]` (danger, confirm twice: `disable_bot(withdraw)` then delete the row and its data), `[🔙]`.
`panel_settings`: clone policy choice `[🌐 Abierta][⏳ Con aprobación][🔒 Cerrada]`, `[🤖 Bots por usuario: 3]`,
`[📣 Chats por clon: sin límite]`, `[📝 Mensajes por clon: sin límite]` (inputs, 0 = unlimited) → `limits.save_platform`.

---------------------------------------------------------------------------------------------------
## 6. Engine (engine module): `app/services/publisher.py`, `app/services/scheduler.py`

* **Publisher.run(post_id, chat_pks, kind, source, triggered_by, wait)**: creates a `Run` (post name copy, total)
  and its `Delivery` rows (queued), commits, then sends in a background task (or awaits it when `wait=True`, used by
  tests and the scheduler when it wants). Per bot and post only one run at a time (`is_busy`). Steps per chat, with
  `SEND_CONCURRENCY` chats at a time and short transactions (commit in batches):
  1. Anti-spam (computed in bulk before sending): `max_per_day` (deliveries sent today in the chat, bot timezone),
     `min_gap` (minutes since the chat's last delivery) → `skipped`.
  2. `one_at_a_time` → delete the chat's live deliveries (any post) first; else `delete_previous` → delete this
     post's previous live delivery in that chat.
  3. Send with `content.deliver` (media from `content.media_for` once per run; a file uploaded to a new bot is
     remembered with `content.remember_media` and its file id reused for the next chats).
  4. Success: `sent`, `message_id`, `sent_at`, `delete_at = sent_at + delete_after` (None when 0); pin when
     `post.pin` (silently; `pinned=True`); chat `posts_total += 1`, `last_post_at`; rotation runs also set
     `chat.rot_last_post_id = post.id`.
  5. Errors: chat gone (`is_chat_gone`, confirmed with `getChatMember` like eButtons: a 403 is final) →
     `chatstate.mark_left`; rights (`is_rights_error`, `is_topic_error`) → `chatstate.mark_rights`; migrated →
     update `chat_id` and retry once; `is_outcome_unknown` → `unknown` (never sent twice); `MediaError` → the whole
     run fails with that reason (admins told); `is_button_error` → send without buttons and note it; anything else →
     `failed` + `error` (`short(exc)`). Temporary errors never expel a chat.
  6. Finish: run `done`, counters (`sent`, `failed`, `skipped`, `reach` = members of the chats it reached),
     `post.runs_count += 1`, `post.sent_count += sent`, `post.last_sent_at`; a `once` post becomes `done`. Admins with
     `run_reports` get «📤 <b>Promo Cine</b> enviado a 23/25 chats (2 fallos · 1 omitido por anti-spam).».
* `send_now(post_id, user_id=)`: a `manual` run to `audience.audience(post)` (None when busy or nobody).
* `retire(post_id)` deletes every live delivery of the post now (`deleted`; already gone → `missing`; older than
  48 h → `expired`) and returns how many were deleted. `drop_chat(chat_pk)` does the same for one chat (before the bot
  leaves it). `update_live(post_id)` edits the live deliveries (< 48 h) with `content.edit_delivery` → (edited,
  failed); "not modified" counts as edited. `withdraw_bot(bot_id, timeout)`: deletes the bot's live deliveries that
  have a pending auto delete, within `timeout`. `resume()` / `resume_bot(bot_id)`: runs left `sending` by a restart
  continue with their queued deliveries (`sending` ones become `unknown`).
* `delete_due()`: live deliveries whose `delete_at` passed → `deleteMessage` (gone → `missing`, 48 h → `expired`).
* `live_count(session, post_id)` (module function): live deliveries of a post (sent, not deleted, < 48 h).
* **Scheduler** (`start/stop/wake/tick`, tick every `SCHEDULER_TICK_SECONDS`, each bot in its own task so one slow
  bot never delays the others, `bot_scope(bot_id)`, low priority): for every running bot that runs a network (not a
  hub main bot) and isn't `paused`:
  1. Global slot due (`rot_next_at <= now`): if more than `LATE_SKIP_MINUTES` late, skip it; else
     `audience.plan_slot(source=None)` → one `run(kind=rotation, source="global")` per post. Then
     `freq.refresh_bot`. A missing `rot_next_at` is just computed.
  2. The same for every group with its own frequency (`source="g<id>"`, `freq.refresh_group`).
  3. Own / once posts with `next_send_at <= now` (late → skip and refresh) → `run(kind=schedule|once)` to
     `audience.audience(post)`; then `freq.refresh_post` (once → `done` after its run). Posts past `ends_on` → `done`.
  4. `publisher.delete_due()` (also for paused bots: announced deletions always happen).
  5. Owner pauses that expired → clear them, `events.emit(CHAT_RESUMED, data={"by": "auto"})` and DM the partner
     «▶️ La pausa de tu canal X ha terminado: vuelve a recibir los mensajes de la red.».
  6. Every `MAINTENANCE_INTERVAL_HOURS` (KV `maint:<bot_id>`): `chatstate.refresh` of every approved and pending
     chat (a pending chat that got its rights is not approved here: the chats module does it on the next update or
     button).
  7. Once a day after `SUMMARY_HOUR` (bot timezone, KV `summary:<bot_id>:<date>`): the daily summary to the admins
     with `summary` on (yesterday's runs / deliveries / failures / reach, paused, pending, without rights).
  8. Once a day: delete runs (and deliveries) and events older than `RETENTION_DAYS` (deliveries waiting for their
     auto delete are kept).
  Survives restarts: everything is in the database.

---------------------------------------------------------------------------------------------------
## 7. Interfaces between modules (signatures are fixed)
* engine → `Publisher(manager, sm, settings)`: `resume()`, `resume_bot(bot_id)`, `withdraw_bot(bot_id, *, timeout)`,
  `is_busy(post_id) -> bool`, `send_now(post_id, *, user_id=None) -> int | None` (run id),
  `run(post_id, chat_pks, *, kind, source="", triggered_by=None, wait=False) -> int | None`,
  `retire(post_id) -> int`, `update_live(post_id) -> tuple[int, int]`, `drop_chat(chat_pk) -> int`,
  `delete_due() -> int`; module function `live_count(session, post_id) -> int`.
  `Scheduler(manager, sm, settings, publisher)`: `start()`, `stop()`, `wake()`, `tick()`.
* chats → `app/services/chats.py`: `approve(bot, session, ws_rec, chat, by_user, *, notify=True)`,
  `reject(bot, session, ws_rec, chat, by_user, reason, *, leave=True)`,
  `remove(bot, session, ws_rec, chat, by_user, *, publisher, ban=False, by_owner=False)`,
  `register_existing(bot, session, ws_rec, ref, *, added_by=None) -> str` (`added` | `existing` | `not_admin` |
  `not_found` | `pending` | `limit`), `pause_by_owner(bot, session, ws_rec, chat, user_id, until)`,
  `resume_by_owner(...)`, `pause_by_admin(bot, session, ws_rec, chat, user_id)`, `resume_by_admin(...)` (lifts an
  admin's pause and a partner's pause: the admins rule; DMs the partner when it lifted theirs).
* Screens are the interface between UI modules (section 5): link to them by name with the documented args.

---------------------------------------------------------------------------------------------------
## 8. i18n
Files `app/i18n/locales/es_<module>.py` and `en_<module>.py` (`STRINGS = {...}`), keys prefixed with your module
prefixes. Spanish (Spain) is the reference; English must have the same keys and the same `{placeholders}` (a test
enforces it). Literal braces: `{{` `}}`. A duplicated key anywhere raises at startup.

---------------------------------------------------------------------------------------------------
## 9. Ownership (who edits what)
| Module | Files | Callback prefixes | i18n prefixes |
|---|---|---|---|
| engine | `app/services/publisher.py`, `scheduler.py`, tests `tests/test_engine*.py` | — | `eng.` |
| posts | `app/bot/routers/posts.py`, `post_buttons.py`, tests `tests/test_posts*.py` | `po`, `pw`, `pb` | `po.`, `pb.` |
| chats | `app/bot/routers/chat_events.py`, `requests.py`, `chats.py`, `partners.py`, `app/services/chats.py`, tests `tests/test_chats*.py`, `tests/test_partners*.py` | `ch`, `rq`, `pa` | `ch.`, `rq.`, `pa.`, `ce.` |
| groups | `app/bot/routers/groups.py`, `freqs.py`, tests `tests/test_groups*.py`, `tests/test_freqs*.py` | `gr`, `fq` | `gr.`, `fq.` |
| start | `app/bot/routers/start.py`, `settings.py`, `timezone.py`, `stats.py`, `setup.py`, `app/data/timezones.py`, tests `tests/test_start*.py`, `tests/test_settings*.py`, `tests/test_stats*.py`, `tests/test_setup*.py` | `st`, `ss`, `tz`, `lg`, `ad`, `sx`, `su` | `home.`, `guide.`, `set.`, `tz.`, `lang.`, `adm.`, `stats.`, `setup.` |
| clones | `app/bot/routers/clone.py`, `panel.py`, `app/services/clones.py`, tests `tests/test_clone*.py`, `tests/test_panel*.py` | `cl`, `sa` | `cl.`, `sa.` |
Everyone: `app/i18n/locales/{es,en}_<module>.py` for their module name. Core files (section 2) belong to the
integrator: report needed changes.

---------------------------------------------------------------------------------------------------
## 10. Testing
`tests/fake_tg.py` is a fake Bot API server; `tests/conftest.py` gives the `app` fixture (whole app against the
fake, SQLite) with helpers: `app.send(user_id, "/start")` (kwargs `photo=`, `video=`, `animation=`, `caption=`,
`entities=`, `caption_entities=`), `app.press(user_id, data)`, `app.click(user_id, "button text part")`,
`app.last_text(user_id)`, `app.find_button(user_id, text)`, `app.panels(user_id)`, `app.feed(update_dict, bot_id)`,
builders `message_update`, `callback_update`, `my_chat_member_update(chat_id, user_id, new=..., rights=...)`,
`channel_post_update(chat_id, text)`, `await app.add_chat(chat_id, user_id, "Title", type="channel", members=…)`
(creates it in the fake world and adds the bot as admin, added by `user_id`),
`await app.add_clone(bot_id, "username_bot", owner_id)`, `app.db()` session, `app.wait_for(cond)`,
`app.publisher`, `app.scheduler`, `app.manager`. Fake world: `app.fake.add_chat(-100..., "Title", members=1200)`,
`app.fake.add_user(id)`, `app.fake.calls_of("sendMessage", chat_id=...)`, `app.fake.messages_to(chat_id)`,
`app.fake.fail(method, code=, description=, retry_after=, when=lambda params: ...)`, `fake.chats[id].messages`.
Users: `SUPER_ID` (super admin = main bot owner), `USER_ID` (a partner), `OWNER2_ID` (owns a clone in some tests).
The main bot runs a network (`MAIN_BOT_MODE="full"`) in tests.
Run: `.venv/bin/python -m pytest -q` from the worktree root (the venv of `/home/user/eMesh`).
Modules written by other agents are stubs in your worktree: monkeypatch them in tests when needed
(`monkeypatch.setattr("app.services.publisher.Publisher.send_now", fake)`), or drive the DB directly.

---------------------------------------------------------------------------------------------------
## 11. Hub mode and workspaces
* `MAIN_BOT_MODE=hub`: the main bot runs no network (`ctx.is_hub`): `open_screen` opens `home` instead of any
  screen in `screens.HUB_HIDDEN`, the bot leaves chats it is added to, the scheduler skips it.
* **🛠 Gestionar** (workspace): a super admin in a main bot sets `bot_users.ws_bot_id` (panel) to a clone's id.
  From then on `ctx.ws_rec` is that clone in every update of that main bot, every panel shows the banner
  «🛠 Gestionando @clone», and the home has `[🚪 Salir de @clone]`. Everything works as in the clone itself:
  data of `ctx.ws_id`, chat calls through `ctx.ws_bot()`, add-to-channel links of the clone. Media sent to the main
  bot is stored with the main bot's file id (`content.apply(post, c, ctx.bot_id)`); the engine passes it to the
  clone automatically (`content.media_for`). Alerts (`events.emit`) go through `ctx.ws_bot()`, so they reach the
  clone's admins in the clone.
