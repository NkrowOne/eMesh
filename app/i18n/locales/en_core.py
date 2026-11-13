STRINGS = {
    "core.expired_button": "⌛ This button is no longer active. Press /start.",
    "ws.banner": "🛠 Managing <b>@{username}</b>",
    "rights.admin": "be an administrator",
    "rights.can_post_messages": "post messages",
    "rights.can_edit_messages": "edit messages",
    "rights.can_delete_messages": "delete messages",
    "rights.can_pin_messages": "pin messages",
    "rights.can_invite_users": "invite users",
    "rights.can_manage_topics": "manage topics",
    # --- chat state (services/chatstate.py): messages to the owner of an external chat ---
    "cs.left": (
        "🚪 The bot is no longer in your {kind} <b>{chat}</b> (kicked or {kind} deleted). It no longer receives "
        "the network's posts. To come back, add the bot as an admin."
    ),
    "cs.rights": (
        "⚠️ The bot is missing rights in your {kind} <b>{chat}</b>: {missing}. It receives no posts until you "
        "grant them (Administrators › the bot)."
    ),
    "cs.rights_ok": "✅ Your {kind} <b>{chat}</b> has its rights back and receives the network's posts.",
    # --- activity / alerts (services/events.py) ---
    "ev.someone": "someone",
    "ev.until.none": "until they resume it",
    "ev.until.date": "until {date}",
    "ev.chat_added": "<b>{chat}</b> was added to the network ({actor}).",
    "ev.chat_request": "<b>{chat}</b> wants to join the network ({actor}).",
    "ev.chat_joined": "<b>{chat}</b> joined the network ({actor}).",
    "ev.chat_joined.admin": "<b>{chat}</b> joined the network (accepted by {actor}).",
    "ev.chat_rejected": "<b>{chat}</b>: request rejected ({actor}).",
    "ev.chat_banned": "{actor} banned <b>{chat}</b>: it can't come back to the network.",
    "ev.chat_paused": "<b>{chat}</b>: distribution paused.",
    "ev.chat_paused.owner": "Your partner {actor} paused <b>{chat}</b> {until}.",
    "ev.chat_paused.admin": "<b>{chat}</b>: distribution paused by {actor}.",
    "ev.chat_resumed": "<b>{chat}</b>: distribution resumed.",
    "ev.chat_resumed.owner": "Your partner {actor} resumed <b>{chat}</b>.",
    "ev.chat_resumed.admin": "<b>{chat}</b>: distribution resumed by {actor}.",
    "ev.chat_resumed.auto": "<b>{chat}</b>: the pause is over and it receives posts again.",
    "ev.chat_left": (
        "The bot is no longer in <b>{chat}</b> (kicked or chat deleted). Out of the network. To bring it back, "
        "add the bot as an admin."
    ),
    "ev.chat_removed": "<b>{chat}</b> left the network.",
    "ev.chat_removed.owner": "Your partner {actor} removed <b>{chat}</b> from the network.",
    "ev.chat_removed.admin": "{actor} removed <b>{chat}</b> from the network. The bot left the chat.",
    "ev.chat_rights": (
        "<b>{chat}</b>: missing rights ({missing}). It receives no posts until an admin of the chat grants them "
        "to the bot."
    ),
    "ev.chat_rights_ok": "<b>{chat}</b> has its rights back and receives posts.",
    "ev.bot_paused": "Distribution of the whole network paused ({actor}).",
    "ev.bot_resumed": "Distribution of the whole network resumed ({actor}).",
    "ev.post_missed.late": (
        "<b>{post}</b> was not sent. It was scheduled for {due} and the bot was not available at that time. "
        "Sends are never made late: you can send it now from the post."
    ),
    "ev.post_missed.no_chats": (
        "<b>{post}</b> was not sent ({due}): no chat of its audience can receive it now. "
        "Check whether they are paused, missing rights, or the audience is empty."
    ),
    "ev.btn.post": "📝 View post",
    "ev.btn.chat": "📣 View chat",
    "ev.btn.activity": "📜 Activity",
    # --- frequencies (services/freq.py) ---
    "freq.h": "{h} h",
    "freq.m": "{m} min",
    "freq.hm": "{h} h {m} min",
    "freq.and": " and ",
    "freq.days.all": "every day",
    "freq.days.weekdays": "Monday to Friday",
    "freq.days.weekend": "weekends",
    "freq.days.none": "no day",
    "freq.d.every": "every {every}",
    "freq.d.at": "at {times}",
    "freq.err.every": "⚠️ That isn't clear. Write how often, for example: <code>45 min</code>, <code>2 h</code> or "
                      "<code>1 h 30 min</code>.",
    "freq.err.every_range": "⚠️ Choose between 10 minutes and 24 hours.",
    "freq.err.times": "⚠️ That time isn't clear. Write them like this: <code>10:00, 14:30, 22:00</code>.",
    "freq.err.too_many": "⚠️ At most 24 different times.",
    "freq.err.window": "⚠️ Write the hours like this: <code>08:00-23:00</code> (or <code>0</code> for all day).",
    "freq.err.date": "⚠️ Write the date like this: <code>25/12/2026</code>.",
    "freq.err.datetime": "⚠️ Write the date and time like this: <code>25/12/2026 20:00</code> (or just the time: "
                         "<code>20:00</code>).",
    "freq.err.past": "⚠️ That date has already passed.",
    # --- content of posts (services/content.py) ---
    "content.kind.text": "📝 Text",
    "content.kind.photo": "🖼 Photo",
    "content.kind.video": "🎬 Video",
    "content.kind.animation": "🎞 GIF",
    "content.kind.document": "📎 File",
    "content.kind.audio": "🎵 Audio",
    "content.kind.voice": "🎙 Voice note",
    "content.err.empty": "⚠️ The message is empty.",
    "content.err.text_long": "⚠️ The text is too long: 4096 characters at most.",
    "content.err.caption_long": "⚠️ With a photo, video or file the text can have 1024 characters at most. Shorten "
                                "it or send it without the media.",
    "content.err.unsupported": "⚠️ That kind of message can't be distributed. Send text, a photo, video, GIF, file, "
                               "audio or voice note.",
    "content.err.format": "⚠️ Line {line}: write each button like this: <code>Name - https://link</code>.",
    "content.err.button_text": "⚠️ Line {line}: the button name must have 1 to 64 characters.",
    "content.err.url": "⚠️ Line {line}: the link isn't valid. Use https://…, t.me/… or @username.",
    "content.err.copy": "⚠️ Line {line}: the text to copy must have 1 to 256 characters.",
    "content.err.row": "⚠️ Line {line}: 8 buttons per row at most.",
    "content.err.too_many": "⚠️ 30 buttons at most.",
    "content.err.empty_buttons": "⚠️ No button was found.",
    "content.err.media_too_big": "⚠️ The file is bigger than 20 MB and can't be passed to another bot. Upload it "
                                 "from the bot of that network.",
    "content.err.media_unavailable": "⚠️ The file couldn't be obtained. Send the message again.",
}
