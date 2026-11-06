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
    "setup.recommended": "{label} (recomendado)",
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
        "⏰ <b>¿Cada cuánto recibe un mensaje cada canal?</b>\n"
        "Cada canal recibe un mensaje en cada turno de su frecuencia; los mensajes en rotación se van turnando.\n"
        "   └ Los intervalos van de 08:00 a 22:00. Luego se puede afinar en ⏰ Frecuencias."
    ),
    "setup.freq.every": "Cada {t}",
    "setup.freq.daily": "1 al día (12:00)",
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
