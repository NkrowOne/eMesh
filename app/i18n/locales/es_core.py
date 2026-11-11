STRINGS = {
    "core.expired_button": "⌛ Este botón ya no está activo. Pulsa /start.",
    "ws.banner": "🛠 Gestionando <b>@{username}</b>",
    "rights.admin": "ser administrador",
    "rights.can_post_messages": "publicar mensajes",
    "rights.can_edit_messages": "editar mensajes",
    "rights.can_delete_messages": "eliminar mensajes",
    "rights.can_pin_messages": "fijar mensajes",
    "rights.can_invite_users": "invitar usuarios",
    "rights.can_manage_topics": "gestionar temas",
    # --- chat state (services/chatstate.py): messages to the owner of an external chat ---
    "cs.left": (
        "🚪 El bot ya no está en tu {kind} <b>{chat}</b> (lo han sacado o el {kind} ya no existe), así que ha "
        "dejado de recibir los mensajes de la red. Para volver, añade el bot de nuevo como administrador."
    ),
    "cs.rights": (
        "⚠️ Al bot le faltan permisos en tu {kind} <b>{chat}</b>: {missing}. Dáselos en los ajustes del {kind} › "
        "Administradores › el bot. En cuanto lo hagas, volverá a recibir los mensajes."
    ),
    "cs.rights_ok": "✅ Tu {kind} <b>{chat}</b> vuelve a tener los permisos y recibe los mensajes de la red.",
    # --- activity / alerts (services/events.py) ---
    "ev.someone": "alguien",
    "ev.until.none": "hasta que la reanude",
    "ev.until.date": "hasta el {date}",
    "ev.chat_added": "<b>{chat}</b> se ha añadido a la red ({actor}).",
    "ev.chat_request": "<b>{chat}</b> quiere unirse a la red ({actor}).",
    "ev.chat_joined": "<b>{chat}</b> se ha unido a la red ({actor}).",
    "ev.chat_joined.admin": "<b>{chat}</b> se ha unido a la red (aceptado por {actor}).",
    "ev.chat_rejected": "<b>{chat}</b>: solicitud rechazada ({actor}).",
    "ev.chat_banned": "{actor} ha bloqueado <b>{chat}</b>: no podrá volver a la red.",
    "ev.chat_paused": "<b>{chat}</b>: distribución pausada.",
    "ev.chat_paused.owner": "El socio {actor} ha pausado <b>{chat}</b> {until}.",
    "ev.chat_paused.admin": "<b>{chat}</b>: distribución pausada por {actor}.",
    "ev.chat_resumed": "<b>{chat}</b>: distribución reanudada.",
    "ev.chat_resumed.owner": "El socio {actor} ha reanudado <b>{chat}</b>.",
    "ev.chat_resumed.admin": "<b>{chat}</b>: distribución reanudada por {actor}.",
    "ev.chat_resumed.auto": "<b>{chat}</b>: la pausa ha terminado y vuelve a recibir mensajes.",
    "ev.chat_left": (
        "El bot ya no está en <b>{chat}</b> (lo han sacado o el chat ya no existe): ha salido de la red. Si "
        "sigue existiendo, añade el bot de nuevo como administrador para recuperarlo."
    ),
    "ev.chat_removed": "<b>{chat}</b> ha salido de la red.",
    "ev.chat_removed.owner": "El socio {actor} ha sacado <b>{chat}</b> de la red.",
    "ev.chat_removed.admin": "{actor} ha quitado <b>{chat}</b> de la red y el bot ha salido de él.",
    "ev.chat_rights": (
        "<b>{chat}</b>: al bot le faltan permisos ({missing}) y no recibe mensajes. Un administrador de ese chat "
        "debe dárselos; en cuanto lo haga, vuelve a recibir solo."
    ),
    "ev.chat_rights_ok": "<b>{chat}</b> vuelve a tener los permisos y recibe mensajes.",
    "ev.bot_paused": "Distribución de toda la red pausada ({actor}).",
    "ev.bot_resumed": "Distribución de toda la red reanudada ({actor}).",
    "ev.btn.chat": "📣 Ver chat",
    "ev.btn.activity": "📜 Actividad",
    # --- frequencies (services/freq.py) ---
    "freq.h": "{h} h",
    "freq.m": "{m} min",
    "freq.hm": "{h} h {m} min",
    "freq.and": " y ",
    "freq.days.all": "todos los días",
    "freq.days.weekdays": "de lunes a viernes",
    "freq.days.weekend": "fines de semana",
    "freq.days.none": "ningún día",
    "freq.d.every": "cada {every}",
    "freq.d.at": "a las {times}",
    "freq.err.every": "⚠️ No se entiende. Escribe cada cuánto, por ejemplo: <code>45 min</code>, <code>2 h</code> o "
                      "<code>1 h 30 min</code>.",
    "freq.err.every_range": "⚠️ Elige entre 10 minutos y 24 horas.",
    "freq.err.times": "⚠️ No se entiende la hora. Escríbelas así: <code>10:00, 14:30, 22:00</code>.",
    "freq.err.too_many": "⚠️ Como máximo 24 horas distintas.",
    "freq.err.window": "⚠️ Escribe el horario así: <code>08:00-23:00</code> (o <code>0</code> para todo el día).",
    "freq.err.date": "⚠️ Escribe la fecha así: <code>25/12/2026</code>.",
    "freq.err.datetime": "⚠️ Escribe la fecha y la hora así: <code>25/12/2026 20:00</code> (o solo la hora: "
                         "<code>20:00</code>).",
    "freq.err.past": "⚠️ Esa fecha ya ha pasado.",
    # --- content of posts (services/content.py) ---
    "content.kind.text": "📝 Texto",
    "content.kind.photo": "🖼 Foto",
    "content.kind.video": "🎬 Vídeo",
    "content.kind.animation": "🎞 GIF",
    "content.kind.document": "📎 Archivo",
    "content.kind.audio": "🎵 Audio",
    "content.kind.voice": "🎙 Nota de voz",
    "content.err.empty": "⚠️ El mensaje está vacío.",
    "content.err.text_long": "⚠️ El texto es demasiado largo: máximo 4096 caracteres.",
    "content.err.caption_long": "⚠️ Con foto, vídeo o archivo el texto puede tener como máximo 1024 caracteres. "
                                "Acórtalo o envíalo sin el contenido multimedia.",
    "content.err.unsupported": "⚠️ Ese tipo de mensaje no se puede distribuir. Envía texto, foto, vídeo, GIF, "
                               "archivo, audio o nota de voz.",
    "content.err.format": "⚠️ Línea {line}: escribe cada botón así: <code>Nombre - https://enlace</code>.",
    "content.err.button_text": "⚠️ Línea {line}: el nombre del botón debe tener entre 1 y 64 caracteres.",
    "content.err.url": "⚠️ Línea {line}: el enlace no es válido. Usa https://…, t.me/… o @usuario.",
    "content.err.copy": "⚠️ Línea {line}: el texto a copiar debe tener entre 1 y 256 caracteres.",
    "content.err.row": "⚠️ Línea {line}: como máximo 8 botones por fila.",
    "content.err.too_many": "⚠️ Como máximo 30 botones.",
    "content.err.empty_buttons": "⚠️ No se ha encontrado ningún botón.",
    "content.err.media_too_big": "⚠️ El archivo pesa más de 20 MB y no puede pasarse a otro bot. Súbelo desde el bot "
                                 "de esa red.",
    "content.err.media_unavailable": "⚠️ No se ha podido obtener el archivo. Vuelve a enviar el mensaje.",
}
