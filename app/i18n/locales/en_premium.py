STRINGS = {
    # --- 💎 post_premium ---
    "pm.title": "💎 <b>Premium emoji in channels</b> · {name}",
    "pm.intro": (
        "Telegram doesn't let bots use premium emoji in channels. To show them, channels get the post "
        "<b>forwarded</b> from your storage channel (with «Forwarded from…» on top).\n"
        "   └ Groups get it as usual, with its premium emoji."
    ),
    "pm.vault": "🗄 Storage channel: <b>{name}</b>",
    "pm.vault.none": "🗄 Storage channel: — (the channel you forward the message to)",
    "pm.vault.gone": "🗄 Storage channel: ⚠️ <b>{name}</b> is no longer in the network",
    "pm.st.none": "ℹ️ This post has no premium emoji: everyone gets it as usual.",
    "pm.st.ready": "📌 Status: ✅ Ready: channels get it with premium emoji.",
    "pm.st.todo": "📌 Status: ⚠️ Not prepared yet: channels get it with normal emoji.",
    "pm.st.stale": "📌 Status: ⚠️ The post changed: prepare it again (meanwhile channels get it with normal emoji).",
    "pm.live_hint": "🔄 Press «Update published» in the post to change the copies already sent.",
    "pm.b.prepare": "📨 Prepare to forward",
    "pm.b.add": "➕ Add channel ↗",
    "pm.b.change": "🗄 Change storage channel",
    "pm.b.change_ok": "🗄 Yes, change it",
    "pm.b.remove": "✖️ Remove the premium version",
    "pm.b.open": "💎 View",
    "pm.change.ask": "🗄 <b>{name}</b> will stop being your storage channel and will get the network's posts again.\n"
                     "The next channel you forward a prepared message to will be the new one.",
    "pm.change.done": "✅ Done. Forward the next prepared message to your new storage channel.",
    "pm.removed": "✅ Removed: channels will get the normal post.",
    "pm.forward": "📨 <b>Now forward the message above</b> to your storage channel <b>{name}</b>. It is detected "
                  "automatically.",
    "pm.forward.first": (
        "📨 <b>Now forward the message above</b> to one of your channels in the network (ideally a private one "
        "made for this, with the bot as admin). That channel will be your <b>storage channel</b>: it won't get the "
        "network's posts."
    ),
    "pm.err.no_premium": "⚠️ Telegram removed the premium emoji: the owner of this bot has no Telegram Premium.",
    # --- DMs after the forward ---
    "pm.dm.linked": "✅ <b>{name}</b>: ready. Channels will get it with premium emoji, forwarded from 🗄 "
                    "<b>{vault}</b>.",
    "pm.dm.new_vault": "🗄 <b>{vault}</b> is now your storage channel: it doesn't get the network's posts.",
    "pm.dm.not_own": "⚠️ <b>{name}</b>: that chat can't be the storage channel. It must be one of your channels in "
                     "the network. Forward it to another one.",
    "pm.dm.other_vault": "⚠️ <b>{name}</b>: your storage channel is <b>{vault}</b>. Forward the message there, or "
                         "change it in 💎 Premium in channels.",
    "pm.dm.changed": "⚠️ <b>{name}</b> changed or no longer exists. Prepare it again in 💎 Premium in channels.",
    "pm.dm.no_emoji": "⚠️ <b>{name}</b>: the premium emoji didn't reach the storage channel. Forward it without "
                      "hiding the sender.",
    "pm.dm.no_buttons": "⚠️ <b>{name}</b>: the buttons didn't reach the storage channel and couldn't be added. "
                        "Channels keep getting the normal post.",
    # --- other screens ---
    "po.d.premium.ready": "💎 Premium in channels: ✅ ready",
    "po.d.premium.todo": "💎 Premium in channels: ⚠️ not prepared",
    "po.b.premium": "💎 Premium in channels",
    "ch.st.vault": "🗄 Storage channel: receives no posts",
}
