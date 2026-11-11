"""Textos del módulo de inicio: inicio, guía, ajustes, zona horaria, idioma, admins, estadísticas y actividad."""

STRINGS = {
    # --- Inicio: vista de los admins ---------------------------------------------------------------
    "home.admin.title": "🕸 <b>Tu red de distribución</b>",
    "home.chats": "📣 Canales y grupos: <b>{n}</b> (👤 {members})",
    "home.chats.split": "   └ 🏠 Propios: {own} · 🤝 Externos: {ext}",
    "home.chats.none": (
        "📣 Canales y grupos: <b>0</b>\n"
        "   └ Añade el bot a tus canales y grupos con ➕ <b>Añadir canal o grupo</b>."
    ),
    "home.posts": "📝 Mensajes activos: <b>{n}</b>",
    "home.posts.none": "   └ Crea el primero en 📝 Mensajes.",
    "home.next_send": "📅 Próximo envío: <b>{date}</b>",
    "home.owner_paused": "⏸ Pausados por su asociado: <b>{n}</b>",
    "home.pending": "⏳ Solicitudes pendientes: <b>{n}</b>",
    "home.no_rights": "⚠️ Sin permisos: <b>{n}</b>",
    "home.status": "📊 Estado: {parts}",
    "home.st.ok": "✅ {n} reciben",
    "home.st.ok.1": "✅ {n} recibe",
    "home.st.paused": "⏸ {n} pausados",
    "home.st.paused.1": "⏸ {n} pausado",
    "home.st.no_rights": "⚠️ {n} sin permisos",
    "home.st.no_rights.1": "⚠️ {n} sin permisos",
    "home.st.pending": "⏳ {n} pendientes",
    "home.st.pending.1": "⏳ {n} pendiente",
    "home.paused": "⏸ <b>La distribución está pausada.</b> No se envía nada hasta que la reanudes.",
    "home.btn.posts": "📝 Mensajes",
    "home.btn.chats": "📣 Canales y grupos",
    "home.btn.groups": "🗂 Grupos de canales",
    "home.btn.freqs": "⏰ Horarios",
    "home.btn.stats": "📊 Estadísticas",
    "home.btn.activity": "📜 Actividad",
    "home.btn.requests": "⏳ Solicitudes ({n})",
    "home.btn.paused": "⏸ Pausados ({n})",
    "home.btn.add_channel": "➕ Añadir canal ↗",
    "home.btn.add_group": "➕ Añadir grupo ↗",
    "home.btn.add_chat": "➕ Añadir canal o grupo",
    "home.add.text": (
        "➕ <b>Añadir canal o grupo</b>\n\n"
        "1. Pulsa ➕ <b>Añadir canal</b> o ➕ <b>Añadir grupo</b> y elige el tuyo.\n"
        "2. Deja marcados los permisos que se proponen: el bot los necesita para publicar.\n"
        "3. Listo: entra en la red al momento y se te avisa por aquí."
    ),
    "home.add.btn.chats": "📣 Ver canales y grupos",
    "home.btn.pause_all": "⏸ Pausar todo",
    "home.btn.resume_all": "▶️ Reanudar todo",
    "home.btn.settings": "⚙️ Ajustes",
    "home.btn.guide": "📖 Guía",
    "home.btn.create_mine": "🤖 Crear mi bot",
    "home.btn.mybots": "🤖 Mis bots ({n})",
    "home.btn.panel": "👑 Panel",
    "home.btn.exit_ws": "🔙 Dejar de gestionar @{bot}",
    "home.toast.paused": "⏸ Distribución pausada: no se enviará nada hasta que la reanudes.",
    "home.toast.resumed": "▶️ Distribución reanudada.",
    "home.toast.ws_left": "🚪 Has dejado de gestionar @{bot}.",
    # --- Inicio: socios y visitantes ---------------------------------------------------------------
    "home.welcome": (
        "👋 <b>¡Hola, {name}!</b> Te damos la bienvenida a <b>eMesh</b>.\n\n"
        "🕸 eMesh publica mensajes en canales y grupos de Telegram de forma automática: escribes el mensaje, eliges "
        "cada cuánto se publica y el bot lo envía solo.\n\n"
        "🤖 <b>Para publicar en tus canales necesitas tu propio bot.</b> Créalo en un minuto con "
        "<b>🤖 Crear mi bot</b>: es tuyo, con tu nombre, tus canales y tus reglas."
    ),
    "home.join.default": (
        "🤝 <b>Únete a la red de @{bot}</b>\n"
        "Tu canal o grupo recibirá sus publicaciones de forma automática. Unirse lleva un minuto:\n\n"
        "1. Pulsa ➕ <b>Añadir a mi canal</b> (o <b>a mi grupo</b>) y elige cuál.\n"
        "2. Conserva los permisos que se proponen: sirven para publicar los mensajes y borrarlos.\n"
        "3. Listo: se te avisará por aquí cuando ya esté dentro.\n\n"
        "⏸ Puedes pausar las publicaciones cuando quieras desde 📣 Mis canales."
    ),
    "home.join.default_no_pause": (
        "🤝 <b>Únete a la red de @{bot}</b>\n"
        "Tu canal o grupo recibirá sus publicaciones de forma automática. Unirse lleva un minuto:\n\n"
        "1. Pulsa ➕ <b>Añadir a mi canal</b> (o <b>a mi grupo</b>) y elige cuál.\n"
        "2. Conserva los permisos que se proponen: sirven para publicar los mensajes y borrarlos.\n"
        "3. Listo: se te avisará por aquí cuando ya esté dentro."
    ),
    "home.join.min": "👤 Mínimo para unirse: <b>{n}</b> miembros.",
    "home.join.approval": "⏳ La administración revisa cada canal antes de aceptarlo.",
    "home.private": "🔒 <b>Esta red es privada.</b>\nSolo la administración puede añadir canales y grupos.",
    "home.btn.join_channel": "➕ Añadir a mi canal ↗",
    "home.btn.join_group": "➕ Añadir a mi grupo ↗",
    "home.btn.my_chats": "📣 Mis canales ({n})",
    "home.btn.support": "🛟 Soporte ↗",
    "home.btn.create_own": "🤖 Crea tu propio bot",
    # --- Inicio: bot principal en modo hub ---------------------------------------------------------
    "home.hub": (
        "🕸 <b>eMesh · Tu propia red de distribución</b>\n\n"
        "Crea tu propio bot y publica mensajes en tus canales y grupos de forma automática: cada mensaje sale a "
        "las horas que elijas.\n\n"
        "✨ <b>Con tu bot podrás:</b>\n"
        "• Publicar texto, fotos y vídeos con botones de colores.\n"
        "• Elegir a qué horas se publica cada mensaje y en qué canales.\n"
        "• Dejar que otras personas añadan sus canales a tu red, si quieres.\n"
        "• Ver las estadísticas y la actividad de la red.\n\n"
        "👑 <b>El bot es tuyo</b>: tu nombre, tus canales y tus reglas. La plataforma se encarga de que funcione.\n\n"
        "👇 Pulsa <b>✨ Crear mi bot</b> para empezar."
    ),
    "home.btn.create_hub": "✨ Crear mi bot",
    "home.id": "🆔 Tu ID: <code>{id}</code>",
    # --- Guía: admins ------------------------------------------------------------------------------
    "guide.admin.1": (
        "🕸 <b>Cómo funciona</b>\n\n"
        "El bot publica tus mensajes en tus canales y grupos de forma automática.\n\n"
        "• 📣 <b>Canales y grupos</b>: los chats donde el bot es administrador. Juntos forman tu <b>red</b>.\n"
        "• 📝 <b>Mensajes</b>: lo que se publica: texto, foto, vídeo… con botones.\n"
        "• ⏰ <b>Horarios</b>: cada mensaje se envía a sus horas; aquí está el horario con el que empiezan los "
        "nuevos y el anti-spam.\n"
        "• 🗂 <b>Grupos de canales</b>: conjuntos de canales para enviarles mensajes concretos.\n\n"
        "👉 <b>Primeros pasos</b>: añade el bot a un canal con ➕ <b>Añadir canal o grupo</b> y crea un mensaje en "
        "📝 <b>Mensajes</b> con sus horas."
    ),
    "guide.admin.2": (
        "📣 <b>Canales propios y externos</b>\n\n"
        "<b>Añadir canales</b>\n"
        "Pulsa ➕ <b>Añadir canal o grupo</b>, en el inicio, y conserva los permisos que se proponen: en canales, "
        "publicar, editar y eliminar mensajes; en grupos, eliminar y fijar mensajes.\n\n"
        "• 🏠 <b>Propios</b>: los añade un admin y entran al momento.\n"
        "• 🤝 <b>Externos</b>: los de otras personas, si se admiten en ⚙️ Ajustes › 🤝 Canales externos. Con "
        "aprobación manual llegan como ⏳ solicitudes.\n\n"
        "<b>Pausas</b>\n"
        "• ⏸ <b>Pausar todo</b>, en el inicio, detiene toda la red.\n"
        "• Cada canal se puede pausar desde su ficha.\n"
        "• El dueño de un canal externo puede pausarlo según las reglas de la red (⚙️ Ajustes › 🤝 Canales "
        "externos): por defecto, hasta que lo reanude; puedes limitarlo a 1, 3 o 7 días o no permitirlo. Se avisa a "
        "los admins y se ve en el inicio, en ⏸ Pausados y en 📜 Actividad.\n"
        "• Los admins pueden reanudar cualquier pausa; si era del socio, se le avisa."
    ),
    "guide.admin.3": (
        "📝 <b>Mensajes</b>\n\n"
        "En 📝 Mensajes › ➕ <b>Nuevo mensaje</b>:\n"
        "1. Envía el mensaje tal como quieres que se publique: texto, foto, vídeo, GIF, archivo, audio o nota de "
        "voz. También puedes reenviarlo desde un canal.\n"
        "2. 🔘 <b>Botones</b>, uno por línea: <code>Nombre - https://enlace</code>. Varios en la misma fila con "
        "<code>&amp;&amp;</code>, un color al final (🔵 🟢 🔴) o un texto para copiar: "
        "<code>Código - copiar: PROMO10</code>.\n"
        "3. 🎯 <b>Destino</b>: 🌐 todos, 🏠 solo propios, 🤝 solo externos o un 🗂 grupo de canales.\n"
        "4. ⏰ <b>Cuándo</b>: ⏰ a sus horas, 📢 difusión puntual (una sola vez: ahora mismo o en una fecha) o "
        "✋ solo cuando lo envíes.\n"
        "5. 🗑 <b>Cuánto tiempo sigue publicado</b>: de 1 h a 2 días, o no se borra.\n\n"
        "⚙️ <b>Opciones</b>: 📌 fijar, 🔕 sin sonido, 🛡 proteger el contenido, 🗑 borrar pasado un tiempo "
        "(máx. 48 h), ♻️ borrar su envío anterior…\n"
        "👁 <b>Vista previa</b> lo muestra tal cual; 🚀 <b>Enviar ahora</b> lo publica al momento."
    ),
    "guide.admin.4": (
        "⏰ <b>Horarios y anti-spam</b>\n\n"
        "• ⏰ Cada mensaje se envía <b>a sus horas</b> a todo su destino: por ejemplo, a las 10:00 y a las 18:00, "
        "o cada 4 h de 08:00 a 22:00, los días que elijas.\n"
        "• 🕐 El <b>horario por defecto</b> (⏰ Horarios) es con el que empieza cada mensaje nuevo; luego se cambia "
        "en su ⏰ Programación.\n"
        "• 📆 Las <b>fechas de campaña</b> limitan cuándo se envía un mensaje.\n\n"
        "🛡 <b>Anti-spam</b> (⏰ Horarios › 🛡 Anti-spam): máximo de mensajes al día por canal, separación "
        "mínima entre dos mensajes y 🧹 uno a la vez (se borra el anterior antes de publicar)."
    ),
    "guide.admin.5": (
        "⚙️ <b>Admins, ajustes y clones</b>\n\n"
        "• 👮 <b>Admins</b>: el propietario los añade con <code>/admin @usuario</code> y los quita con "
        "<code>/deladmin @usuario</code> (antes deben abrir el bot). Gestionan la red; los canales externos, el "
        "soporte y los admins solo los cambia el propietario.\n"
        "• 🔔 <b>Mis avisos</b>: alertas de la red, resumen diario e informe de cada envío. Cada admin elige los "
        "suyos.\n"
        "• 🗺 <b>Zona horaria</b>: los horarios y las fechas se calculan con ella.\n"
        "• 🤝 <b>Canales externos</b>: admitirlos o no, aprobación manual, mínimo de miembros, texto de bienvenida, "
        "las pausas de los socios y el enlace para invitar.\n"
        "• 🧭 <b>Asistente de configuración</b>: repasa paso a paso lo principal de la red.\n"
        "• 📊 <b>Estadísticas</b> y 📜 <b>Actividad</b>: envíos, alcance y lo que pasa en los canales.\n\n"
        "🤖 <b>Clones</b>: cada bot de la plataforma es una red independiente. Cualquiera puede crear el suyo con "
        "🤖 <b>Crear mi bot</b> en el bot principal y gestionarlo en 🤖 <b>Mis bots</b>."
    ),
    # --- Guía: socios ------------------------------------------------------------------------------
    "guide.partner.1": (
        "🤝 <b>Cómo unirse a la red</b>\n\n"
        "1. Pulsa ➕ <b>Añadir a mi canal</b> o ➕ <b>Añadir a mi grupo</b> en el inicio.\n"
        "2. Elige tu canal o grupo y conserva los permisos que se proponen.\n"
        "3. Si la red revisa las solicitudes, tu canal queda ⏳ pendiente hasta que se acepte. Se te avisa por "
        "aquí.\n\n"
        "<b>¿Para qué son los permisos?</b>\n"
        "• Publicar mensajes: para publicar los mensajes de la red.\n"
        "• Editar mensajes: para actualizar los ya publicados y fijarlos.\n"
        "• Eliminar mensajes: para borrarlos cuando caducan o llega uno nuevo.\n"
        "• En grupos, fijar mensajes."
    ),
    "guide.partner.2": (
        "⏸ <b>Pausar, categorías y salir</b>\n\n"
        "En 📣 <b>Mis canales</b> tienes la ficha de cada uno de tus canales:\n"
        "• ⏸ <b>Pausar</b>: deja de recibir mensajes durante un tiempo, dentro de las reglas de la red. Lo "
        "reanudas cuando quieras con ▶️ <b>Reanudar</b>; la administración también puede reanudarlo.\n"
        "• 🗂 <b>Categorías</b>: únete a las categorías abiertas de la red o sal de ellas.\n"
        "• 🚪 <b>Salir de la red</b>: el bot sale de tu canal y deja de publicar en él.\n\n"
        "Si al bot le faltan permisos o termina una pausa, se te avisa por aquí."
    ),
    # --- Guía: hub ---------------------------------------------------------------------------------
    "guide.hub.1": (
        "🕸 <b>¿Qué es eMesh?</b>\n\n"
        "eMesh crea <b>tu propio bot</b> para publicar mensajes en tus canales y grupos de forma automática.\n\n"
        "1. Añades tu bot a tus canales y grupos (y, si quieres, otras personas añaden los suyos).\n"
        "2. Escribes los mensajes: texto, foto o vídeo, con botones de colores.\n"
        "3. Eliges a qué horas se publica cada mensaje.\n\n"
        "👑 <b>El bot es tuyo</b>: tu nombre, tus canales y tus reglas."
    ),
    "guide.hub.2": (
        "✨ <b>Crear tu bot</b>\n\n"
        "Pulsa <b>✨ Crear mi bot</b> y elige:\n"
        "• ✨ <b>Crear bot</b>: Telegram lo crea por ti en un par de toques (si está disponible).\n"
        "• 🔑 <b>Usar token</b>: crea el bot en @BotFather con /newbot y pega aquí el token que te da.\n\n"
        "Después abre tu bot y pulsa /start: elige la zona horaria, responde unas preguntas rápidas, añade el bot a "
        "tus canales y crea tu primer mensaje. Dentro, 📖 <b>Guía</b> lo explica todo.\n\n"
        "🤖 En <b>Mis bots</b> puedes pausar, reanudar o desconectar tus bots."
    ),
    # --- Ajustes -----------------------------------------------------------------------------------
    "set.title": "⚙️ <b>Ajustes</b>",
    "set.tz": "🗺 Zona horaria: {tz} ({offset})",
    "set.hint.user_tz": "   └ Las fechas se muestran en esta hora.",
    "set.lang": "🌍 Idioma: {lang}",
    "set.admins": "👮 Admins: {n}",
    "set.notif.admin": "🔔 Mis avisos: alertas {a} · resumen diario {s} · informe de cada envío {r}",
    "set.notif.user": "🔔 Mis avisos: alertas {a}",
    "set.line.ext_closed": "🤝 Canales externos: ✖️ no admitidos (red privada)",
    "set.line.ext_approval": "🤝 Canales externos: ✅ admitidos (con aprobación)",
    "set.line.ext_auto": "🤝 Canales externos: ✅ admitidos (entran solos)",
    "set.support": "🛟 Soporte: {user}",
    "set.owner_only": "🔒 Los canales externos y el soporte solo los cambia el propietario.",
    "set.btn.tz": "🗺 Zona horaria",
    "set.btn.lang": "🌍 Idioma",
    "set.btn.notif": "🔔 Mis avisos",
    "set.btn.admins": "👮 Admins",
    "set.btn.externals": "🤝 Canales externos",
    "set.btn.support": "🛟 Soporte",
    "set.btn.setup": "🧭 Asistente de configuración",
    "set.days": "{n} días",
    "set.days.1": "{n} día",
    # --- Mis avisos --------------------------------------------------------------------------------
    "set.nt.title": "🔔 <b>Mis avisos</b>",
    "set.nt.notify": "🔔 Alertas de la red: {v}",
    "set.nt.hint.notify": "   └ Canales que se pausan, se unen, salen o pierden permisos.",
    "set.nt.hint.notify_user": "   └ Los avisos sobre tus propios canales llegan siempre.",
    "set.nt.summary": "📋 Resumen diario: {v}",
    "set.nt.hint.summary": "   └ Cada mañana, los envíos del día anterior y lo que necesita atención.",
    "set.nt.reports": "📤 Informe de cada envío: {v}",
    "set.nt.hint.reports": "   └ Un mensaje al terminar cada envío: entregados, fallos y omitidos.",
    "set.nt.btn.notify": "🔔 Alertas de la red",
    "set.nt.btn.summary": "📋 Resumen diario",
    "set.nt.btn.reports": "📤 Informe de cada envío",
    # --- Canales externos --------------------------------------------------------------------------
    "set.ext.title": "🤝 <b>Canales externos</b>",
    "set.ext.intro": (
        "Otras personas pueden añadir el bot a sus canales y grupos para recibir los mensajes de la red. Las "
        "reglas las pones tú."
    ),
    "set.ext.open": "🤝 Admitir canales externos: {v}",
    "set.ext.hint.closed": "   └ Ahora la red es privada: solo los admins añaden canales.",
    "set.ext.approval": "✋ Aprobación manual: {v}",
    "set.ext.hint.approval_on": "   └ Las solicitudes llegan a los admins, que las aceptan o rechazan.",
    "set.ext.hint.approval_off": "   └ Entran solos, sin revisión.",
    "set.ext.min": "🔢 Mínimo de miembros: <b>{n}</b>",
    "set.ext.hint.min": "   └ Los canales con menos miembros no pueden unirse (0 = sin mínimo).",
    "set.ext.text": "💬 Texto de bienvenida: {v}",
    "set.ext.text.default": "el predeterminado",
    "set.ext.text.custom": "personalizado",
    "set.ext.hint.text": "   └ Lo ve quien abre el bot, sobre los botones para añadirlo a su canal.",
    "set.ext.groups": "🗂 Grupos abiertos: <b>{n}</b>",
    "set.ext.hint.groups": "   └ Los canales externos entran solos en ellos y pueden salir desde su panel.",
    "set.ext.link": "🔗 Enlace para invitar: {link}",
    "set.ext.hint.link": "   └ Compártelo con los dueños de canales: les explica cómo unirse.",
    "set.ext.pause": "⏸ Los socios pueden pausar: {v}",
    "set.ext.hint.no_pause": "   └ Solo los admins pueden pausar sus canales.",
    "set.ext.pmax": "⏸ Pausa máxima: <b>{v}</b>",
    "set.ext.hint.pmax": "   └ Tú siempre puedes reanudar una pausa.",
    "set.ext.pmax.none": "Sin límite",
    "set.ext.btn.open": "🤝 Admitir canales externos",
    "set.ext.btn.approval": "✋ Aprobación manual",
    "set.ext.btn.min": "🔢 Mínimo de miembros: {n}",
    "set.ext.btn.text": "💬 Texto de bienvenida",
    "set.ext.btn.groups": "🗂 Grupos abiertos",
    "set.ext.btn.pause": "⏸ Los socios pueden pausar",
    "set.ext.min.prompt": (
        "🔢 <b>Mínimo de miembros</b>\n\n"
        "Actual: <b>{n}</b>\n"
        "Los canales y grupos externos con menos miembros no pueden unirse a la red.\n\n"
        "✏️ Envía el número mínimo (0 = sin mínimo)."
    ),
    "set.ext.min.invalid": "⚠️ Envía un número entero, por ejemplo <code>500</code>.",
    "set.ext.text.prompt": (
        "💬 <b>Texto de bienvenida</b>\n\n"
        "Lo ve quien abre el bot y no es admin, sobre los botones para añadirlo a su canal o grupo.\n\n"
        "✏️ Envía el texto con el formato que quieras (negrita, cursiva, enlaces, emojis). Máximo {max} caracteres."
    ),
    "set.ext.text.current": "📋 Texto actual:\n<blockquote>{text}</blockquote>",
    "set.ext.text.invalid": "⚠️ Envía solo texto, sin fotos ni archivos.",
    "set.ext.text.reset": "↩️ Texto predeterminado",
    "set.ext.text.reset_done": "↩️ Se usa el texto predeterminado.",
    # --- Soporte -----------------------------------------------------------------------------------
    "set.sup.title": "🛟 <b>Soporte</b>",
    "set.sup.intro": (
        "El botón «🛟 Soporte» del inicio abre este contacto para que te escriban: tu cuenta, la de otra persona o "
        "un bot de atención."
    ),
    "set.sup.custom": "📌 Actual: @{user}",
    "set.sup.owner": "📌 Actual: @{user} (la cuenta del propietario)",
    "set.sup.none": (
        "📌 Actual: ninguno. La cuenta del propietario no tiene @usuario, así que el botón no se muestra."
    ),
    "set.sup.btn.change": "✏️ Cambiar contacto",
    "set.sup.btn.mine": "↩️ Usar mi cuenta",
    "set.sup.btn.owner": "↩️ Usar la del propietario",
    "set.sup.prompt": (
        "🛟 <b>Contacto de soporte</b>\n\n"
        "✏️ Envía el @usuario de una persona o de un bot, o su enlace (<code>t.me/usuario</code>)."
    ),
    "set.sup.invalid": "⚠️ @usuario no válido. Ejemplo: <code>@soporte</code>.",
    # --- Idioma ------------------------------------------------------------------------------------
    "lang.title": "🌍 <b>Idioma / Language</b>",
    "lang.body": "Elige el idioma del bot.\nChoose the bot language.",
    "lang.changed": "✅ Idioma actualizado.",
    # --- Administradores ---------------------------------------------------------------------------
    "adm.title": "👮 <b>Administradores</b>",
    "adm.owner": "#{n} ⚜️ {user} ({id})",
    "adm.admin": "#{n} 🔰 {user} ({id})",
    "adm.hint": (
        "ℹ️ Para añadir un admin envía <code>/admin @usuario</code>; para quitarlo, <code>/deladmin @usuario</code> "
        "o pulsa 🗑."
    ),
    "adm.hint_started": "   └ Antes debe haber abierto @{bot} y pulsado /start.",
    "adm.btn.remove": "🗑 #{n} {name}",
    "adm.btn.list": "👮 Ver admins",
    "adm.ok.added": "✅ {user} ahora es admin.",
    "adm.ok.removed": "✅ {user} ya no es admin.",
    "adm.note.no_dm": "⚠️ No se le ha podido avisar por mensaje privado.",
    "adm.err.usage": "ℹ️ Uso: <code>/admin @usuario</code> o <code>/admin ID</code>",
    "adm.err.usage_del": "ℹ️ Uso: <code>/deladmin @usuario</code> o <code>/deladmin ID</code>",
    "adm.err.not_found": "⚠️ No se ha encontrado a esa persona. Antes debe abrir @{bot} y pulsar /start.",
    "adm.err.self": "⚠️ No puedes cambiar tu propio rol.",
    "adm.err.owner": "⚠️ Esa persona ya tiene todos los permisos (propietario o superadministrador).",
    "adm.err.banned": "⚠️ Esa persona está bloqueada en este bot.",
    "adm.err.already": "ℹ️ {user} ya es admin.",
    "adm.err.not_admin": "ℹ️ {user} no es admin.",
    "adm.dm.promoted": (
        "🔰 <b>Ahora eres admin de @{bot}</b>\n\n"
        "Ya puedes gestionar su red de distribución. Pulsa /start para ver el panel."
    ),
    "adm.dm.demoted": "ℹ️ Ya no eres admin de @{bot}.",
    # --- Zona horaria ------------------------------------------------------------------------------
    "tz.title": "🗺 <b>Zona horaria</b>",
    "tz.intro.admin": "Con ella se calculan los horarios y las fechas de envío de la red.",
    "tz.intro.user": "Las fechas y las horas se muestran en tu zona horaria.",
    "tz.intro.onboarding": (
        "👋 <b>¡Te damos la bienvenida a tu bot!</b>\n"
        "Ya funciona; déjalo listo en un minuto:\n"
        "1. 🗺 Elige la zona horaria.\n"
        "2. 🧭 Responde unas preguntas rápidas.\n"
        "3. ➕ Añade tus canales y 📝 crea tu primer mensaje.\n\n"
        "🗺 <b>Zona horaria</b>\n"
        "Con ella se calculan las horas de envío de tu red. Telegram no la comparte con los bots, así que se "
        "pregunta solo una vez (luego se puede cambiar en ⚙️ Ajustes)."
    ),
    "tz.intro.welcome": (
        "👋 <b>¡Hola!</b> Antes de empezar, elige tu <b>zona horaria</b>: así verás las fechas y las horas en tu "
        "hora local.\n"
        "   └ Solo se pregunta una vez."
    ),
    "tz.welcome": "👋 <b>¡Te damos la bienvenida a tu bot!</b> Ya funciona; déjalo listo en un minuto.",
    "tz.current": "🕐 Actual: <b>{zone}</b> ({offset}) · {time}",
    "tz.current.default": "🕐 Actual: <b>{zone}</b> ({offset}) · {time}\n   └ Es la zona de la red.",
    "tz.pick": "👇 Elige tu <b>continente</b> y luego tu <b>país</b>.",
    "tz.cont.ame": "🌎 América",
    "tz.cont.nam": "🌎 América del Norte",
    "tz.cont.cam": "🌎 Centroamérica y Caribe",
    "tz.cont.sam": "🌎 América del Sur",
    "tz.cont.eur": "🌍 Europa",
    "tz.cont.asi": "🌏 Asia",
    "tz.cont.afr": "🌍 África",
    "tz.cont.oce": "🌏 Oceanía",
    "tz.btn.write": "✍️ Escribir zona",
    "tz.btn.photo_set": "🖼 Poner imagen",
    "tz.btn.photo_change": "🖼 Cambiar imagen",
    "tz.btn.photo_del": "🗑 Quitar imagen",
    "tz.photo.prompt": "🖼 Envía la <b>foto</b> que se verá al abrir este menú, en todos los bots.",
    "tz.photo.invalid": "⚠️ Eso no es una foto. Envíala como foto, no como archivo.",
    "tz.photo.saved": "✅ Imagen guardada.",
    "tz.photo.deleted": "🗑 Imagen quitada.",
    "tz.regions": "👇 Elige tu región:",
    "tz.countries": "👇 Elige tu país:",
    "tz.zones": "👇 Elige tu zona horaria:",
    "tz.write.prompt": (
        "✍️ <b>Escribir zona horaria</b>\n\n"
        "Envía el nombre de tu zona en formato IANA, por ejemplo <code>Europe/Madrid</code> o "
        "<code>America/Mexico_City</code>.\n\n"
        "📋 Lista completa: https://en.wikipedia.org/wiki/List_of_tz_database_time_zones"
    ),
    "tz.write.invalid": "⚠️ Esa zona horaria no es válida. Usa el formato <code>Continente/Ciudad</code>.",
    "tz.saved.admin": "✅ Zona horaria de la red: <b>{zone}</b>. Los próximos envíos se han recalculado.",
    "tz.saved.first": "✅ Zona horaria de la red: <b>{zone}</b>.",
    "tz.saved.known": "🗺 Zona horaria de tu red: <b>{zone}</b>, la que ya elegiste. Se cambia en ⚙️ Ajustes.",
    "tz.saved.user": "✅ Tu zona horaria es ahora <b>{zone}</b>.",
    "tz.saved.welcome": "✅ Tu zona horaria: <b>{zone}</b>. Puedes cambiarla en ⚙️ Ajustes.",
    # --- Estadísticas y actividad ------------------------------------------------------------------
    "stats.title": "📊 <b>Estadísticas</b> · {period}",
    "stats.period.0": "últimas 24 h",
    "stats.period.1": "últimos 7 días",
    "stats.period.2": "últimos 30 días",
    "stats.runs": "📤 Envíos: <b>{n}</b>",
    "stats.sent": "✅ Entregados: <b>{n}</b>",
    "stats.failed": "❌ Fallidos: <b>{n}</b>",
    "stats.skipped": "🛡 Omitidos por anti-spam: <b>{n}</b>",
    "stats.reach": "👁 Alcance: <b>{n}</b>",
    "stats.hint.reach": "   └ Miembros de los chats que recibieron los mensajes.",
    "stats.chats": "📣 Chats: {n} (🏠 {own} · 🤝 {ext}) · 👤 {members}",
    "stats.paused": "⏸ Pausados: {n}",
    "stats.no_rights": "⚠️ Sin permisos: {n}",
    "stats.pending": "⏳ Pendientes: {n}",
    "stats.top": "🏆 <b>Mensajes más enviados</b>",
    "stats.top.item": "{i}. {name} — {n}",
    "stats.btn.0": "24 h",
    "stats.btn.1": "7 días",
    "stats.btn.2": "30 días",
    "stats.btn.activity": "📜 Actividad",
    "stats.act.title": "📜 <b>Actividad</b>",
    "stats.act.empty": (
        "Todavía no hay actividad. Aquí aparece lo que pasa en los canales de la red: los que se unen, se pausan, "
        "pierden permisos o salen."
    ),
}
