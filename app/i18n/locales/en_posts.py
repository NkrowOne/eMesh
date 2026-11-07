STRINGS = {
    # --- list ---
    "po.list.title": "📝 <b>Posts</b>",
    "po.list.legend": "🔁 rotation · ⏰ own schedule · 📢 one-off · ✋ manual",
    "po.list.item": "{n}. {status} {mode} <b>{name}</b> · {kind}\n   └🎯 {targets} · {extra}",
    "po.list.runs": "📤 {sends}",
    "po.list.next": "📅 {date}",
    "po.list.empty": "📭 There are no posts yet. Create the first one with ➕ New post.",
    "po.btn.new": "➕ New post",
    "po.btn.defaults": "⚙️ Default options",
    "po.limit": "🔒 This network already has the maximum number of posts ({max}). Delete one to create another.",
    # --- counts ---
    "po.unit.chats": "{n} chats",
    "po.unit.chats.1": "{n} chat",
    "po.unit.times": "{n} times",
    "po.unit.times.1": "{n} time",
    "po.unit.deliveries": "{n} deliveries",
    "po.unit.deliveries.1": "{n} delivery",
    "po.unit.sends": "{n} sends",
    "po.unit.sends.1": "{n} send",
    "po.unit.buttons": "{n} buttons",
    "po.unit.buttons.1": "{n} button",
    "po.unit.copies": "{n} copies",
    "po.unit.copies.1": "{n} copy",
    "po.unit.days": "{n} days",
    "po.unit.days.1": "{n} day",
    # --- targets ---
    "po.tg.all": "🌐 Everyone",
    "po.tg.own": "🏠 Own only",
    "po.tg.ext": "🤝 External only",
    "po.tg.group": "🗂 {name} ({n})",
    "po.tgs.all": "🌐 Everyone",
    "po.tgs.own": "🏠 Own",
    "po.tgs.ext": "🤝 External",
    "po.tgl.all": "Everyone",
    "po.tgl.own": "Own",
    "po.tgl.ext": "External",
    "po.tg.none": "⚠️ nobody",
    "po.tg.more": " +{n} more",
    "po.tg.hint": "Choose one or more targets: they add up.",
    "po.tg.count": "👥 It will reach: <b>{chats}</b> · 👤 {members}",
    "po.tg.count_hint": (
        "   └ Only the chats that receive posts right now count (approved, with rights and not paused)."
    ),
    "po.tg.need_one": "⚠️ Choose at least one target.",
    "po.targets.title": "🎯 <b>Target</b> · {name}",
    # --- create wizard ---
    "po.w.content": (
        "📝 <b>New post</b> · 1/5\n\n"
        "Send the message exactly as it should be published: text, photo, video, GIF, file, audio or voice note, "
        "with its formatting (<b>bold</b>, <i>italic</i>, links, emoji). It can also be forwarded from a channel."
    ),
    "po.w.buttons": "🔘 <b>Buttons</b> · 2/5\n\nSend the buttons that go under the message.\n\n{help}",
    "po.w.no_buttons": "⏭ No buttons",
    "po.w.targets": "🎯 <b>Who receives it?</b> · 3/5",
    "po.w.continue": "✅ Continue",
    "po.w.when": (
        "⏰ <b>When is it sent?</b> · 4/5\n\n"
        "🔁 <b>In rotation</b> (recommended)\n"
        "   └ It takes turns with the other posts at the frequency of each channel (global: {freq}).\n"
        "⏰ <b>On its own schedule</b>\n"
        "   └ It has its own frequency; at each slot it goes to all its chats.\n"
        "📢 <b>One-off broadcast</b>\n"
        "   └ It is sent just once to its whole target: right now or on the date you choose.\n"
        "✋ <b>Only when sent by hand</b>\n"
        "   └ Only with 🚀 Send now."
    ),
    "po.w.date": "📢 <b>One-off broadcast</b> · 4/5\n\nPress 🚀 <b>Right now</b> or {ask}",
    "po.w.delete": (
        "🗑 <b>How long does it stay published?</b> · 5/5\n"
        "   └ After that time it is deleted from the channels automatically."
    ),
    "po.w.no_delete": "♾ Don't delete",
    "po.help.buttons": (
        "One button per line: <code>Name - https://link</code>\n"
        "• On the same row: separate them with <code>&amp;&amp;</code>\n"
        "• Color: add 🔵, 🟢 or 🔴 at the end\n"
        "• A button that copies a text: <code>Code - copy: PROMO10</code>\n"
        "• 30 buttons at most, 8 per row\n\n"
        "Example:\n"
        "<pre>Web - https://example.com 🟢\n"
        "Channel - @mychannel &amp;&amp; Group - t.me/mygroup\n"
        "Code - copy: PROMO10 🔵</pre>"
    ),
    "po.mode.rotation": "🔁 In rotation",
    "po.mode.rotation_rec": "🔁 In rotation (recommended)",
    "po.mode.own": "⏰ On its own schedule",
    "po.mode.once": "📢 One-off broadcast",
    "po.w.now": "🚀 Right now",
    "po.mode.manual": "✋ Only when I send it",
    "po.date.ask": (
        "send the date and time: <code>25/12/2026 20:00</code>, <code>25/12 20:00</code> or just the time "
        "(<code>20:00</code>: today, or tomorrow when it has already passed).\n🗺 Timezone: {tz}"
    ),
    "po.saved": "✅ Post saved",
    "po.err.use_buttons": "👇 Use the buttons below.",
    "po.err.text_only": "⚠️ Send it as text.",
    # --- detail ---
    "po.d.title": "📝 <b>{name}</b>",
    "po.d.status": "📌 Status: {value}",
    "po.st.active": "▶️ Active",
    "po.st.paused": "⏸ Paused",
    "po.st.done": "✅ Finished",
    "po.d.kind": "🧩 Type: {kind} · {buttons}",
    "po.d.buttons": "🔘 {buttons}",
    "po.d.no_buttons": "no buttons",
    "po.d.targets": "🎯 Target: {targets} → {chats} (👤 {members})",
    "po.d.no_targets": "🎯 Target: ⚠️ none, it is sent to nobody",
    "po.d.mode": "⏰ Sending: {value}",
    "po.dm.rotation": "🔁 In rotation",
    "po.dm.own": "⏰ Own schedule · {freq}",
    "po.dm.once": "📢 One-off broadcast · {date}",
    "po.dm.manual": "✋ Manual",
    "po.dh.rotation": "   └ Each channel gets it in turns, at its frequency.",
    "po.dh.own": "   └ At each slot of its schedule it goes to all its chats.",
    "po.dh.once": "   └ It is sent once and then it is finished.",
    "po.dh.manual": "   └ It is only sent with 🚀 Send now.",
    "po.d.next": "📅 Next send: <b>{date}</b>",
    "po.d.campaign": "📆 Campaign: {value}",
    "po.camp.both": "from {start} to {end}",
    "po.camp.from": "from {start}",
    "po.camp.to": "until {end}",
    "po.d.sent": "📤 Sent: {times} · {deliveries} · last {last}",
    "po.d.never": "📤 It hasn't been sent yet.",
    "po.d.live": "🟢 Published right now in: <b>{chats}</b>",
    "po.d.opts": "⚙️ <b>Options</b>",
    "po.b.preview": "👁 Preview",
    "po.b.send": "🚀 Send now",
    "po.b.content": "✏️ Content",
    "po.b.buttons": "🔘 Buttons",
    "po.b.targets": "🎯 Target",
    "po.b.sched": "⏰ Schedule",
    "po.b.opts": "⚙️ Options",
    "po.b.dup": "🧬 Duplicate",
    "po.b.update": "🔄 Update published ({n})",
    "po.b.retire": "🔚 Withdraw ({n})",
    "po.b.pause": "⏸ Pause",
    "po.b.play": "▶️ Activate",
    "po.b.delete": "🗑 Delete",
    "po.no": "❌ No",
    # --- detail actions ---
    "po.preview.failed": "⚠️ The preview couldn't be sent. Try again.",
    "po.busy": "⏳ This post is being sent right now. Wait until it finishes.",
    "po.send.nobody": "⚠️ No chat can receive it right now. Check its 🎯 Target.",
    "po.send.paused": "⏸ The distribution is paused: nothing is sent. Resume it on the home screen with ▶️ Resume all.",
    "po.send.confirm": (
        "🚀 <b>{name}</b>\n\nIt will be sent now to <b>{chats}</b> (👤 {members}).\n"
        "   └ The 🛡 anti-spam limits of the network apply."
    ),
    "po.send.yes": "✅ Send",
    "po.send.started": "🚀 Sending…",
    "po.retire.confirm": "🔚 <b>{name}</b> will be deleted from where it is published now: <b>{chats}</b>.",
    "po.retire.yes": "🔚 Withdraw",
    "po.retire.started": "🔚 Withdrawing…",
    "po.update.confirm": (
        "🔄 The current text and buttons of <b>{name}</b> will be applied to what is already published: "
        "<b>{copies}</b>.\n   └ The photo, video or file doesn't change."
    ),
    "po.update.yes": "🔄 Update",
    "po.update.started": "🔄 Updating…",
    "po.nothing_live": "ℹ️ It isn't published in any chat right now.",
    "po.dup.name": "{name} (copy)",
    "po.dup.done": "🧬 Copy created paused: review it and activate it.",
    "po.del.confirm": "🗑 Delete <b>{name}</b>?",
    "po.del.live": (
        "🟢 It is published right now in <b>{chats}</b>:\n"
        "• <b>Delete and withdraw</b>: it is also deleted from those chats.\n"
        "• <b>Delete the post only</b>: the published copies stay (and are deleted on time when they have an auto "
        "delete)."
    ),
    "po.del.all": "🗑 Delete and withdraw the published ({n})",
    "po.del.only": "🗑 Delete the post only",
    "po.del.yes": "🗑 Yes, delete",
    "po.del.done": "🗑 Post deleted",
    "po.del.retiring": "🗑 Deleting: the published copies are being withdrawn…",
    "po.paused": "⏸ Post paused",
    "po.activated": "▶️ Post activated",
    "po.ended": "📆 Its campaign is over: change the end date in ⏰ Schedule to activate it.",
    "po.activate.date": "📆 <b>New date</b> · {name}\n\nA future date is needed to send it again.\n{ask}",
    # --- content ---
    "po.c.title": "✏️ <b>Content</b> · {name}",
    "po.c.name": "🏷 Internal name: {name}",
    "po.c.name_hint": "   └ Only the admins see it, to recognise the post in the list.",
    "po.c.kind": "🧩 Type: {kind}",
    "po.c.text": "📝 Text: <i>{text}</i>",
    "po.c.no_text": "📝 Text: ✖️",
    "po.c.b.change": "✏️ Change the message",
    "po.c.b.text": "📝 Change the text only",
    "po.c.b.name": "🏷 Internal name",
    "po.c.b.nomedia": "🖼 Remove the media",
    "po.c.ask_content": (
        "✏️ <b>Change the message</b> · {name}\n\n"
        "Send the new message exactly as it should be published (text, or media with its text). It replaces the "
        "current one; the buttons and options are kept."
    ),
    "po.c.ask_text": (
        "📝 <b>Change the text only</b> · {name}\n\nSend the new text with its formatting (4096 characters at most)."
    ),
    "po.c.ask_caption": (
        "📝 <b>Change the text only</b> · {name}\n\n"
        "Send the new text with its formatting. The media is kept; with media the text can have 1024 characters at "
        "most."
    ),
    "po.c.ask_name": "🏷 <b>Internal name</b>\n\nCurrent: {name}\nSend the new name (64 characters at most).",
    "po.c.nomedia.confirm": "🖼 Remove the media of <b>{name}</b>? Only the text will be left.",
    "po.c.nomedia.yes": "🖼 Remove the media",
    "po.c.nomedia.no_text": "⚠️ Without the media it would be empty: add a text first with 📝 Change the text only.",
    "po.c.nomedia.done": "🖼 Media removed",
    "po.c.live_hint": "🔄 Press Update published to apply it to the copies already sent.",
    # --- schedule ---
    "po.s.title": "⏰ <b>Schedule</b> · {name}",
    "po.s.modes": (
        "🔁 <b>In rotation</b>\n"
        "   └ It takes turns with the other posts at the frequency of each channel (global: {freq}).\n"
        "⏰ <b>On its own schedule</b>\n"
        "   └ At each slot of its schedule it goes to all its chats.\n"
        "📢 <b>One-off broadcast</b>\n"
        "   └ It is sent just once, on the date chosen; then it is finished.\n"
        "✋ <b>Only when I send it</b>\n"
        "   └ Only with 🚀 Send now."
    ),
    "po.s.campaign": "📆 Campaign: {value}",
    "po.s.no_campaign": "no dates",
    "po.s.campaign_hint": (
        "   └ Optional. Outside those dates it isn't sent in rotation nor on its schedule; after the last day it is "
        "finished."
    ),
    "po.s.b.own": "⏰ Own schedule: {freq}",
    "po.s.b.date": "📆 Date: {date}",
    "po.s.b.from": "📆 From: {date}",
    "po.s.b.to": "📆 Until: {date}",
    "po.s.ask_date": "📆 <b>Date of the send</b> · {name}\n\n{ask}",
    "po.s.ask_start": (
        "📆 <b>Start of the campaign</b> · {name}\n\nCurrent: {current}\n"
        "Send the first day it is sent: <code>dd/mm/yyyy</code>. <code>0</code> removes the date."
    ),
    "po.s.ask_end": (
        "📆 <b>End of the campaign</b> · {name}\n\nCurrent: {current}\n"
        "Send the last day it is sent: <code>dd/mm/yyyy</code>. <code>0</code> removes the date."
    ),
    "po.s.err.order": "⚠️ The end of the campaign can't be before its start.",
    # --- options ---
    "po.opts.title": "⚙️ <b>Options</b> · {name}",
    "po.defaults.title": "⚙️ <b>Default options</b>\nThey apply to new posts; the existing ones don't change.",
    "po.o.pin": "📌 Pin: {v}",
    "po.o.silent": "🔕 Silent: {v}",
    "po.o.protect": "🛡 Protect content: {v}",
    "po.o.link_preview": "🔗 Link preview: {v}",
    "po.o.caption_above": "🔼 Text above the media: {v}",
    "po.o.spoiler": "🫣 Spoiler: {v}",
    "po.o.delete_previous": "♻️ Delete its previous copy: {v}",
    "po.o.delete_after": "🗑 Auto delete: {v}",
    "po.ob.pin": "📌 Pin",
    "po.ob.silent": "🔕 Silent",
    "po.ob.protect": "🛡 Protect content",
    "po.ob.link_preview": "🔗 Link preview",
    "po.ob.caption_above": "🔼 Text above the media",
    "po.ob.spoiler": "🫣 Spoiler",
    "po.ob.delete_previous": "♻️ Delete its previous copy",
    "po.oh.pin": "   └ It is pinned in the chat without notifying the members.",
    "po.oh.silent": "   └ It arrives without a notification sound.",
    "po.oh.protect": "   └ It can't be forwarded nor saved.",
    "po.oh.link_preview": "   └ Shows the preview of the first link of the text.",
    "po.oh.caption_above": "   └ The text is shown above the photo, video or GIF.",
    "po.oh.spoiler": "   └ The media is blurred until it is tapped.",
    "po.oh.delete_previous": "   └ When it is sent to a chat again, the previous copy in that chat is deleted.",
    "po.oh.delete_after": (
        "   └ Each copy is deleted after that time (48 h at most: Telegram doesn't let bots delete older messages)."
    ),
    "po.ad.never": "✖️ never",
    "po.ad.after": "{t} after it is sent",
    "po.ad.b.never": "Never",
    "po.ad.b.other": "✏️ Other",
    "po.ad.ask": (
        "🗑 <b>Auto delete</b>\n\n"
        "Send after how long each copy is deleted, between 15 min and 48 h: <code>45 min</code>, <code>2 h</code>, "
        "<code>1 h 30 min</code>, <code>36 h</code>. <code>0</code> = never."
    ),
    "po.err.duration": (
        "⚠️ That isn't clear. Write the time like this: <code>45 min</code>, <code>2 h</code> or "
        "<code>1 h 30 min</code>."
    ),
    "po.err.duration_range": "⚠️ Choose between 15 minutes and 48 hours.",
    # --- buttons editor (post_buttons.py) ---
    "pb.title": "🔘 <b>Buttons</b> · {name}",
    "pb.hint": "Tap a button to change, move or remove it. This is how they look under the message 👇",
    "pb.none": "It has no buttons yet. Add one with ➕ or write them all at once.",
    "pb.count": "🔘 {n} of {max} buttons",
    "pb.live_hint": "🔄 The changes reach the published copies with 🔄 Update published, in the post.",
    "pb.b.add": "➕ Add button",
    "pb.b.bulk": "✍️ Write them all",
    "pb.b.clear": "🗑 Remove all",
    "pb.b.preview": "👁 Preview",
    "pb.e.title": "🔘 <b>Button</b> · {name}",
    "pb.e.name": "🏷 Name: {v}",
    "pb.e.url": "🔗 Link: {v}",
    "pb.e.copy": "📋 Copies the text: <code>{v}</code>",
    "pb.e.color": "🎨 Color: {v}",
    "pb.e.pos": "📍 Row {row} · position {col}",
    "pb.e.hint": "   └ ⬅️ ➡️ move it inside its row; ⬆️ ⬇️ move it to the row above or below.",
    "pb.e.b.name": "🏷 Name",
    "pb.e.b.link": "🔗 Link",
    "pb.e.b.del": "🗑 Remove button",
    "pb.edge": "↔️ It can't move further that way.",
    "pb.row_full": "⚠️ That row already has 8 buttons.",
    "pb.removed": "🗑 Button removed",
    "pb.max": "⚠️ {max} buttons at most.",
    "pb.a.name": (
        "➕ <b>New button</b> · 1/4\n\n🏷 Send the name of the button: the text shown on it (64 characters at "
        "most)."
    ),
    "pb.a.link": "➕ <b>New button</b> · 2/4\n\n{ask}",
    "pb.a.color": "➕ <b>New button</b> · 3/4\n\n🎨 Choose the color of <b>{name}</b>:",
    "pb.a.place": "➕ <b>New button</b> · 4/4\n\n📍 Where does <b>{name}</b> go?",
    "pb.a.new_row": "⬇️ On a new row",
    "pb.a.same_row": "➡️ Next to the last one",
    "pb.added": "✅ Button added",
    "pb.ask_link": (
        "🔗 Send where it leads:\n"
        "• a link: <code>https://…</code>, <code>t.me/…</code> or <code>@username</code>\n"
        "• or <code>copy: TEXT</code> for a button that copies that text (for example, a discount code)."
    ),
    "pb.ask_name": "🏷 <b>Name of the button</b>\n\nCurrent: {name}\nSend the new name (64 characters at most).",
    "pb.ask_link_edit": "🔗 <b>Link of the button</b> · {name}\n\nCurrent: {current}\n\n{ask}",
    "pb.err.name": "⚠️ The name must have 1 to 64 characters.",
    "pb.err.link": "⚠️ The link isn't valid. Use https://…, t.me/…, @username or copy: TEXT.",
    "pb.err.copy": "⚠️ The text to copy must have 1 to 256 characters.",
    "pb.bulk.title": "✍️ <b>Write all the buttons</b> · {name}",
    "pb.bulk.current": "Current buttons (copy, change and send them):\n<pre>{rows}</pre>",
    "pb.bulk.too_long": "ℹ️ The current buttons are too long to show them here.",
    "pb.bulk.replace": "⚠️ What is sent replaces all the current buttons.",
    "pb.clear.confirm": "🗑 Remove all the buttons of <b>{name}</b> ({buttons})?",
    "pb.clear.yes": "🗑 Remove all",
    "pb.cleared": "🗑 Buttons removed",
}
