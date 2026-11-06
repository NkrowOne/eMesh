STRINGS = {
    # ------------------------------------------------------------------ 🤖 Create my bot
    "cl.title": "🤖 <b>Create your own bot</b>",
    "cl.intro": (
        "A bot of your own with its own distribution network: your channels and groups, your posts and your "
        "frequencies. Everything is managed from Telegram and you are its owner."
    ),
    "cl.how.create": "✨ <b>Create bot</b>: Telegram creates it in a couple of taps, no tokens to copy.",
    "cl.how.token": (
        "🔑 <b>Use token</b>: create a bot in @BotFather with /newbot (or use one you already have) and paste its "
        "token here."
    ),
    "cl.how.reconnect": (
        "🔑 <b>Use token</b>: if the token of one of your bots changed, paste the new one here to connect it again."
    ),
    "cl.count": "🤖 Your bots: <b>{count}</b>/{limit}",
    "cl.limit_reached": "⚠️ The maximum number of bots was reached. Disconnect one in «🤖 My bots» to add another.",
    "cl.closed": "🔒 New bots can't be created right now.",
    "cl.approval": "⏳ Your bot will wait until the administration approves it.",
    "cl.newbot_name": "{name}'s Network",
    "cl.btn.create": "✨ Create bot",
    "cl.btn.token": "🔑 Use token",
    "cl.btn.mybots": "🤖 My bots ({n})",
    "cl.btn.mybots_short": "🤖 My bots",
    "cl.btn.clone": "🤖 Create my bot",
    "cl.btn.open": "🚀 Open @{username}",
    "cl.btn.open_main": "🤖 Go to @{username}",
    "cl.btn.reconnect": "🔑 Connect it again",
    "cl.not_main": (
        "🤖 <b>Create your own bot</b>\n\n"
        "Bots are created and managed from the main bot of the platform. Press the button to open it."
    ),
    # --- token ---
    "cl.ask_token": (
        "🔑 <b>Use token</b>\n\n"
        "1. Open @BotFather and create a bot with /newbot (or pick one you already have).\n"
        "2. Copy the token it gives you, something like <code>123456789:AAH…</code>\n"
        "3. Paste it here.\n\n"
        "🔒 The message will be deleted as soon as it is read, to protect the token."
    ),
    "cl.err.text": "⚠️ Send the token as text.",
    "cl.err.format": "⚠️ That doesn't look like a token. It looks like this: <code>123456789:AAH…</code>",
    "cl.err.unauthorized": "⚠️ The token is not valid or was revoked. Copy it again from @BotFather.",
    "cl.err.network": "⚠️ Telegram couldn't be reached. Please try again in a few seconds.",
    "cl.err.not_bot": "⚠️ That token doesn't belong to a bot.",
    "cl.err.is_main": "⚠️ That is the token of the platform's bot.",
    "cl.err.taken": "⚠️ That bot is already connected by someone else.",
    "cl.err.limit": "⚠️ You already have the maximum of {limit} bots. Disconnect one in «🤖 My bots» to add another.",
    "cl.err.admin_locked": "🔒 That bot was disabled by the administration. Contact them to enable it again.",
    "cl.err.closed": "🔒 New bots can't be created right now.",
    # --- connected ---
    "cl.ready": "✅ Your bot @{username} is ready! Open it and press /start.",
    "cl.pending": (
        "⏳ Your bot @{username} is connected and waiting for approval. You will be told as soon as the "
        "administration reviews it."
    ),
    "cl.managed_failed": "⚠️ Your new bot @{username} couldn't be connected.",
    "cl.approved_dm": "✅ <b>Your bot @{username} was approved!</b> It is running now: open it and press /start.",
    "cl.rejected_dm": (
        "❌ Your bot @{username} was not approved. If this looks like a mistake, contact the administration."
    ),
    "cl.invalid_dm": (
        "⚠️ Your bot @{username} stopped: its token is no longer valid (was it revoked in @BotFather?).\n\n"
        "To bring it back, connect it again with the new token in «🤖 Create my bot» › «🔑 Use token»: its data is "
        "kept."
    ),
    "cl.new_admin": (
        "🤖 <b>New clone</b>\n\n"
        "🤖 @{bot} (<code>{bot_id}</code>)\n"
        "👤 Owner: {owner} (<code>{owner_id}</code>)\n"
        "🔧 Method: {method}"
    ),
    "cl.new_admin_pending": "⏳ <b>Waiting for approval.</b>",
    "cl.method.managed": "✨ Created with Telegram",
    "cl.method.token": "🔑 @BotFather token",
    # --- 🤖 My bots ---
    "cl.mybots.title": "🤖 <b>My bots</b> ({count}/{limit})",
    "cl.mybots.empty": "You don't have bots yet. Create one with «🤖 Create my bot».",
    "cl.mybots.row": "{i}. @{username} · {status}",
    "cl.mybots.hint.pending": "⏳ A pending bot starts working once the administration approves it.",
    "cl.mybots.hint.invalid": "❌ To bring back a bot with an invalid token, connect it again with «🔑 Use token».",
    "cl.status.active": "✅ Active",
    "cl.status.pending": "⏳ Waiting for approval",
    "cl.status.paused": "⏸ Paused",
    "cl.status.admin": "🔒 Disabled by the administration",
    "cl.status.removed": "🔌 Disconnected",
    "cl.status.invalid": "❌ Invalid token",
    "cl.btn.pause": "⏸ Pause",
    "cl.btn.resume": "▶️ Activate",
    "cl.btn.remove": "🗑 Disconnect",
    "cl.btn.remove_yes": "🗑 Yes, disconnect",
    "cl.paused": "⏸ Bot paused",
    "cl.resumed": "▶️ Bot activated",
    "cl.resume_failed": (
        "⚠️ The bot couldn't be started: its token may have been revoked. Connect it again with «🔑 Use token»."
    ),
    "cl.admin_locked": "🔒 This bot was disabled by the administration. Contact them to enable it again.",
    "cl.confirm_remove": (
        "🗑 <b>Disconnect @{username}?</b>\n\n"
        "The bot will stop working, but its data (channels, posts and settings) is kept: if it is connected again "
        "with its token, everything will be as it was."
    ),
    "cl.confirm_withdraw": (
        "🗑 <b>Withdraw @{username}?</b>\n\nIt is still waiting for approval: the request will be cancelled."
    ),
    "cl.removed": "🔌 Bot disconnected",
    "cl.withdrawn": "🗑 Request withdrawn",
    # ------------------------------------------------------------------------ 👑 Panel
    "sa.panel": (
        "👑 <b>Platform panel</b>\n"
        "🤖 Bots: <b>{bots}</b> (✅ {active} · ⏸ {paused} · ⏳ {pending} · ❌ {invalid})\n"
        "👥 Users: <b>{users}</b>\n"
        "📣 Chats: <b>{chats}</b> (👤 {members}) · ⏸ paused by their owner: {owner_paused}\n"
        "📝 Active posts: <b>{posts}</b>\n"
        "📤 Last 24 h: {runs} sends · {sent} deliveries\n"
        "⚙️ Cloning: {policy}"
    ),
    "sa.policy.open": "🌐 Open",
    "sa.policy.approval": "⏳ With approval",
    "sa.policy.closed": "🔒 Closed",
    "sa.policy.hint.open": "Anyone can create their bot.",
    "sa.policy.hint.approval": "New bots wait until a super admin approves them.",
    "sa.policy.hint.closed": "New bots can't be created (super admins can).",
    "sa.btn.bots": "🤖 Clones",
    "sa.btn.pending": "⏳ Pending ({n})",
    "sa.btn.settings": "⚙️ Platform",
    "sa.btn.blast": "📢 Notice to owners",
    "sa.btn.errors": "📄 Errors",
    "sa.main_locked": "ℹ️ The main bot isn't managed from here.",
    # --- clones list ---
    "sa.bots.title": "🤖 <b>Clones</b> · {filter}: <b>{count}</b>",
    "sa.bots.row": "{i}. {icon} @{username} · 👤 {owner}\n   └📣 {chats} · 📝 {posts}{paused}",
    "sa.bots.paused": " · ⏸ {n}",
    "sa.bots.empty": "📭 There are no bots here.",
    "sa.filter.all": "🌐 All",
    "sa.filter.active": "✅ Active",
    "sa.filter.paused": "⏸ Stopped",
    "sa.filter.pending": "⏳ Pending",
    "sa.filter.invalid": "❌ Invalid token",
    "sa.btn.find": "🔎 Search",
    "sa.find.ask": "🔎 <b>Search a bot</b>\n\nSend its @username or its id. The @username or id of its owner works too.",
    "sa.find.none": "🔎 No bot was found with «{query}».",
    "sa.find.title": "🔎 <b>Results for «{query}»</b>",
    "sa.find.more": "The first {n} are shown: narrow the search down to see the rest.",
    # --- bot detail ---
    "sa.bot": (
        "🤖 <b>@{username}</b>{name}\n"
        "🆔 <code>{id}</code>\n"
        "👤 Owner: {owner} (<code>{owner_id}</code>)\n"
        "📌 Status: {status}\n"
        "📅 Created: {created}\n"
        "📣 Chats: <b>{chats}</b> (🏠 {own} · 🤝 {ext}) · 👤 {members}\n"
        "⏸ Paused by their owner: {owner_paused} · ⏳ Pending: {pending}\n"
        "📝 Active posts: <b>{posts}</b> · ⏰ {freq}\n"
        "📤 Last 24 h: {runs} sends · {sent} deliveries · {failed} failed\n"
        "🔒 Limits: {limits}"
    ),
    "sa.bot.net_paused": "⏸ <b>The distribution of its whole network is paused.</b>",
    "sa.lim.chats": "{n} chats",
    "sa.lim.chats_free": "unlimited chats",
    "sa.lim.posts": "{n} posts",
    "sa.lim.posts_free": "unlimited posts",
    "sa.lim.none": "no limits",
    "sa.lim.super": "no limits (it belongs to a super admin)",
    "sa.lim.default": "(default)",
    "sa.lim.ask": (
        "🔒 <b>Limits of @{username}</b>\n"
        "Now: {current}\n\n"
        "Send the maximum chats and posts separated by a space, for example <code>50 20</code>.\n"
        "<code>0</code> = no limit · <code>-</code> = the platform default.\n"
        "   └ What it already has is kept: it just can't add more."
    ),
    "sa.lim.err": (
        "⚠️ That wasn't understood. Write two values, for example <code>50 20</code>, <code>0 0</code> or "
        "<code>- -</code>."
    ),
    "sa.btn.manage": "🛠 Manage",
    "sa.btn.disable": "⏸ Disable",
    "sa.btn.enable": "▶️ Enable",
    "sa.btn.approve": "✅ Approve",
    "sa.btn.reject": "❌ Reject",
    "sa.btn.limits": "🔒 Limits",
    "sa.btn.dm": "💬 Write to the owner",
    "sa.btn.activity": "📜 Activity",
    "sa.btn.delete": "🗑 Delete",
    "sa.btn.delete_yes": "🗑 Yes, delete",
    "sa.btn.delete_final": "🗑 Delete for good",
    "sa.disabled": "⏸ Bot disabled",
    "sa.enabled": "▶️ Bot enabled",
    "sa.enable_failed": "⚠️ It couldn't be started: its token is not valid.",
    "sa.approved": "✅ Bot approved",
    "sa.rejected": "❌ Bot rejected",
    "sa.not_pending": "ℹ️ This bot is no longer pending: it was already decided.",
    "sa.confirm_delete": (
        "🗑 <b>Delete @{username}?</b>\n\n"
        "The bot will be stopped and <b>all</b> its data will be deleted: chats, posts, groups of channels, sends, "
        "activity and users. This can't be undone."
    ),
    "sa.confirm_delete2": "⚠️ <b>Last confirmation</b>\n\n@{username} and all its data will be deleted for good.",
    "sa.deleted": "🗑 Bot deleted",
    "sa.dm.ask": (
        "💬 <b>Message for the owner of @{username}</b>\n\nWrite the message: it is delivered through this bot."
    ),
    "sa.dm.header": "💬 <b>Message from the administration</b> about your bot @{username}:",
    "sa.dm.err_text": "⚠️ Send the message as text.",
    "sa.dm.sent": "✅ Message sent to the owner.",
    "sa.dm.failed": "⚠️ It couldn't be sent: the owner may not have started this bot, or blocked it.",
    "sa.act.title": "📜 <b>Activity of @{username}</b>",
    "sa.act.empty": "📭 No activity yet.",
    # --- 📄 Errors ---
    "sa.file.all": "every bot",
    "sa.file.errors": "Errors and warnings of {target}",
    "sa.file.errors_note": "Since the last restart, at most the last {n} entries. Times in {tz}.",
    "sa.file.none": "(none)",
    "sa.file.caption": "📄 {what} · {n} entries",
    "sa.file.sent": "📄 File sent",
    # --- ⚙️ Platform ---
    "sa.set.title": "⚙️ <b>Platform</b>",
    "sa.set.policy": "🤖 Bot creation: {policy}\n   └ {hint}",
    "sa.set.max_clones": "🔢 Bots per user: <b>{value}</b>",
    "sa.set.limit_chats": "📣 Chats per clone: <b>{value}</b>",
    "sa.set.limit_posts": "📝 Posts per clone: <b>{value}</b>",
    "sa.set.limits_hint": "   └ They apply to bots without limits of their own (🔒 Limits in the page of each bot).",
    "sa.set.unlimited": "no limit",
    "sa.btn.max_clones": "🔢 Bots per user: {value}",
    "sa.btn.limit_chats": "📣 Chats per clone: {value}",
    "sa.btn.limit_posts": "📝 Posts per clone: {value}",
    "sa.set.ask.max_clones": (
        "🔢 <b>Bots per user</b>\nNow: {value}\n\nSend how many bots each person may have (<code>0</code> = no limit)."
    ),
    "sa.set.ask.limit_chats": (
        "📣 <b>Chats per clone</b>\nNow: {value}\n\nSend how many channels and groups each bot may have "
        "(<code>0</code> = no limit)."
    ),
    "sa.set.ask.limit_posts": (
        "📝 <b>Posts per clone</b>\nNow: {value}\n\nSend how many posts each bot may have (<code>0</code> = no limit)."
    ),
    # --- 📢 Notice to owners ---
    "sa.blast.intro": (
        "📢 <b>Notice to owners</b>\n\nA message for the owners of the platform's bots (<b>{n}</b> people), sent "
        "through this bot."
    ),
    "sa.blast.ask": (
        "📢 <b>Notice to owners</b>\n\nSend the message (text, photo, video…) for the owners of the bots (<b>{n}</b> "
        "people). It will be copied as it is."
    ),
    "sa.blast.none": "📭 There are no bot owners to notify yet.",
    "sa.blast.confirm": "📢 This message will be sent to <b>{n}</b> bot owners.",
    "sa.btn.blast_write": "✏️ Write the notice",
    "sa.btn.blast_send": "✅ Send",
    "sa.blast.started": "📢 Sending the notice to <b>{n}</b> owners… A report will follow when it is done.",
    "sa.blast.dup": "ℹ️ That notice was already sent.",
    "sa.blast.done": (
        "📢 <b>Notice to owners sent</b>\n"
        "✅ Delivered: <b>{sent}</b>\n"
        "🚫 Blocked the bot: {blocked}\n"
        "❌ Failed: {failed}"
    ),
}
