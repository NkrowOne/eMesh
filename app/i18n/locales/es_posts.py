STRINGS = {
    # --- list ---
    "po.list.title": "📝 <b>Mensajes</b>",
    "po.list.legend": "🔁 rotación · ⏰ horario propio · 📆 una vez · ✋ manual",
    "po.list.item": "{n}. {status} {mode} <b>{name}</b> · {kind}\n   └🎯 {targets} · {extra}",
    "po.list.runs": "📤 {sends}",
    "po.list.next": "📅 {date}",
    "po.list.empty": "📭 Todavía no hay mensajes. Crea el primero con ➕ Nuevo mensaje.",
    "po.btn.new": "➕ Nuevo mensaje",
    "po.btn.defaults": "⚙️ Opciones por defecto",
    "po.limit": "🔒 Esta red ya tiene el máximo de mensajes ({max}). Elimina alguno para crear otro.",
    # --- counts ---
    "po.unit.chats": "{n} chats",
    "po.unit.chats.1": "{n} chat",
    "po.unit.times": "{n} veces",
    "po.unit.times.1": "{n} vez",
    "po.unit.deliveries": "{n} entregas",
    "po.unit.deliveries.1": "{n} entrega",
    "po.unit.sends": "{n} envíos",
    "po.unit.sends.1": "{n} envío",
    "po.unit.buttons": "{n} botones",
    "po.unit.buttons.1": "{n} botón",
    "po.unit.copies": "{n} copias",
    "po.unit.copies.1": "{n} copia",
    # --- targets ---
    "po.tg.all": "🌐 Todos",
    "po.tg.own": "🏠 Solo propios",
    "po.tg.ext": "🤝 Solo externos",
    "po.tg.group": "🗂 {name} ({n})",
    "po.tgs.all": "🌐 Todos",
    "po.tgs.own": "🏠 Propios",
    "po.tgs.ext": "🤝 Externos",
    "po.tgl.all": "Todos",
    "po.tgl.own": "Propios",
    "po.tgl.ext": "Externos",
    "po.tg.none": "⚠️ nadie",
    "po.tg.hint": "Elige uno o varios destinos: se suman.",
    "po.tg.count": "👥 Lo recibirán: <b>{chats}</b> · 👤 {members}",
    "po.tg.count_hint": "   └ Solo cuentan los chats que reciben mensajes ahora (aprobados, con permisos y sin pausa).",
    "po.tg.need_one": "⚠️ Elige al menos un destino.",
    "po.targets.title": "🎯 <b>Destino</b> · {name}",
    # --- create wizard ---
    "po.w.content": (
        "📝 <b>Nuevo mensaje</b> · 1/4\n\n"
        "Envía el mensaje tal como quieres que se publique: texto, foto, vídeo, GIF, archivo, audio o nota de voz, "
        "con su formato (<b>negrita</b>, <i>cursiva</i>, enlaces, emojis). También puedes reenviarlo desde un canal."
    ),
    "po.w.buttons": "🔘 <b>Botones</b> · 2/4\n\nEnvía los botones que irán debajo del mensaje.\n\n{help}",
    "po.w.no_buttons": "⏭ Sin botones",
    "po.w.targets": "🎯 <b>¿A quién se envía?</b> · 3/4",
    "po.w.continue": "✅ Continuar",
    "po.w.when": (
        "⏰ <b>¿Cuándo se envía?</b> · 4/4\n\n"
        "🔁 <b>En rotación</b> (recomendado)\n"
        "   └ Se turna con los demás mensajes según la frecuencia de cada canal (global: {freq}).\n"
        "⏰ <b>Con su propio horario</b>\n"
        "   └ Tiene su propia frecuencia; en cada turno se envía a todos sus chats.\n"
        "📆 <b>Una sola vez</b>\n"
        "   └ En la fecha y hora que elijas; después queda terminado.\n"
        "✋ <b>Solo cuando lo envíes</b>\n"
        "   └ Únicamente con 🚀 Enviar ahora."
    ),
    "po.w.date": "📆 <b>Una sola vez</b> · 4/4\n\n{ask}",
    "po.help.buttons": (
        "Un botón por línea: <code>Nombre - https://enlace</code>\n"
        "• En la misma fila: sepáralos con <code>&amp;&amp;</code>\n"
        "• Color: añade 🔵, 🟢 o 🔴 al final\n"
        "• Botón que copia un texto: <code>Código - copiar: PROMO10</code>\n"
        "• Máximo 30 botones, 8 por fila\n\n"
        "Ejemplo:\n"
        "<pre>Web - https://example.com 🟢\n"
        "Canal - @micanal &amp;&amp; Grupo - t.me/migrupo\n"
        "Código - copiar: PROMO10 🔵</pre>"
    ),
    "po.mode.rotation": "🔁 En rotación",
    "po.mode.rotation_rec": "🔁 En rotación (recomendado)",
    "po.mode.own": "⏰ Con su propio horario",
    "po.mode.once": "📆 Una sola vez",
    "po.mode.manual": "✋ Solo cuando lo envíe yo",
    "po.date.ask": (
        "Envía la fecha y la hora: <code>25/12/2026 20:00</code>, <code>25/12 20:00</code> o solo la hora "
        "(<code>20:00</code>: hoy, o mañana si ya ha pasado).\n🗺 Zona horaria: {tz}"
    ),
    "po.saved": "✅ Mensaje guardado",
    "po.err.use_buttons": "👇 Usa los botones de abajo.",
    "po.err.text_only": "⚠️ Envíalo como texto.",
    # --- detail ---
    "po.d.title": "📝 <b>{name}</b>",
    "po.d.status": "📌 Estado: {value}",
    "po.st.active": "▶️ Activo",
    "po.st.paused": "⏸ Pausado",
    "po.st.done": "✅ Terminado",
    "po.d.kind": "🧩 Tipo: {kind} · {buttons}",
    "po.d.buttons": "🔘 {buttons}",
    "po.d.no_buttons": "sin botones",
    "po.d.targets": "🎯 Destino: {targets} → {chats} (👤 {members})",
    "po.d.no_targets": "🎯 Destino: ⚠️ ninguno, no se envía a nadie",
    "po.d.mode": "⏰ Envío: {value}",
    "po.dm.rotation": "🔁 En rotación",
    "po.dm.own": "⏰ Horario propio · {freq}",
    "po.dm.once": "📆 Una sola vez · {date}",
    "po.dm.manual": "✋ Manual",
    "po.dh.rotation": "   └ Cada canal lo recibe por turnos según su frecuencia.",
    "po.dh.own": "   └ En cada turno de su horario se envía a todos sus chats.",
    "po.dh.once": "   └ Se envía una vez y después queda terminado.",
    "po.dh.manual": "   └ Solo se envía al pulsar 🚀 Enviar ahora.",
    "po.d.next": "📅 Próximo envío: <b>{date}</b>",
    "po.d.campaign": "📆 Campaña: {value}",
    "po.camp.both": "del {start} al {end}",
    "po.camp.from": "desde el {start}",
    "po.camp.to": "hasta el {end}",
    "po.d.sent": "📤 Enviado: {times} · {deliveries} · último {last}",
    "po.d.never": "📤 Todavía no se ha enviado.",
    "po.d.live": "🟢 Publicado ahora en: <b>{chats}</b>",
    "po.d.opts": "⚙️ <b>Opciones</b>",
    "po.b.preview": "👁 Vista previa",
    "po.b.send": "🚀 Enviar ahora",
    "po.b.content": "✏️ Contenido",
    "po.b.buttons": "🔘 Botones",
    "po.b.targets": "🎯 Destino",
    "po.b.sched": "⏰ Programación",
    "po.b.opts": "⚙️ Opciones",
    "po.b.dup": "🧬 Duplicar",
    "po.b.update": "🔄 Actualizar publicados ({n})",
    "po.b.retire": "🔚 Retirar ({n})",
    "po.b.pause": "⏸ Pausar",
    "po.b.play": "▶️ Activar",
    "po.b.delete": "🗑 Eliminar",
    "po.no": "❌ No",
    # --- detail actions ---
    "po.preview.failed": "⚠️ No se ha podido enviar la vista previa. Inténtalo de nuevo.",
    "po.busy": "⏳ Este mensaje se está enviando ahora mismo. Espera a que termine.",
    "po.send.nobody": "⚠️ Ahora mismo ningún chat puede recibirlo. Revisa su 🎯 Destino.",
    "po.send.paused": "⏸ La distribución está pausada: no se envía nada. Reanúdala en el inicio con ▶️ Reanudar todo.",
    "po.send.confirm": (
        "🚀 <b>{name}</b>\n\nSe enviará ahora a <b>{chats}</b> (👤 {members}).\n"
        "   └ Se respetan los límites del 🛡 anti-spam de la red."
    ),
    "po.send.yes": "✅ Enviar",
    "po.send.started": "🚀 Enviando…",
    "po.retire.confirm": "🔚 Se borrará <b>{name}</b> de donde está publicado ahora: <b>{chats}</b>.",
    "po.retire.yes": "🔚 Retirar",
    "po.retire.started": "🔚 Retirando…",
    "po.update.confirm": (
        "🔄 Se aplicarán el texto y los botones actuales de <b>{name}</b> a lo ya publicado: <b>{copies}</b>.\n"
        "   └ La foto, el vídeo o el archivo no cambian."
    ),
    "po.update.yes": "🔄 Actualizar",
    "po.update.started": "🔄 Actualizando…",
    "po.nothing_live": "ℹ️ Ahora mismo no está publicado en ningún chat.",
    "po.dup.name": "{name} (copia)",
    "po.dup.done": "🧬 Copia creada en pausa: revísala y actívala.",
    "po.del.confirm": "🗑 ¿Eliminar <b>{name}</b>?",
    "po.del.live": (
        "🟢 Ahora está publicado en <b>{chats}</b>:\n"
        "• <b>Eliminar y retirar</b>: también se borra de esos chats.\n"
        "• <b>Eliminar solo el mensaje</b>: las copias publicadas se quedan (y se borran a su hora si tienen "
        "borrado automático)."
    ),
    "po.del.all": "🗑 Eliminar y retirar lo publicado ({n})",
    "po.del.only": "🗑 Eliminar solo el mensaje",
    "po.del.yes": "🗑 Sí, eliminar",
    "po.del.done": "🗑 Mensaje eliminado",
    "po.del.retiring": "🗑 Eliminando: se está retirando lo publicado…",
    "po.paused": "⏸ Mensaje pausado",
    "po.activated": "▶️ Mensaje activado",
    "po.ended": "📆 Su campaña ya terminó: cambia la fecha de fin en ⏰ Programación para activarlo.",
    "po.activate.date": "📆 <b>Nueva fecha</b> · {name}\n\nPara volver a enviarlo hace falta una fecha futura.\n{ask}",
    # --- content ---
    "po.c.title": "✏️ <b>Contenido</b> · {name}",
    "po.c.name": "🏷 Nombre interno: {name}",
    "po.c.name_hint": "   └ Solo lo ve la administración, para reconocerlo en la lista.",
    "po.c.kind": "🧩 Tipo: {kind}",
    "po.c.text": "📝 Texto: <i>{text}</i>",
    "po.c.no_text": "📝 Texto: ✖️",
    "po.c.b.change": "✏️ Cambiar el mensaje",
    "po.c.b.text": "📝 Cambiar solo el texto",
    "po.c.b.name": "🏷 Nombre interno",
    "po.c.b.nomedia": "🖼 Quitar la media",
    "po.c.ask_content": (
        "✏️ <b>Cambiar el mensaje</b> · {name}\n\n"
        "Envía el mensaje nuevo tal como quieres que se publique (texto, o media con su texto). Sustituye al actual; "
        "los botones y las opciones se mantienen."
    ),
    "po.c.ask_text": (
        "📝 <b>Cambiar solo el texto</b> · {name}\n\nEnvía el texto nuevo con su formato (máximo 4096 caracteres)."
    ),
    "po.c.ask_caption": (
        "📝 <b>Cambiar solo el texto</b> · {name}\n\n"
        "Envía el texto nuevo con su formato. La media se mantiene; con media, el texto puede tener como máximo "
        "1024 caracteres."
    ),
    "po.c.ask_name": "🏷 <b>Nombre interno</b>\n\nActual: {name}\nEnvía el nombre nuevo (máximo 64 caracteres).",
    "po.c.nomedia.confirm": "🖼 ¿Quitar la media de <b>{name}</b>? Quedará solo el texto.",
    "po.c.nomedia.yes": "🖼 Quitar la media",
    "po.c.nomedia.no_text": "⚠️ Sin la media quedaría vacío: primero añade un texto con 📝 Cambiar solo el texto.",
    "po.c.nomedia.done": "🖼 Media quitada",
    "po.c.live_hint": "🔄 Pulsa Actualizar publicados para aplicarlo a los ya enviados.",
    # --- schedule ---
    "po.s.title": "⏰ <b>Programación</b> · {name}",
    "po.s.modes": (
        "🔁 <b>En rotación</b>\n"
        "   └ Se turna con los demás mensajes según la frecuencia de cada canal (global: {freq}).\n"
        "⏰ <b>Con su propio horario</b>\n"
        "   └ En cada turno de su horario se envía a todos sus chats.\n"
        "📆 <b>Una sola vez</b>\n"
        "   └ En la fecha elegida; después queda terminado.\n"
        "✋ <b>Solo cuando lo envíe yo</b>\n"
        "   └ Únicamente con 🚀 Enviar ahora."
    ),
    "po.s.campaign": "📆 Campaña: {value}",
    "po.s.no_campaign": "sin fechas",
    "po.s.campaign_hint": (
        "   └ Opcional. Fuera de esas fechas no se envía en rotación ni con su horario; pasado el último día "
        "queda terminado."
    ),
    "po.s.b.own": "⏰ Horario propio: {freq}",
    "po.s.b.date": "📆 Fecha: {date}",
    "po.s.b.from": "📆 Desde: {date}",
    "po.s.b.to": "📆 Hasta: {date}",
    "po.s.ask_date": "📆 <b>Fecha del envío</b> · {name}\n\n{ask}",
    "po.s.ask_start": (
        "📆 <b>Inicio de la campaña</b> · {name}\n\nActual: {current}\n"
        "Envía el primer día en que se envía: <code>dd/mm/aaaa</code>. <code>0</code> quita la fecha."
    ),
    "po.s.ask_end": (
        "📆 <b>Fin de la campaña</b> · {name}\n\nActual: {current}\n"
        "Envía el último día en que se envía: <code>dd/mm/aaaa</code>. <code>0</code> quita la fecha."
    ),
    "po.s.err.order": "⚠️ El fin de la campaña no puede ser anterior a su inicio.",
    # --- options ---
    "po.opts.title": "⚙️ <b>Opciones</b> · {name}",
    "po.defaults.title": (
        "⚙️ <b>Opciones por defecto</b>\nSe aplican a los mensajes nuevos; los que ya existen no cambian."
    ),
    "po.o.pin": "📌 Fijar: {v}",
    "po.o.silent": "🔕 Sin sonido: {v}",
    "po.o.protect": "🛡 Proteger contenido: {v}",
    "po.o.link_preview": "🔗 Vista previa de enlaces: {v}",
    "po.o.caption_above": "🔼 Texto encima de la media: {v}",
    "po.o.spoiler": "🫣 Spoiler: {v}",
    "po.o.delete_previous": "♻️ Borrar su envío anterior: {v}",
    "po.o.delete_after": "🗑 Borrado automático: {v}",
    "po.ob.pin": "📌 Fijar",
    "po.ob.silent": "🔕 Sin sonido",
    "po.ob.protect": "🛡 Proteger contenido",
    "po.ob.link_preview": "🔗 Vista previa de enlaces",
    "po.ob.caption_above": "🔼 Texto encima de la media",
    "po.ob.spoiler": "🫣 Spoiler",
    "po.ob.delete_previous": "♻️ Borrar su envío anterior",
    "po.oh.pin": "   └ Se fija en el chat sin avisar a los miembros.",
    "po.oh.silent": "   └ Llega sin sonido de notificación.",
    "po.oh.protect": "   └ No se puede reenviar ni guardar.",
    "po.oh.link_preview": "   └ Muestra la vista previa del primer enlace del texto.",
    "po.oh.caption_above": "   └ El texto aparece encima de la foto, el vídeo o el GIF.",
    "po.oh.spoiler": "   └ La media se ve borrosa hasta que se toca.",
    "po.oh.delete_previous": "   └ Al enviarlo de nuevo a un chat, se borra la copia anterior de ese chat.",
    "po.oh.delete_after": (
        "   └ Cada copia se borra sola pasado ese tiempo (máximo 48 h: Telegram no deja borrar mensajes más antiguos)."
    ),
    "po.ad.never": "✖️ nunca",
    "po.ad.after": "a las {t} de enviarse",
    "po.ad.b.never": "Nunca",
    "po.ad.b.other": "✏️ Otro",
    "po.ad.ask": (
        "🗑 <b>Borrado automático</b>\n\n"
        "Envía tras cuánto tiempo se borra cada copia, entre 15 min y 48 h: <code>45 min</code>, <code>2 h</code>, "
        "<code>1 h 30 min</code>, <code>36 h</code>. <code>0</code> = nunca."
    ),
    "po.err.duration": (
        "⚠️ No se entiende. Escribe el tiempo así: <code>45 min</code>, <code>2 h</code> o <code>1 h 30 min</code>."
    ),
    "po.err.duration_range": "⚠️ Elige entre 15 minutos y 48 horas.",
    # --- buttons editor (post_buttons.py) ---
    "pb.title": "🔘 <b>Botones</b> · {name}",
    "pb.hint": "Toca un botón para cambiarlo, moverlo o quitarlo. Así se ven debajo del mensaje 👇",
    "pb.none": "Todavía no tiene botones. Añade uno con ➕ o escríbelos todos de una vez.",
    "pb.count": "🔘 {n} de {max} botones",
    "pb.live_hint": "🔄 Los cambios llegan a lo ya publicado con 🔄 Actualizar publicados, en el mensaje.",
    "pb.b.add": "➕ Añadir botón",
    "pb.b.bulk": "✍️ Escribirlos todos",
    "pb.b.clear": "🗑 Quitar todos",
    "pb.b.preview": "👁 Vista previa",
    "pb.e.title": "🔘 <b>Botón</b> · {name}",
    "pb.e.name": "🏷 Nombre: {v}",
    "pb.e.url": "🔗 Enlace: {v}",
    "pb.e.copy": "📋 Copia el texto: <code>{v}</code>",
    "pb.e.color": "🎨 Color: {v}",
    "pb.e.pos": "📍 Fila {row} · posición {col}",
    "pb.e.hint": "   └ ⬅️ ➡️ lo mueven dentro de su fila; ⬆️ ⬇️ lo pasan a la fila de arriba o de abajo.",
    "pb.e.b.name": "🏷 Nombre",
    "pb.e.b.link": "🔗 Enlace",
    "pb.e.b.del": "🗑 Quitar botón",
    "pb.edge": "↔️ No se puede mover más hacia ese lado.",
    "pb.row_full": "⚠️ Esa fila ya tiene 8 botones.",
    "pb.removed": "🗑 Botón quitado",
    "pb.max": "⚠️ Como máximo {max} botones.",
    "pb.a.name": (
        "➕ <b>Nuevo botón</b> · 1/4\n\n🏷 Envía el nombre del botón: el texto que se leerá en él (máximo 64 "
        "caracteres)."
    ),
    "pb.a.link": "➕ <b>Nuevo botón</b> · 2/4\n\n{ask}",
    "pb.a.color": "➕ <b>Nuevo botón</b> · 3/4\n\n🎨 Elige el color de <b>{name}</b>:",
    "pb.a.place": "➕ <b>Nuevo botón</b> · 4/4\n\n📍 ¿Dónde se coloca <b>{name}</b>?",
    "pb.a.new_row": "⬇️ En una fila nueva",
    "pb.a.same_row": "➡️ Al lado del último",
    "pb.added": "✅ Botón añadido",
    "pb.ask_link": (
        "🔗 Envía adónde lleva:\n"
        "• un enlace: <code>https://…</code>, <code>t.me/…</code> o <code>@usuario</code>\n"
        "• o <code>copiar: TEXTO</code> para un botón que copia ese texto (por ejemplo, un código de descuento)."
    ),
    "pb.ask_name": "🏷 <b>Nombre del botón</b>\n\nActual: {name}\nEnvía el nombre nuevo (máximo 64 caracteres).",
    "pb.ask_link_edit": "🔗 <b>Enlace del botón</b> · {name}\n\nActual: {current}\n\n{ask}",
    "pb.err.name": "⚠️ El nombre debe tener entre 1 y 64 caracteres.",
    "pb.err.link": "⚠️ El enlace no es válido. Usa https://…, t.me/…, @usuario o copiar: TEXTO.",
    "pb.err.copy": "⚠️ El texto a copiar debe tener entre 1 y 256 caracteres.",
    "pb.bulk.title": "✍️ <b>Escribir todos los botones</b> · {name}",
    "pb.bulk.current": "Botones actuales (cópialos, cámbialos y envíalos):\n<pre>{rows}</pre>",
    "pb.bulk.too_long": "ℹ️ Los botones actuales son demasiado largos para mostrarlos aquí.",
    "pb.bulk.replace": "⚠️ Lo que envíes sustituye a todos los botones actuales.",
    "pb.clear.confirm": "🗑 ¿Quitar todos los botones de <b>{name}</b> ({buttons})?",
    "pb.clear.yes": "🗑 Quitar todos",
    "pb.cleared": "🗑 Botones quitados",
}
