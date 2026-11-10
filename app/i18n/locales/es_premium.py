STRINGS = {
    # --- 💎 post_premium ---
    "pm.title": "💎 <b>Emojis premium en canales</b> · {name}",
    "pm.intro": (
        "Telegram no deja a los bots poner emojis premium en los canales. Para que salgan, los canales reciben el "
        "mensaje <b>reenviado</b> desde tu canal almacén (arriba se ve «Reenviado de…»).\n"
        "   └ Los grupos lo reciben normal, con sus emojis premium."
    ),
    "pm.vault": "🗄 Canal almacén: <b>{name}</b>",
    "pm.vault.none": "🗄 Canal almacén: — (será el canal al que reenvíes el mensaje)",
    "pm.vault.gone": "🗄 Canal almacén: ⚠️ <b>{name}</b> ya no está en la red",
    "pm.st.none": "ℹ️ Este mensaje no tiene emojis premium: se envía normal a todos.",
    "pm.st.ready": "📌 Estado: ✅ Listo: los canales lo reciben con emojis premium.",
    "pm.st.todo": "📌 Estado: ⚠️ Falta prepararlo: los canales lo reciben con emojis normales.",
    "pm.st.stale": "📌 Estado: ⚠️ El mensaje ha cambiado: prepáralo otra vez (mientras, los canales lo reciben con "
                   "emojis normales).",
    "pm.live_hint": "🔄 Pulsa «Actualizar publicados» en el mensaje para cambiar los ya enviados.",
    "pm.b.prepare": "📨 Preparar para reenviar",
    "pm.b.add": "➕ Añadir canal ↗",
    "pm.b.change": "🗄 Cambiar canal almacén",
    "pm.b.change_ok": "🗄 Sí, cambiarlo",
    "pm.b.remove": "✖️ Quitar la versión premium",
    "pm.b.open": "💎 Ver",
    "pm.change.ask": "🗄 <b>{name}</b> dejará de ser tu canal almacén y volverá a recibir los mensajes de la red.\n"
                     "El siguiente canal al que reenvíes un mensaje preparado será el nuevo almacén.",
    "pm.change.done": "✅ Hecho. Reenvía el próximo mensaje preparado a tu nuevo canal almacén.",
    "pm.removed": "✅ Quitada: los canales recibirán el mensaje normal.",
    "pm.forward": "📨 <b>Ahora reenvía el mensaje de arriba</b> a tu canal almacén <b>{name}</b>. Se detectará solo.",
    "pm.forward.first": (
        "📨 <b>Ahora reenvía el mensaje de arriba</b> a un canal tuyo de la red (mejor uno privado creado para "
        "esto, con el bot de admin). Ese canal será tu <b>canal almacén</b>: no recibirá los mensajes de la red."
    ),
    "pm.err.no_premium": "⚠️ Telegram ha quitado los emojis premium: el dueño de este bot no tiene Telegram Premium.",
    # --- DMs after the forward ---
    "pm.dm.linked": "✅ <b>{name}</b>: listo. Los canales lo recibirán con emojis premium, reenviado desde 🗄 "
                    "<b>{vault}</b>.",
    "pm.dm.new_vault": "🗄 <b>{vault}</b> es ahora tu canal almacén: no recibe los mensajes de la red.",
    "pm.dm.not_own": "⚠️ <b>{name}</b>: ese chat no sirve como canal almacén. Tiene que ser un canal tuyo de la red. "
                     "Reenvíalo a otro.",
    "pm.dm.other_vault": "⚠️ <b>{name}</b>: tu canal almacén es <b>{vault}</b>. Reenvía el mensaje allí, o cámbialo "
                         "en 💎 Premium en canales.",
    "pm.dm.changed": "⚠️ <b>{name}</b> ha cambiado o ya no existe. Prepáralo otra vez en 💎 Premium en canales.",
    "pm.dm.no_emoji": "⚠️ <b>{name}</b>: los emojis premium no han llegado al canal almacén. Reenvíalo sin ocultar "
                      "el remitente.",
    "pm.dm.no_buttons": "⚠️ <b>{name}</b>: los botones no han llegado al canal almacén y no se han podido poner. Los "
                        "canales siguen recibiendo el mensaje normal.",
    # --- other screens ---
    "po.d.premium.ready": "💎 Premium en canales: ✅ listo",
    "po.d.premium.todo": "💎 Premium en canales: ⚠️ falta prepararlo",
    "po.b.premium": "💎 Premium en canales",
    "ch.st.vault": "🗄 Canal almacén: no recibe mensajes",
}
