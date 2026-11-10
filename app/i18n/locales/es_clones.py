STRINGS = {
    # ------------------------------------------------------------------ 🤖 Crear mi bot
    "cl.title": "🤖 <b>Crea tu propio bot</b>",
    "cl.intro": (
        "Un bot tuyo con su propia red de distribución: tus canales y grupos, tus mensajes y tus frecuencias. "
        "Se gestiona todo desde Telegram y tú eres su dueño."
    ),
    "cl.how.create": "✨ <b>Crear bot</b>: Telegram lo crea en un par de toques, sin copiar tokens.",
    "cl.how.token": (
        "🔑 <b>Usar token</b>: crea un bot en @BotFather con /newbot (o usa uno que ya tengas) y pega aquí su token."
    ),
    "cl.how.reconnect": (
        "🔑 <b>Usar token</b>: si el token de uno de tus bots ha cambiado, pega aquí el nuevo para volver a "
        "conectarlo."
    ),
    "cl.photo": "🖼 Tu bot se crea con el logo de eMesh como foto; puedes cambiarla cuando quieras en @BotFather.",
    "cl.count": "🤖 Tus bots: <b>{count}</b>/{limit}",
    "cl.limit_reached": "⚠️ Has llegado al máximo de bots. Desconecta uno en «🤖 Mis bots» para añadir otro.",
    "cl.closed": "🔒 Ahora mismo no se pueden crear bots nuevos.",
    "cl.approval": "⏳ Tu bot quedará pendiente hasta que la administración lo apruebe.",
    "cl.newbot_name": "Red de {name}",
    "cl.btn.create": "✨ Crear bot",
    "cl.btn.token": "🔑 Usar token",
    "cl.btn.mybots": "🤖 Mis bots ({n})",
    "cl.btn.mybots_short": "🤖 Mis bots",
    "cl.btn.clone": "🤖 Crear mi bot",
    "cl.btn.open": "🚀 Abrir @{username}",
    "cl.btn.open_main": "🤖 Ir a @{username}",
    "cl.btn.reconnect": "🔑 Conectarlo de nuevo",
    "cl.not_main": (
        "🤖 <b>Crea tu propio bot</b>\n\n"
        "Los bots se crean y se gestionan desde el bot principal de la plataforma. Pulsa el botón para abrirlo."
    ),
    # --- token ---
    "cl.ask_token": (
        "🔑 <b>Usar token</b>\n\n"
        "1. Abre @BotFather y crea un bot con /newbot (o elige uno que ya tengas).\n"
        "2. Copia el token que te da, algo como <code>123456789:AAH…</code>\n"
        "3. Pégalo aquí.\n\n"
        "🔒 El mensaje se borrará en cuanto se lea, para proteger el token."
    ),
    "cl.err.text": "⚠️ Envía el token como texto.",
    "cl.err.format": "⚠️ Eso no parece un token. Tiene esta forma: <code>123456789:AAH…</code>",
    "cl.err.unauthorized": "⚠️ El token no es válido o se ha revocado. Cópialo de nuevo desde @BotFather.",
    "cl.err.network": "⚠️ No se ha podido conectar con Telegram. Inténtalo de nuevo en unos segundos.",
    "cl.err.not_bot": "⚠️ Ese token no es de un bot.",
    "cl.err.is_main": "⚠️ Ese es el token del bot de la plataforma.",
    "cl.err.taken": "⚠️ Ese bot ya lo ha conectado otra persona.",
    "cl.err.limit": "⚠️ Ya tienes el máximo de {limit} bots. Desconecta uno en «🤖 Mis bots» para añadir otro.",
    "cl.err.admin_locked": "🔒 La administración ha desactivado ese bot. Contacta con ella para reactivarlo.",
    "cl.err.closed": "🔒 Ahora mismo no se pueden crear bots nuevos.",
    # --- connected ---
    "cl.ready": (
        "✅ <b>¡Tu bot @{username} está listo!</b> Ábrelo y pulsa /start: en un minuto lo dejas a punto (zona "
        "horaria, unas preguntas y tus canales)."
    ),
    "cl.pending": (
        "⏳ Tu bot @{username} está conectado y pendiente de aprobación. Se te avisará en cuanto la administración "
        "lo revise."
    ),
    "cl.managed_failed": "⚠️ No se ha podido conectar tu nuevo bot @{username}.",
    "cl.approved_dm": (
        "✅ <b>¡Tu bot @{username} se ha aprobado!</b> Ya está en marcha: ábrelo y pulsa /start; en un minuto lo "
        "dejas a punto (zona horaria, unas preguntas y tus canales)."
    ),
    "cl.rejected_dm": (
        "❌ Tu bot @{username} no se ha aprobado. Si crees que es un error, contacta con la administración."
    ),
    "cl.invalid_dm": (
        "⚠️ Tu bot @{username} se ha detenido: su token ya no es válido (¿se ha revocado en @BotFather?).\n\n"
        "Para reactivarlo, conéctalo de nuevo con el token nuevo en «🤖 Crear mi bot» › «🔑 Usar token»: sus datos "
        "se conservan."
    ),
    "cl.new_admin": (
        "🤖 <b>Nuevo clon</b>\n\n"
        "🤖 @{bot} (<code>{bot_id}</code>)\n"
        "👤 Dueño: {owner} (<code>{owner_id}</code>)\n"
        "🔧 Método: {method}"
    ),
    "cl.new_admin_pending": "⏳ <b>Pendiente de aprobación.</b>",
    "cl.method.managed": "✨ Creado con Telegram",
    "cl.method.token": "🔑 Token de @BotFather",
    # --- 🤖 Mis bots ---
    "cl.mybots.title": "🤖 <b>Mis bots</b> ({count}/{limit})",
    "cl.mybots.empty": "Aún no tienes bots. Crea uno con «🤖 Crear mi bot».",
    "cl.mybots.row": "{i}. @{username} · {status}",
    "cl.mybots.hint.pending": "⏳ Un bot pendiente se pondrá en marcha cuando la administración lo apruebe.",
    "cl.mybots.hint.invalid": (
        "❌ Para reactivar un bot con el token no válido, conéctalo de nuevo con «🔑 Usar token»."
    ),
    "cl.status.active": "✅ Activo",
    "cl.status.pending": "⏳ Pendiente de aprobación",
    "cl.status.paused": "⏸ Pausado",
    "cl.status.admin": "🔒 Desactivado por la administración",
    "cl.status.removed": "🔌 Desconectado",
    "cl.status.invalid": "❌ Token no válido",
    "cl.btn.pause": "⏸ Pausar",
    "cl.btn.resume": "▶️ Activar",
    "cl.btn.remove": "🗑 Desconectar",
    "cl.btn.remove_yes": "🗑 Sí, desconectar",
    "cl.paused": "⏸ Bot pausado",
    "cl.resumed": "▶️ Bot activado",
    "cl.resume_failed": (
        "⚠️ No se ha podido poner en marcha el bot: puede que su token se haya revocado. Conéctalo de nuevo con "
        "«🔑 Usar token»."
    ),
    "cl.admin_locked": "🔒 La administración ha desactivado este bot. Contacta con ella para reactivarlo.",
    "cl.confirm_remove": (
        "🗑 <b>¿Desconectar @{username}?</b>\n\n"
        "El bot dejará de funcionar, pero sus datos (canales, mensajes y ajustes) se conservan: si se vuelve a "
        "conectar con su token, todo seguirá como estaba."
    ),
    "cl.confirm_withdraw": (
        "🗑 <b>¿Retirar @{username}?</b>\n\nAún está pendiente de aprobación: se cancelará la solicitud."
    ),
    "cl.removed": "🔌 Bot desconectado",
    "cl.withdrawn": "🗑 Solicitud retirada",
    # ------------------------------------------------------------------------ 👑 Panel
    "sa.panel": (
        "👑 <b>Panel de la plataforma</b>\n"
        "🤖 Bots: <b>{bots}</b> (✅ {active} · ⏸ {paused} · ⏳ {pending} · ❌ {invalid})\n"
        "👥 Usuarios: <b>{users}</b>\n"
        "📣 Chats: <b>{chats}</b> (👤 {members}) · ⏸ pausados por su dueño: {owner_paused}\n"
        "📝 Mensajes activos: <b>{posts}</b>\n"
        "📤 Últimas 24 h: {runs} envíos · {sent} entregas\n"
        "⚙️ Clonación: {policy}"
    ),
    "sa.policy.open": "🌐 Abierta",
    "sa.policy.approval": "⏳ Con aprobación",
    "sa.policy.closed": "🔒 Cerrada",
    "sa.policy.hint.open": "Cualquiera puede crear su bot.",
    "sa.policy.hint.approval": "Los bots nuevos esperan a que un super admin los apruebe.",
    "sa.policy.hint.closed": "No se pueden crear bots nuevos (los super admins sí).",
    "sa.btn.bots": "🤖 Clones",
    "sa.btn.pending": "⏳ Pendientes ({n})",
    "sa.btn.settings": "⚙️ Plataforma",
    "sa.btn.blast": "📢 Aviso a los dueños",
    "sa.btn.errors": "📄 Errores",
    "sa.btn.photo": "🖼 Imagen del bot",
    "sa.main_locked": "ℹ️ El bot principal no se gestiona desde aquí.",
    # --- clones list ---
    "sa.bots.title": "🤖 <b>Clones</b> · {filter}: <b>{count}</b>",
    "sa.bots.row": "{i}. {icon} @{username} · 👤 {owner}\n   └📣 {chats} · 📝 {posts}{paused}",
    "sa.bots.paused": " · ⏸ {n}",
    "sa.bots.empty": "📭 No hay ningún bot aquí.",
    "sa.filter.all": "🌐 Todos",
    "sa.filter.active": "✅ Activos",
    "sa.filter.paused": "⏸ Detenidos",
    "sa.filter.pending": "⏳ Pendientes",
    "sa.filter.invalid": "❌ Token no válido",
    "sa.btn.find": "🔎 Buscar",
    "sa.find.ask": (
        "🔎 <b>Buscar un bot</b>\n\nEnvía su @usuario o su id. También sirve el @usuario o el id de su dueño."
    ),
    "sa.find.none": "🔎 No se ha encontrado ningún bot con «{query}».",
    "sa.find.title": "🔎 <b>Resultados de «{query}»</b>",
    "sa.find.more": "Se muestran los {n} primeros: concreta más la búsqueda para ver el resto.",
    # --- bot detail ---
    "sa.bot": (
        "🤖 <b>@{username}</b>{name}\n"
        "🆔 <code>{id}</code>\n"
        "👤 Dueño: {owner} (<code>{owner_id}</code>)\n"
        "📌 Estado: {status}\n"
        "📅 Creado: {created}\n"
        "📣 Chats: <b>{chats}</b> (🏠 {own} · 🤝 {ext}) · 👤 {members}\n"
        "⏸ Pausados por su dueño: {owner_paused} · ⏳ Pendientes: {pending}\n"
        "📝 Mensajes activos: <b>{posts}</b> · 🕐 {freq}\n"
        "📤 Últimas 24 h: {runs} envíos · {sent} entregas · {failed} fallos\n"
        "🔒 Límites: {limits}"
    ),
    "sa.bot.net_paused": "⏸ <b>La distribución de toda su red está pausada.</b>",
    "sa.lim.chats": "{n} chats",
    "sa.lim.chats_free": "chats sin límite",
    "sa.lim.posts": "{n} mensajes",
    "sa.lim.posts_free": "mensajes sin límite",
    "sa.lim.none": "sin límites",
    "sa.lim.super": "sin límites (es de un super admin)",
    "sa.lim.default": "(predeterminado)",
    "sa.lim.ask": (
        "🔒 <b>Límites de @{username}</b>\n"
        "Ahora: {current}\n\n"
        "Envía el máximo de chats y de mensajes separados por un espacio, por ejemplo <code>50 20</code>.\n"
        "<code>0</code> = sin límite · <code>-</code> = el predeterminado de la plataforma.\n"
        "   └ Lo que ya tiene se mantiene: solo no podrá añadir más."
    ),
    "sa.lim.err": (
        "⚠️ No se entiende. Escribe dos valores, por ejemplo <code>50 20</code>, <code>0 0</code> o <code>- -</code>."
    ),
    "sa.btn.manage": "🛠 Gestionar",
    "sa.btn.disable": "⏸ Desactivar",
    "sa.btn.enable": "▶️ Activar",
    "sa.btn.approve": "✅ Aprobar",
    "sa.btn.reject": "❌ Rechazar",
    "sa.btn.limits": "🔒 Límites",
    "sa.btn.dm": "💬 Escribir al dueño",
    "sa.btn.activity": "📜 Actividad",
    "sa.btn.delete": "🗑 Eliminar",
    "sa.btn.delete_yes": "🗑 Sí, eliminar",
    "sa.btn.delete_final": "🗑 Eliminar definitivamente",
    "sa.disabled": "⏸ Bot desactivado",
    "sa.enabled": "▶️ Bot activado",
    "sa.enable_failed": "⚠️ No se ha podido poner en marcha: su token no es válido.",
    "sa.approved": "✅ Bot aprobado",
    "sa.rejected": "❌ Bot rechazado",
    "sa.not_pending": "ℹ️ Este bot ya no está pendiente: ya se ha decidido.",
    "sa.confirm_delete": (
        "🗑 <b>¿Eliminar @{username}?</b>\n\n"
        "Se detendrá el bot y se borrarán <b>todos</b> sus datos: chats, mensajes, grupos de canales, envíos, "
        "actividad y usuarios. No se puede deshacer."
    ),
    "sa.confirm_delete2": "⚠️ <b>Última confirmación</b>\n\n@{username} y todos sus datos se eliminarán para siempre.",
    "sa.deleted": "🗑 Bot eliminado",
    "sa.dm.ask": (
        "💬 <b>Mensaje para el dueño de @{username}</b>\n\nEscribe el mensaje: le llegará a través de este bot."
    ),
    "sa.dm.header": "💬 <b>Mensaje de la administración</b> sobre tu bot @{username}:",
    "sa.dm.err_text": "⚠️ Envía el mensaje como texto.",
    "sa.dm.sent": "✅ Mensaje enviado al dueño.",
    "sa.dm.failed": "⚠️ No se ha podido enviar: puede que el dueño no haya iniciado este bot o que lo haya bloqueado.",
    "sa.act.title": "📜 <b>Actividad de @{username}</b>",
    "sa.act.empty": "📭 Todavía no hay actividad.",
    # --- 📄 Errores ---
    "sa.file.all": "todos los bots",
    "sa.file.errors": "Errores y avisos de {target}",
    "sa.file.errors_note": "Desde el último reinicio, como máximo las {n} últimas entradas. Horas en {tz}.",
    "sa.file.none": "(ninguno)",
    "sa.file.caption": "📄 {what} · {n} entradas",
    "sa.file.sent": "📄 Archivo enviado",
    # --- ⚙️ Plataforma ---
    "sa.set.title": "⚙️ <b>Plataforma</b>",
    "sa.set.policy": "🤖 Creación de bots: {policy}\n   └ {hint}",
    "sa.set.max_clones": "🔢 Bots por usuario: <b>{value}</b>",
    "sa.set.limit_chats": "📣 Chats por clon: <b>{value}</b>",
    "sa.set.limit_posts": "📝 Mensajes por clon: <b>{value}</b>",
    "sa.set.limits_hint": "   └ Valen para los bots sin límites propios (🔒 Límites en la ficha de cada bot).",
    "sa.set.unlimited": "sin límite",
    "sa.btn.max_clones": "🔢 Bots por usuario: {value}",
    "sa.btn.limit_chats": "📣 Chats por clon: {value}",
    "sa.btn.limit_posts": "📝 Mensajes por clon: {value}",
    "sa.set.ask.max_clones": (
        "🔢 <b>Bots por usuario</b>\nAhora: {value}\n\nEnvía cuántos bots puede tener cada persona "
        "(<code>0</code> = sin límite)."
    ),
    "sa.set.ask.limit_chats": (
        "📣 <b>Chats por clon</b>\nAhora: {value}\n\nEnvía cuántos canales y grupos puede tener cada bot "
        "(<code>0</code> = sin límite)."
    ),
    "sa.set.ask.limit_posts": (
        "📝 <b>Mensajes por clon</b>\nAhora: {value}\n\nEnvía cuántos mensajes puede tener cada bot "
        "(<code>0</code> = sin límite)."
    ),
    # --- 🖼 Imagen del bot ---
    "sa.photo": (
        "🖼 <b>Imagen del bot</b>\n\n"
        "Sale arriba del mensaje de inicio de @{main} y, en los clones, arriba del inicio de sus admins.\n"
        "   └ No cambia ninguna foto de perfil: la de los clones es siempre el logo de eMesh."
    ),
    "sa.photo.none": "📌 Ahora no hay ninguna imagen.",
    "sa.btn.photo_set": "🖼 Poner imagen",
    "sa.btn.photo_change": "🖼 Cambiar imagen",
    "sa.photo.ask": "🖼 Envía la <b>foto</b> que saldrá arriba del inicio (como foto, no como archivo).",
    "sa.photo.err_type": "⚠️ Eso no es una foto. Envíala como foto, no como archivo.",
    "sa.photo.err_read": "⚠️ No se ha podido leer la foto. Prueba con otra.",
    "sa.photo.saved": "✅ Imagen puesta.",
    # --- 📢 Aviso a los dueños ---
    "sa.blast.intro": (
        "📢 <b>Aviso a los dueños</b>\n\nUn mensaje para los dueños de los bots de la plataforma (<b>{n}</b> "
        "personas), enviado a través de este bot."
    ),
    "sa.blast.ask": (
        "📢 <b>Aviso a los dueños</b>\n\nEnvía el mensaje (texto, foto, vídeo…) para los dueños de los bots "
        "(<b>{n}</b> personas). Se copiará tal cual."
    ),
    "sa.blast.none": "📭 Todavía no hay dueños de bots a los que avisar.",
    "sa.blast.confirm": "📢 Este mensaje se enviará a <b>{n}</b> dueños de bots.",
    "sa.btn.blast_write": "✏️ Escribir el aviso",
    "sa.btn.blast_send": "✅ Enviar",
    "sa.blast.started": "📢 Enviando el aviso a <b>{n}</b> dueños… Se avisará al terminar.",
    "sa.blast.dup": "ℹ️ Ese aviso ya se ha enviado.",
    "sa.blast.done": (
        "📢 <b>Aviso a los dueños enviado</b>\n"
        "✅ Entregados: <b>{sent}</b>\n"
        "🚫 Han bloqueado el bot: {blocked}\n"
        "❌ Fallidos: {failed}"
    ),
}
