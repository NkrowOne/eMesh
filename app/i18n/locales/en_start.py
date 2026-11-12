"""Texts of the start module: home, guide, settings, timezone, language, admins, statistics and activity."""

STRINGS = {
    # --- Home: admins ------------------------------------------------------------------------------
    "home.admin.title": "🕸 <b>Your distribution network</b>",
    "home.chats": "📣 Channels and groups: <b>{n}</b> (👤 {members})",
    "home.chats.split": "   └ 🏠 Own: {own} · 🤝 External: {ext}",
    "home.chats.none": (
        "📣 Channels and groups: <b>0</b>\n"
        "   └ Add the bot to your channels and groups with ➕ <b>Add channel or group</b>."
    ),
    "home.posts": "📝 Active posts: <b>{n}</b>",
    "home.posts.none": "   └ Create the first one in 📝 Posts.",
    "home.next_send": "📅 Next send: <b>{date}</b>",
    "home.owner_paused": "⏸ Paused by their partner: <b>{n}</b>",
    "home.pending": "⏳ Pending requests: <b>{n}</b>",
    "home.no_rights": "⚠️ Missing rights: <b>{n}</b>",
    "home.status": "📊 Status: {parts}",
    "home.st.ok": "✅ {n} receiving",
    "home.st.ok.1": "✅ {n} receiving",
    "home.st.paused": "⏸ {n} paused",
    "home.st.paused.1": "⏸ {n} paused",
    "home.st.no_rights": "⚠️ {n} missing rights",
    "home.st.no_rights.1": "⚠️ {n} missing rights",
    "home.st.pending": "⏳ {n} pending",
    "home.st.pending.1": "⏳ {n} pending",
    "home.paused": "⏸ <b>The distribution is paused.</b> Nothing is sent until you resume it.",
    "home.btn.posts": "📝 Posts",
    "home.btn.chats": "📣 Channels and groups",
    "home.btn.groups": "🗂 Channel groups",
    "home.btn.freqs": "⏰ Schedules",
    "home.btn.stats": "📊 Statistics",
    "home.btn.activity": "📜 Activity",
    "home.btn.requests": "⏳ Requests ({n})",
    "home.btn.paused": "⏸ Paused ({n})",
    "home.btn.add_channel": "➕ Add channel",
    "home.btn.add_group": "➕ Add group",
    "home.btn.add_chat": "➕ Add channel or group",
    "home.add.text": (
        "➕ <b>Add a channel or group</b>\n\n"
        "1. Tap ➕ <b>Add channel</b> or ➕ <b>Add group</b> and pick yours.\n"
        "2. Keep the suggested rights checked: the bot needs them to post.\n"
        "3. Done: it joins the network at once and you're told here."
    ),
    "home.add.btn.chats": "📣 See channels and groups",
    "home.btn.pause_all": "⏸ Pause all",
    "home.btn.resume_all": "▶️ Resume all",
    "home.btn.settings": "⚙️ Settings",
    "home.btn.guide": "📖 Guide",
    "home.btn.create_mine": "🤖 Create my bot",
    "home.btn.mybots": "🤖 My bots ({n})",
    "home.btn.panel": "👑 Panel",
    "home.btn.exit_ws": "🔙 Stop managing @{bot}",
    "home.toast.paused": "⏸ Distribution paused: nothing will be sent until you resume it.",
    "home.toast.resumed": "▶️ Distribution resumed.",
    "home.toast.ws_left": "🚪 You no longer manage @{bot}.",
    # --- Home: partners and visitors ---------------------------------------------------------------
    "home.welcome": (
        "👋 <b>Hi, {name}!</b> Welcome to <b>eMesh</b>.\n\n"
        "🕸 eMesh posts messages to Telegram channels and groups automatically: you write the post, choose how often "
        "it goes out and the bot sends it on its own.\n\n"
        "🤖 <b>To post to your channels you need your own bot.</b> Create it in a minute with "
        "<b>🤖 Create my bot</b>: it's yours, with your name, your channels and your rules."
    ),
    "home.join.default": (
        "🤝 <b>Join the network of @{bot}</b>\n"
        "Your channel or group will get its posts automatically. Joining takes a minute:\n\n"
        "1. Tap ➕ <b>Add channel</b> (or ➕ <b>Add group</b>) and pick which one.\n"
        "2. Keep the suggested rights: they are used to post the messages and delete them.\n"
        "3. Done: you'll be told here as soon as it's in.\n\n"
        "⏸ You can pause the posts whenever you want from 📣 My channels."
    ),
    "home.join.default_no_pause": (
        "🤝 <b>Join the network of @{bot}</b>\n"
        "Your channel or group will get its posts automatically. Joining takes a minute:\n\n"
        "1. Tap ➕ <b>Add channel</b> (or ➕ <b>Add group</b>) and pick which one.\n"
        "2. Keep the suggested rights: they are used to post the messages and delete them.\n"
        "3. Done: you'll be told here as soon as it's in."
    ),
    "home.join.min": "👤 Minimum to join: <b>{n}</b> members.",
    "home.join.approval": "⏳ Every channel is reviewed by the team before it is accepted.",
    "home.private": "🔒 <b>This network is private.</b>\nOnly its team can add channels and groups.",
    "home.btn.join_channel": "➕ Add channel",
    "home.btn.join_group": "➕ Add group",
    "home.btn.my_chats": "📣 My channels ({n})",
    "home.btn.support": "🛟 Support",
    "home.btn.create_own": "🤖 Create your own bot",
    # --- Home: main bot in hub mode ----------------------------------------------------------------
    "home.hub": (
        "🕸 <b>eMesh · Your own distribution network</b>\n\n"
        "Create your own bot and post to your channels and groups automatically: each post goes out at the times "
        "you choose.\n\n"
        "✨ <b>With your bot you can:</b>\n"
        "• Post text, photos and videos with colored buttons.\n"
        "• Choose at what times each post goes out and in which channels.\n"
        "• Let other people add their channels to your network, if you want.\n"
        "• See the statistics and the activity of the network.\n\n"
        "👑 <b>The bot is yours</b>: your name, your channels and your rules. The platform keeps it running.\n\n"
        "👇 Tap <b>✨ Create my bot</b> to start."
    ),
    "home.btn.create_hub": "✨ Create my bot",
    "home.id": "🆔 Your ID: <code>{id}</code>",
    # --- Guide: admins -----------------------------------------------------------------------------
    "guide.admin.1": (
        "🕸 <b>How it works</b>\n\n"
        "The bot posts your messages to your channels and groups automatically.\n\n"
        "• 📣 <b>Channels and groups</b>: the chats where the bot is an administrator. Together they are your "
        "<b>network</b>.\n"
        "• 📝 <b>Posts</b>: what gets published: text, photo, video… with buttons.\n"
        "• ⏰ <b>Schedules</b>: each post goes out at its own times; here are the schedule new posts start with "
        "and the anti-spam.\n"
        "• 🗂 <b>Channel groups</b>: sets of channels to send them specific posts.\n\n"
        "👉 <b>First steps</b>: add the bot to a channel with ➕ <b>Add channel or group</b> and create a post in "
        "📝 <b>Posts</b> with its times."
    ),
    "guide.admin.2": (
        "📣 <b>Own and external channels</b>\n\n"
        "<b>Adding channels</b>\n"
        "Tap ➕ <b>Add channel or group</b> on the home screen and keep the suggested rights: in channels, post, "
        "edit and delete messages; in groups, delete and pin messages.\n\n"
        "• 🏠 <b>Own</b>: added by an admin, they join at once.\n"
        "• 🤝 <b>External</b>: other people's, when they are accepted in ⚙️ Settings › 🤝 External channels. With "
        "manual approval they arrive as ⏳ requests.\n\n"
        "<b>Pauses</b>\n"
        "• ⏸ <b>Pause all</b>, on the home screen, stops the whole network.\n"
        "• Each channel can be paused from its page.\n"
        "• The owner of an external channel can pause it within the network's rules (⚙️ Settings › 🤝 External "
        "channels): by default, until they resume it; you can limit it to 1, 3 or 7 days or not allow it. The admins "
        "are alerted and it shows on the home screen, in ⏸ Paused and in 📜 Activity.\n"
        "• The admins can resume any pause; a partner whose pause is lifted is told."
    ),
    "guide.admin.3": (
        "📝 <b>Posts</b>\n\n"
        "In 📝 Posts › ➕ <b>New post</b>:\n"
        "1. Send the post exactly as it should be published: text, photo, video, GIF, file, audio or voice note. "
        "You can also forward it from a channel.\n"
        "2. 🔘 <b>Buttons</b>, one per line: <code>Name - https://link</code>. Several in the same row with "
        "<code>&amp;&amp;</code>, a color at the end (🔵 🟢 🔴) or a text to copy: "
        "<code>Code - copy: PROMO10</code>.\n"
        "3. 🎯 <b>Target</b>: 🌐 everyone, 🏠 own only, 🤝 external only or a 🗂 channel group.\n"
        "4. ⏰ <b>When</b>: ⏰ at its own times, 📢 one-off broadcast (just once: right now or on a date) or "
        "✋ only when you send it.\n"
        "5. 🗑 <b>How long it stays published</b>: from 1 h to 2 days, or it isn't deleted.\n\n"
        "⚙️ <b>Options</b>: 📌 pin, 🔕 silent, 🛡 protect content, 🗑 delete after a while (max. 48 h), ♻️ delete "
        "its previous copy…\n"
        "👁 <b>Preview</b> shows it as is; 🚀 <b>Send now</b> publishes it right away."
    ),
    "guide.admin.4": (
        "⏰ <b>Schedules and anti-spam</b>\n\n"
        "• ⏰ Each post goes to its whole target <b>at its own times</b>: for example, at 10:00 and 18:00, or "
        "every 4 h from 08:00 to 22:00, on the days you choose.\n"
        "• 🕐 The <b>default schedule</b> (⏰ Schedules) is the one every new post starts with; then it is changed "
        "in its ⏰ Schedule.\n"
        "• 📆 <b>Campaign dates</b> limit when a post is sent.\n\n"
        "🛡 <b>Anti-spam</b> (⏰ Schedules › 🛡 Anti-spam): maximum posts a day per channel, minimum gap between "
        "two posts and 🧹 one at a time (the previous one is deleted before posting)."
    ),
    "guide.admin.5": (
        "⚙️ <b>Admins, settings and clones</b>\n\n"
        "• 👮 <b>Admins</b>: the owner adds them with <code>/admin @user</code> and removes them with "
        "<code>/deladmin @user</code> (they must open the bot first). They manage the network; external channels, "
        "support and admins are changed by the owner only.\n"
        "• 🔔 <b>My notifications</b>: network alerts, daily summary and a report of every send. Each admin chooses "
        "their own.\n"
        "• 🗺 <b>Timezone</b>: schedules and dates are calculated with it.\n"
        "• 🤝 <b>External channels</b>: accept them or not, manual approval, minimum members, welcome text, the "
        "partners' pauses and the invite link.\n"
        "• 🧭 <b>Setup wizard</b>: goes through the main settings of the network step by step.\n"
        "• 📊 <b>Statistics</b> and 📜 <b>Activity</b>: sends, reach and what happens in the channels.\n\n"
        "🤖 <b>Clones</b>: every bot of the platform is an independent network. Anyone can create theirs with "
        "🤖 <b>Create my bot</b> in the main bot and manage it in 🤖 <b>My bots</b>."
    ),
    # --- Guide: partners ---------------------------------------------------------------------------
    "guide.partner.1": (
        "🤝 <b>How to join the network</b>\n\n"
        "1. Tap ➕ <b>Add channel</b> or ➕ <b>Add group</b> on the home screen.\n"
        "2. Pick your channel or group and keep the suggested rights.\n"
        "3. If the network reviews requests, your channel stays ⏳ pending until it is accepted. You are notified "
        "here.\n\n"
        "<b>What are the rights for?</b>\n"
        "• Post messages: to publish the network's posts.\n"
        "• Edit messages: to update the posts already published and pin them.\n"
        "• Delete messages: to remove them when they expire or a new one arrives.\n"
        "• In groups, pin messages."
    ),
    "guide.partner.2": (
        "⏸ <b>Pause, categories and leaving</b>\n\n"
        "In 📣 <b>My channels</b> you have the page of each of your channels:\n"
        "• ⏸ <b>Pause</b>: stop receiving posts for a while, within the network's rules. Resume whenever you "
        "want with ▶️ <b>Resume</b>; the network's team can resume it too.\n"
        "• 🗂 <b>Categories</b>: join or leave the open categories of the network.\n"
        "• 🚪 <b>Leave the network</b>: the bot leaves your channel and stops posting there.\n\n"
        "If the bot is missing rights or a pause ends, you are notified here."
    ),
    # --- Guide: hub --------------------------------------------------------------------------------
    "guide.hub.1": (
        "🕸 <b>What is eMesh?</b>\n\n"
        "eMesh creates <b>your own bot</b> to post to your channels and groups automatically.\n\n"
        "1. You add your bot to your channels and groups (and, if you want, other people add theirs).\n"
        "2. You write the posts: text, photo or video, with colored buttons.\n"
        "3. You choose at what times each post goes out.\n\n"
        "👑 <b>The bot is yours</b>: your name, your channels and your rules."
    ),
    "guide.hub.2": (
        "✨ <b>Create your bot</b>\n\n"
        "Tap <b>✨ Create my bot</b> and choose:\n"
        "• ✨ <b>Create bot</b>: Telegram creates it for you in a couple of taps (when available).\n"
        "• 🔑 <b>Use token</b>: create the bot in @BotFather with /newbot and paste the token it gives you here.\n\n"
        "Then open your bot and tap /start: choose the timezone, answer a few quick questions, add the bot to your "
        "channels and create your first post. Inside, 📖 <b>Guide</b> explains everything.\n\n"
        "🤖 In <b>My bots</b> you can pause, resume or disconnect your bots."
    ),
    # --- Settings ----------------------------------------------------------------------------------
    "set.title": "⚙️ <b>Settings</b>",
    "set.tz": "🗺 Timezone: {tz} ({offset})",
    "set.hint.user_tz": "   └ Dates are shown in this timezone.",
    "set.lang": "🌍 Language: {lang}",
    "set.admins": "👮 Admins: {n}",
    "set.notif.admin": "🔔 My notifications: alerts {a} · daily summary {s} · report of every send {r}",
    "set.notif.user": "🔔 My notifications: alerts {a}",
    "set.line.ext_closed": "🤝 External channels: ✖️ not accepted (private network)",
    "set.line.ext_approval": "🤝 External channels: ✅ accepted (with approval)",
    "set.line.ext_auto": "🤝 External channels: ✅ accepted (they join on their own)",
    "set.support": "🛟 Support: {user}",
    "set.owner_only": "🔒 External channels and support are changed by the owner only.",
    "set.btn.tz": "🗺 Timezone",
    "set.btn.lang": "🌍 Language",
    "set.btn.notif": "🔔 My notifications",
    "set.btn.admins": "👮 Admins",
    "set.btn.externals": "🤝 External channels",
    "set.btn.support": "🛟 Support",
    "set.btn.setup": "🧭 Setup wizard",
    "set.days": "{n} days",
    "set.days.1": "{n} day",
    # --- My notifications --------------------------------------------------------------------------
    "set.nt.title": "🔔 <b>My notifications</b>",
    "set.nt.notify": "🔔 Network alerts: {v}",
    "set.nt.hint.notify": "   └ Channels that pause, join, leave or lose rights. Requests always reach you.",
    "set.nt.hint.notify_user": "   └ Notices about your own channels are always sent.",
    "set.nt.summary": "📋 Daily summary: {v}",
    "set.nt.hint.summary": "   └ Every morning, the previous day's sends and what needs attention.",
    "set.nt.reports": "📤 Report of every send: {v}",
    "set.nt.hint.reports": "   └ A message when each send ends: delivered, failed and skipped.",
    "set.nt.btn.notify": "🔔 Network alerts",
    "set.nt.btn.summary": "📋 Daily summary",
    "set.nt.btn.reports": "📤 Report of every send",
    # --- External channels -------------------------------------------------------------------------
    "set.ext.title": "🤝 <b>External channels</b>",
    "set.ext.intro": (
        "Other people can add the bot to their channels and groups to receive the network's posts. You set the "
        "rules."
    ),
    "set.ext.open": "🤝 Accept external channels: {v}",
    "set.ext.hint.closed": "   └ The network is private now: only the admins add channels.",
    "set.ext.approval": "✋ Manual approval: {v}",
    "set.ext.hint.approval_on": "   └ Requests go to the admins, who accept or reject them.",
    "set.ext.hint.approval_off": "   └ They join on their own, without review.",
    "set.ext.min": "🔢 Minimum members: <b>{n}</b>",
    "set.ext.hint.min": "   └ Channels with fewer members can't join (0 = no minimum).",
    "set.ext.text": "💬 Welcome text: {v}",
    "set.ext.text.default": "the default one",
    "set.ext.text.custom": "custom",
    "set.ext.hint.text": "   └ Shown to whoever opens the bot, above the buttons to add it to their channel.",
    "set.ext.groups": "🗂 Open channel groups: <b>{n}</b>",
    "set.ext.hint.groups": "   └ External channels join them on their own and can leave them from their page.",
    "set.ext.link": "🔗 Invite link: {link}",
    "set.ext.hint.link": "   └ Share it with channel owners: it explains how to join.",
    "set.ext.pause": "⏸ Partners can pause: {v}",
    "set.ext.hint.no_pause": "   └ Only the admins can pause their channels.",
    "set.ext.pmax": "⏸ Longest pause: <b>{v}</b>",
    "set.ext.hint.pmax": "   └ You can always resume a pause.",
    "set.ext.pmax.none": "No limit",
    "set.ext.btn.open": "🤝 Accept external channels",
    "set.ext.btn.approval": "✋ Manual approval",
    "set.ext.btn.min": "🔢 Minimum members: {n}",
    "set.ext.btn.text": "💬 Welcome text",
    "set.ext.btn.groups": "🗂 Open channel groups",
    "set.ext.btn.pause": "⏸ Partners can pause",
    "set.ext.min.prompt": (
        "🔢 <b>Minimum members</b>\n\n"
        "Current: <b>{n}</b>\n"
        "External channels and groups with fewer members can't join the network.\n\n"
        "✏️ Send the minimum number (0 = no minimum)."
    ),
    "set.ext.min.invalid": "⚠️ Send a whole number, for example <code>500</code>.",
    "set.ext.text.prompt": (
        "💬 <b>Welcome text</b>\n\n"
        "Shown to whoever opens the bot and isn't an admin, above the buttons to add it to their channel or group.\n\n"
        "✏️ Send the text with the formatting you want (bold, italics, links, emojis). At most {max} characters."
    ),
    "set.ext.text.current": "📋 Current text:\n<blockquote>{text}</blockquote>",
    "set.ext.text.invalid": "⚠️ Send text only, without photos or files.",
    "set.ext.text.reset": "↩️ Default text",
    "set.ext.text.reset_done": "↩️ The default text is used.",
    # --- Support -----------------------------------------------------------------------------------
    "set.sup.title": "🛟 <b>Support</b>",
    "set.sup.intro": (
        "The «🛟 Support» button of the home screen opens this contact so people can write to you: your account, "
        "someone else's or a support bot."
    ),
    "set.sup.custom": "📌 Current: @{user}",
    "set.sup.owner": "📌 Current: @{user} (the owner's account)",
    "set.sup.none": "📌 Current: none. The owner's account has no @username, so the button is not shown.",
    "set.sup.btn.change": "✏️ Change contact",
    "set.sup.btn.mine": "↩️ Use my account",
    "set.sup.btn.owner": "↩️ Use the owner's",
    "set.sup.prompt": (
        "🛟 <b>Support contact</b>\n\n"
        "✏️ Send the @username of a person or a bot, or their link (<code>t.me/username</code>)."
    ),
    "set.sup.invalid": "⚠️ Invalid @username. Example: <code>@support</code>.",
    # --- Language ----------------------------------------------------------------------------------
    "lang.title": "🌍 <b>Idioma / Language</b>",
    "lang.body": "Elige el idioma del bot.\nChoose the bot language.",
    "lang.changed": "✅ Language updated.",
    # --- Admins ------------------------------------------------------------------------------------
    "adm.title": "👮 <b>Administrators</b>",
    "adm.owner": "#{n} ⚜️ {user} ({id})",
    "adm.admin": "#{n} 🔰 {user} ({id})",
    "adm.hint": (
        "ℹ️ To add an admin send <code>/admin @user</code>; to remove one, <code>/deladmin @user</code> or tap 🗑."
    ),
    "adm.hint_started": "   └ They must have opened @{bot} and tapped /start first.",
    "adm.btn.remove": "🗑 #{n} {name}",
    "adm.btn.list": "👮 See admins",
    "adm.ok.added": "✅ {user} is now an admin.",
    "adm.ok.removed": "✅ {user} is no longer an admin.",
    "adm.note.no_dm": "⚠️ They could not be notified by private message.",
    "adm.err.usage": "ℹ️ Usage: <code>/admin @user</code> or <code>/admin ID</code>",
    "adm.err.usage_del": "ℹ️ Usage: <code>/deladmin @user</code> or <code>/deladmin ID</code>",
    "adm.err.not_found": "⚠️ That person was not found. They must open @{bot} and tap /start first.",
    "adm.err.self": "⚠️ You can't change your own role.",
    "adm.err.owner": "⚠️ That person already has every right (owner or super admin).",
    "adm.err.banned": "⚠️ That person is blocked in this bot.",
    "adm.err.already": "ℹ️ {user} is already an admin.",
    "adm.err.not_admin": "ℹ️ {user} is not an admin.",
    "adm.dm.promoted": (
        "🔰 <b>You are now an admin of @{bot}</b>\n\n"
        "You can manage its distribution network. Tap /start to see the panel."
    ),
    "adm.dm.demoted": "ℹ️ You are no longer an admin of @{bot}.",
    # --- Timezone ----------------------------------------------------------------------------------
    "tz.title": "🗺 <b>Timezone</b>",
    "tz.intro.admin": "The network's schedules and send dates are calculated with it.",
    "tz.intro.user": "Dates and times are shown in your timezone.",
    "tz.intro.onboarding": (
        "👋 <b>Welcome to your bot!</b>\n"
        "It's already running; get it ready in a minute:\n"
        "1. 🗺 Choose the timezone.\n"
        "2. 🧭 Answer a few quick questions.\n"
        "3. ➕ Add your channels and 📝 create your first post.\n\n"
        "🗺 <b>Timezone</b>\n"
        "Your network's send times are calculated with it. Telegram doesn't share it with bots, so it's only asked "
        "once (it can be changed later in ⚙️ Settings)."
    ),
    "tz.intro.welcome": (
        "👋 <b>Hi!</b> Before you start, choose your <b>timezone</b>: you'll see dates and times in your local "
        "time.\n"
        "   └ It's only asked once."
    ),
    "tz.welcome": "👋 <b>Welcome to your bot!</b> It's already running; get it ready in a minute.",
    "tz.current": "🕐 Current: <b>{zone}</b> ({offset}) · {time}",
    "tz.current.default": "🕐 Current: <b>{zone}</b> ({offset}) · {time}\n   └ It is the network's timezone.",
    "tz.pick": "👇 Choose your <b>continent</b> and then your <b>country</b>.",
    "tz.cont.ame": "🌎 America",
    "tz.cont.nam": "🌎 North America",
    "tz.cont.cam": "🌎 Central America & Caribbean",
    "tz.cont.sam": "🌎 South America",
    "tz.cont.eur": "🌍 Europe",
    "tz.cont.asi": "🌏 Asia",
    "tz.cont.afr": "🌍 Africa",
    "tz.cont.oce": "🌏 Oceania",
    "tz.btn.write": "✍️ Type zone",
    "tz.btn.photo_set": "🖼 Set image",
    "tz.btn.photo_change": "🖼 Change image",
    "tz.btn.photo_del": "🗑 Remove image",
    "tz.photo.prompt": "🖼 Send the <b>photo</b> that will be shown when this menu is opened, in every bot.",
    "tz.photo.invalid": "⚠️ That isn't a photo. Send it as a photo, not as a file.",
    "tz.photo.saved": "✅ Image saved.",
    "tz.photo.deleted": "🗑 Image removed.",
    "tz.regions": "👇 Choose your region:",
    "tz.countries": "👇 Choose your country:",
    "tz.zones": "👇 Choose your timezone:",
    "tz.write.prompt": (
        "✍️ <b>Type a timezone</b>\n\n"
        "Send the name of your zone in IANA format, for example <code>Europe/Madrid</code> or "
        "<code>America/Mexico_City</code>.\n\n"
        "📋 Full list: https://en.wikipedia.org/wiki/List_of_tz_database_time_zones"
    ),
    "tz.write.invalid": "⚠️ That timezone is not valid. Use the format <code>Continent/City</code>.",
    "tz.saved.admin": "✅ Network timezone: <b>{zone}</b>. The next sends have been recalculated.",
    "tz.saved.first": "✅ Network timezone: <b>{zone}</b>.",
    "tz.saved.known": "🗺 Your network's timezone: <b>{zone}</b>, the one you already chose. It can be changed in "
                      "⚙️ Settings.",
    "tz.saved.user": "✅ Your timezone is now <b>{zone}</b>.",
    "tz.saved.welcome": "✅ Your timezone: <b>{zone}</b>. You can change it in ⚙️ Settings.",
    # --- Statistics and activity -------------------------------------------------------------------
    "stats.title": "📊 <b>Statistics</b> · {period}",
    "stats.period.0": "last 24 h",
    "stats.period.1": "last 7 days",
    "stats.period.2": "last 30 days",
    "stats.runs": "📤 Sends: <b>{n}</b>",
    "stats.sent": "✅ Delivered: <b>{n}</b>",
    "stats.failed": "❌ Failed: <b>{n}</b>",
    "stats.skipped": "🛡 Skipped by anti-spam: <b>{n}</b>",
    "stats.reach": "👁 Reach: <b>{n}</b>",
    "stats.hint.reach": "   └ Members of the chats that received the posts.",
    "stats.chats": "📣 Chats: {n} (🏠 {own} · 🤝 {ext}) · 👤 {members}",
    "stats.paused": "⏸ Paused: {n}",
    "stats.no_rights": "⚠️ Missing rights: {n}",
    "stats.pending": "⏳ Pending: {n}",
    "stats.top": "🏆 <b>Most sent posts</b>",
    "stats.top.item": "{i}. {name} — {n}",
    "stats.btn.0": "24 h",
    "stats.btn.1": "7 days",
    "stats.btn.2": "30 days",
    "stats.btn.activity": "📜 Activity",
    "stats.act.title": "📜 <b>Activity</b>",
    "stats.act.empty": (
        "No activity yet. What happens in the network's channels shows up here: the ones that join, pause, lose "
        "rights or leave."
    ),
}
