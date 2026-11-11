# eMesh — Red de distribución de mensajes para Telegram

Bot para **distribuir mensajes en tus canales y grupos**: escribes los mensajes una vez (texto, foto, vídeo, GIF,
archivo, audio o nota de voz, con **botones de colores**) y el bot los publica solo, con la **frecuencia** que elijas,
en todos tus canales o en los **grupos de canales** que crees. Otras personas pueden unir sus canales a tu red y
**pausarla cuando quieran**: tú recibes el aviso y lo ves en tu panel.

Cada persona puede tener **su propio bot (clon)** con su propia red, y tú, como dueño de la plataforma, los
controlas todos desde el **👑 Panel** del bot principal (e incluso gestionas la red de un clon desde ahí: 🛠 Gestionar).

Hecho con la **última API de Telegram (Bot API 10.3)** y aiogram 3.31. Misma base técnica que eButtons.

## Qué hace

- **📣 Canales y grupos**: el primer botón del inicio, **➕ Añadir canal o grupo**, explica cómo y añade el bot como
  admin con un toque (los permisos salen ya marcados). Los tuyos entran
  al momento; si el bot pierde permisos o lo quitan, recibes un aviso. Si el bot ya era admin en un canal, este
  se añade solo con su siguiente publicación.
- **🤝 Canales externos (socios)**: actívalo y cualquiera puede añadir el bot a su canal o grupo (con o sin tu
  aprobación, con mínimo de miembros). Desde **📣 Mis canales** pueden **pausar** la distribución, elegir
  categorías y salir de la red.
- **👮 Tú mandas sobre los socios**: decides si pueden pausar y cuánto como máximo (por defecto sin límite; o 1, 3
  o 7 días), **puedes reanudar cualquier pausa** y lo ves siempre: cada pausa te llega como
  aviso y aparece en el estado de tu inicio, en **⏸ Pausados** (quién, desde cuándo, hasta cuándo), en la lista de
  canales y en 📜 Actividad.
- **🧭 Asistente al crear un bot**: paso a paso pregunta si aceptas canales de otros, cuánto pueden pausar, cada
  cuánto se publica y cuánto duran los mensajes. Se puede repetir desde ⚙️ Ajustes.
- **📝 Mensajes**: asistente de 5 pasos (mensaje → botones → destino → cuándo → cuánto tiempo sigue publicado).
  **📢 Difusión puntual**: un mensaje que se envía una sola vez, **ahora mismo** o en la fecha que elijas. Vista previa real, 🚀 enviar ahora, 🔄 aplicar cambios a lo ya publicado (corrige una errata
  en todos los canales), 🔚 retirar, 🧬 duplicar.
- **🔘 Botones**: editor visual (toca un botón para cambiarlo, muévelo, cambia su color) o escríbelos todos de golpe:
  `Web - https://ejemplo.com 🟢`, varios en una fila con `&&`, colores 🔵 🟢 🔴 y botones de **copiar texto**
  (`Código - copiar: PROMO10`).
- **🎯 Destinos**: 🌐 Todos, 🏠 Solo propios, 🤝 Solo externos o tus **🗂 grupos de canales** (combinables).
- **⏰ Frecuencias, fáciles siempre**: una pantalla con todas. Global («cada 3 h de 08:00 a 23:00») o propia de cada
  grupo de canales («a las 10:00, 14:00 y 22:00, de lunes a viernes»). Los mensajes en **rotación** se turnan en cada
  canal; también hay mensajes con su propio horario, difusiones puntuales o solo manuales, y **fechas de
  campaña**. Por defecto, cada canal recibe **1 mensaje al día** (a las 12:00).
- **🛡 Anti-spam**: máximo de mensajes al día por chat, separación mínima y «uno a la vez» (borra el anterior).
- **Opciones de cada mensaje**: fijar, sin sonido, proteger contenido, vista previa de enlaces, texto encima del
  multimedia, spoiler (contenido multimedia borroso hasta que se pulsa), borrado automático (de 1 h a 48 h, o nunca)
  y borrar su envío anterior.
- **📊 Estadísticas y 📜 Actividad**: envíos, entregas, fallos, alcance, mensajes más enviados, y el historial de
  todo lo que pasa en la red. Resumen diario e informe de cada envío (opcionales).
- **🤖 Clones**: para publicar, cada uno crea su propio bot en 2 toques (Managed Bots de Telegram) o con un token de
  @BotFather; el bot principal lo explica al empezar. Clonación **abierta, con aprobación o cerrada**, límite de bots
  por persona y límites de chats/mensajes por clon.
- **👑 Panel**: estadísticas de la plataforma, lista de clones con búsqueda, activar/desactivar, aprobar, límites,
  escribir al dueño, actividad, eliminar, **🛠 Gestionar** su red desde el bot principal, aviso a todos los dueños y
  descarga de errores. **🖼 Imagen del bot**: sale arriba del mensaje de inicio y es la foto de perfil del bot
  principal; los clones la llevan también (en el inicio de sus admins y como foto de perfil, salvo los que tienen una
  propia).
- **Límites de Telegram respetados siempre**: ~30 mensajes/segundo, 1/segundo por chat privado, 20/minuto por grupo
  o canal, y reintentos automáticos si Telegram pide esperar (429).
- **🗺 Zona horaria**: por continente y país, con la imagen que elijas para ese menú. Se pregunta **una sola vez**:
  si alguien ya la eligió en eButtons o en eMesh, no se le vuelve a preguntar (la de eButtons manda).
- **Fácil de usar**: cuando el bot te pide un texto, el mensaje sale siempre abajo del todo (el anterior se borra).
- Español 🇪🇸 e inglés 🇬🇧.

## Puesta en marcha

### 1. Prepara el bot en @BotFather
1. `/newbot` → copia el **token**.
2. Para clonar en 2 toques: abre la Mini App de @BotFather → tu bot → **Bot Settings** → activa **Bot Management
   Mode**. (Sin esto, los clones se crean pegando un token.)
3. Si quieres grupos: `/setjoingroups` → *Enable*.

### 2. Despliega

**Railway (lo más fácil)**
1. Nuevo proyecto desde este repositorio.
2. Añade **PostgreSQL** (➕ New → Database → PostgreSQL).
3. En el servicio del bot → **Variables**: `BOT_TOKEN`, `SUPER_ADMIN_IDS` (tu ID), `ENCRYPTION_KEY` (ver
   `.env.example`) y `DATABASE_URL` = `${{Postgres.DATABASE_URL}}`.
4. Deploy. Las tablas se crean solas al arrancar. Deja **1 réplica**.

**Docker (VPS)**
```bash
cp .env.example .env   # rellena BOT_TOKEN, SUPER_ADMIN_IDS y ENCRYPTION_KEY
docker compose up -d --build
```

**Local**
```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # rellénalo
python -m app
```

Para saber tu ID de Telegram: arranca el bot y escribe `/id`.

### 3. Primeros pasos
1. `/start` en tu bot → **➕ Añadir canal** (y grupo). Tus canales entran automáticamente.
2. **📝 Mensajes → ➕ Nuevo mensaje**: envía el mensaje, añade botones, elige a quién y cuándo.
3. **⏰ Frecuencias**: elige cada cuánto recibe un mensaje cada canal (global o por grupo de canales).
4. ¿Quieres socios? **⚙️ Ajustes → 🤝 Canales externos** y comparte el enlace `https://t.me/<tu_bot>?start=join`.

## Variables de entorno

Todas están explicadas en [`.env.example`](.env.example). Obligatorias: `BOT_TOKEN`, `SUPER_ADMIN_IDS`,
`DATABASE_URL` (en producción) y `ENCRYPTION_KEY` (si usas clones). Opcional: `EBUTTONS_DATABASE_URL`, la base de
datos de eButtons si no es la misma que la de eMesh (así nadie elige dos veces su zona horaria).

## Desarrollo

```bash
pip install -r requirements-dev.txt
pytest -q
```

Los tests levantan un **Telegram falso** (`tests/fake_tg.py`) y prueban los flujos completos, incluidos los límites
de velocidad. La arquitectura está en [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

```
app/
  main.py            arranque (python -m app)
  config.py          variables de entorno
  db/                modelos y migraciones (Alembic)
  telegram/          gestor de varios bots, límites de velocidad, FSM
  bot/routers/       pantallas y comandos
  services/          lógica: contenido, frecuencias, destinos, publicar, programar, clones
  i18n/locales/      textos (es / en)
tests/               tests con Telegram falso
```
