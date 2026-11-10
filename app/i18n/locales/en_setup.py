"""Texts of the setup wizard of a new bot (start module)."""

STRINGS = {
    "setup.intro": (
        "🧭 <b>Setup wizard</b>\n"
        "A few quick questions to get the network ready. Each answer is saved at once and everything can be changed "
        "later in ⚙️ Settings."
    ),
    # --- 1. External channels ----------------------------------------------------------------------
    "setup.q.1": (
        "🤝 <b>Do you accept other people's channels?</b>\n"
        "They will be able to add the bot to their channels and groups to receive the network's posts.\n"
        "   └ With approval, every new channel arrives as a request to the admins."
    ),
    "setup.join.approval": "✅ Yes, with my approval",
    "setup.join.auto": "⚡ Yes, they join on their own",
    "setup.join.closed": "🔒 No, only mine",
    # --- 2. Partners' pauses -----------------------------------------------------------------------
    "setup.q.2": (
        "⏸ <b>Can they pause the distribution in their channels?</b>\n"
        "Each partner pauses it from their page, for at most the time you choose.\n"
        "   └ You always see who pauses and can resume it."
    ),
    "setup.pause.upto": "Up to {t}",
    "setup.pause.no": "🚫 They can't pause",
    # --- 3. Rotation -------------------------------------------------------------------------------
    "setup.q.3": (
        "🔁 <b>Do you want the posts to take turns?</b>\n\n"
        "🔁 <b>With rotation</b>: the posts make a queue. At each time you choose, every channel gets <b>one</b>: "
        "the next in the queue, in order or at random.\n"
        "   └ E.g.: posts A, B and C at 10:00 and 18:00 → today A and B, tomorrow C and A…\n\n"
        "🕐 <b>No rotation</b>: no queue. Each post has its own schedule and goes out at all its times.\n"
        "   └ E.g.: A at 10:00 and B at 18:00, every day.\n\n"
        "It can be changed later in ⏰ Frequencies."
    ),
    "setup.rot.seq": "🔁 Yes, in order",
    "setup.rot.random": "🎲 Yes, at random",
    "setup.rot.off": "🕐 No, each post on its own schedule",
    # --- 4. Rotation times -------------------------------------------------------------------------
    "setup.q.4": (
        "⏰ <b>At what times does each channel get a post?</b>\n"
        "Tap an hour to tick or untick it, or pick a quick option. On each ticked hour every channel gets the next "
        "post of the rotation."
    ),
    "setup.freq.now": "🕐 <b>{n} a day</b>: {times}",
    "setup.freq.days": "📅 Days: {days}",
    "setup.freq.tz": "   └ {tz} time. It can be fine-tuned later in ⏰ Frequencies.",
    "setup.freq.n": "{n} a day",
    "setup.freq.every": "Every {t}",
    "setup.freq.hourly": "Every hour",
    "setup.days.0": "All",
    "setup.days.1": "Mo-Fr",
    "setup.days.2": "Sa-Su",
    "setup.freq.write": "✏️ Type other times (9:30…)",
    "setup.freq.need_hour": "⚠️ Keep at least one hour ticked.",
    "setup.freq.ask": (
        "✏️ <b>Type the times</b>\n\n"
        "Separated by commas, up to 24, with any minutes. For example: <code>9:30, 14, 21:15</code>.\n\n"
        "🕐 Now: <b>{current}</b>"
    ),
    "setup.freq.saved": "✅ Saved: {freq}",
    "setup.btn.next": "Continue ➡️",
    # --- 5. Auto delete ----------------------------------------------------------------------------
    "setup.q.5": (
        "🗑 <b>How long do the posts stay published?</b>\n"
        "After that time they are deleted from the channels on their own.\n"
        "   └ New posts take this value; each one can be changed in its ⚙️ Options."
    ),
    "setup.delete.never": "♾ Never deleted",
    "setup.keep": "Keep: {v}",
    "setup.btn.skip": "⏭ Skip the wizard",
    # --- 6. Summary --------------------------------------------------------------------------------
    "setup.done": "✅ <b>All set</b>\nThe network is set up like this:",
    "setup.sum.pause": "⏸ Partners' pauses: {v}",
    "setup.sum.pause.upto": "up to {t}",
    "setup.sum.pause.free": "no limit",
    "setup.sum.pause.no": "they can't pause",
    "setup.sum.rot": "🔁 Rotation: {v}",
    "setup.sum.rot.seq": "yes, in order",
    "setup.sum.rot.random": "yes, at random",
    "setup.sum.rot.off": "no, each post on its own schedule",
    "setup.sum.delete": "🗑 Auto delete: {v}",
    "setup.sum.after": "after {t}",
    "setup.sum.never": "never",
    "setup.done.next": (
        "👇 Now add the bot to your channels and groups and create a post.\n"
        "   └ Everything can be changed in ⚙️ Settings, ⏰ Frequencies and 📝 Posts."
    ),
    "setup.btn.first_post": "📝 Create the first post",
    "setup.btn.new_post": "📝 Create a post",
    "setup.btn.home": "🏠 Go to the home screen",
}
