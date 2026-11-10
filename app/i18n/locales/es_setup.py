"""Textos del asistente de configuración de un bot nuevo (módulo de inicio)."""

STRINGS = {
    "setup.intro": (
        "🧭 <b>Asistente de configuración</b>\n"
        "Unas preguntas rápidas para dejar la red lista. Cada respuesta se guarda al momento y todo se puede cambiar "
        "luego en ⚙️ Ajustes."
    ),
    # --- 1. Canales externos -----------------------------------------------------------------------
    "setup.q.1": (
        "🤝 <b>¿Aceptas canales de otras personas?</b>\n"
        "Podrán añadir el bot a sus canales y grupos para recibir los mensajes de la red.\n"
        "   └ Con aprobación, cada canal nuevo llega como solicitud a los admins."
    ),
    "setup.join.approval": "✅ Sí, con mi aprobación",
    "setup.join.auto": "⚡ Sí, entran solos",
    "setup.join.closed": "🔒 No, solo los míos",
    # --- 2. Pausas de los socios -------------------------------------------------------------------
    "setup.q.2": (
        "⏸ <b>¿Pueden pausar la distribución en sus canales?</b>\n"
        "Cada socio la pausa desde su panel, como mucho el tiempo que elijas.\n"
        "   └ Tú siempre ves quién pausa y puedes reanudarlo."
    ),
    "setup.pause.upto": "Hasta {t}",
    "setup.pause.no": "🚫 No pueden pausar",
    # --- 3. Frecuencia global ----------------------------------------------------------------------
    "setup.q.3": (
        "⏰ <b>¿A qué horas recibe un mensaje cada canal?</b>\n"
        "Toca una hora para marcarla o quitarla, o elige una opción rápida. En cada hora marcada, cada canal recibe "
        "un mensaje; los mensajes en rotación se van turnando."
    ),
    "setup.freq.now": "🕐 <b>{n} al día</b>: {times}",
    "setup.freq.days": "📅 Días: {days}",
    "setup.freq.tz": "   └ Hora de {tz}. Luego se puede afinar en ⏰ Frecuencias.",
    "setup.freq.n": "{n} al día",
    "setup.freq.every": "Cada {t}",
    "setup.freq.hourly": "Cada hora",
    "setup.days.0": "Todos",
    "setup.days.1": "L-V",
    "setup.days.2": "S-D",
    "setup.freq.write": "✏️ Escribir otras horas (9:30…)",
    "setup.freq.need_hour": "⚠️ Deja al menos una hora marcada.",
    "setup.freq.ask": (
        "✏️ <b>Escribe las horas</b>\n\n"
        "Separadas por comas, hasta 24 y con los minutos que quieras. Por ejemplo: <code>9:30, 14, 21:15</code>.\n\n"
        "🕐 Ahora: <b>{current}</b>"
    ),
    "setup.freq.saved": "✅ Guardado: {freq}",
    "setup.btn.next": "Continuar ➡️",
    # --- 4. Borrado automático ---------------------------------------------------------------------
    "setup.q.4": (
        "🗑 <b>¿Cuánto tiempo siguen publicados los mensajes?</b>\n"
        "Pasado ese tiempo se borran solos de los canales.\n"
        "   └ Es lo que toman los mensajes nuevos; cada uno se puede cambiar en sus ⚙️ Opciones."
    ),
    "setup.delete.never": "♾ No se borran",
    "setup.keep": "Mantener: {v}",
    "setup.btn.skip": "⏭ Saltar el asistente",
    # --- 5. Resumen --------------------------------------------------------------------------------
    "setup.done": "✅ <b>Todo listo</b>\nAsí queda la red:",
    "setup.sum.pause": "⏸ Pausas de los socios: {v}",
    "setup.sum.pause.upto": "hasta {t}",
    "setup.sum.pause.free": "sin límite",
    "setup.sum.pause.no": "no pueden pausar",
    "setup.sum.delete": "🗑 Borrado automático: {v}",
    "setup.sum.after": "al cabo de {t}",
    "setup.sum.never": "no se borran",
    "setup.done.next": (
        "👇 Ahora añade el bot a tus canales y grupos y crea un mensaje.\n"
        "   └ Todo se puede cambiar en ⚙️ Ajustes, ⏰ Frecuencias y 📝 Mensajes."
    ),
    "setup.btn.first_post": "📝 Crear el primer mensaje",
    "setup.btn.new_post": "📝 Crear un mensaje",
    "setup.btn.home": "🏠 Ir al inicio",
}
