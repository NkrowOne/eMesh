# Vídeo promocional de eMesh (1:1)

Un vídeo cuadrado (1080×1080, 30 fps, unos 70 s) con las mejores funciones de eMesh: a la izquierda el titular de
cada escena y a la derecha un iPhone burdeos con Telegram, donde se ve el bot **de verdad** (las pantallas salen del
propio bot, no están dibujadas a mano).

## Renderizarlo en tu PC

Hace falta [Node.js](https://nodejs.org) y [ffmpeg](https://ffmpeg.org) (en Windows: `winget install ffmpeg`).

```bash
cd tools/promo_video
npm install playwright
npx playwright install chromium
node render.js es
```

El vídeo queda en `tools/promo_video/out/emesh_promo_es.mp4`.

Opciones (variables de entorno):

| Variable | Qué hace | Por defecto |
|---|---|---|
| `SPEED` | Velocidad de la historia. `1` ≈ 93 s, `1.3` ≈ 70 s, `1.5` ≈ 62 s | `1.3` |
| `SCALE` | Nitidez: se dibuja a `1080 × SCALE` y se reduce. `2` es más nítido y más lento | `1.5` |
| `STILLS` | Guarda además un fotograma cada N segundos en `out/stills/` | no |
| `FFMPEG` | Ruta de ffmpeg si no está en el PATH | `ffmpeg` |

En PowerShell: `$env:SPEED="1.5"; node render.js es`.

El texto usa la fuente Inter si está instalada (si no, la del sistema).

## El guion

| # | Titular | Qué se ve en el teléfono |
|---|---|---|
| Inicio | **Publica en todos tus canales a la vez** | Portada con el logo |
| 1 | **Toda tu red, de un vistazo** | `/start`: el inicio con la imagen, los números de la red y el menú |
| 2 | **Añade canales en dos toques** | ➕ Añadir canal → elegir canal → permisos → «✅ añadido a la red» |
| 3 | **Escribe una vez, publica en todos** | 📝 Mensajes → un mensaje → 🚀 Enviar ahora → el mensaje publicado en un canal, con botones de colores |
| 4 | **Cada mensaje, a su hora** | ⏰ Horarios y 🛡 Anti-spam |
| 5 | **Tus asociados suman sus canales** | Llega una solicitud → ✅ Aceptar → 📣 la lista de canales con su estado |
| 6 | **Mide cada envío** | 📊 Estadísticas del día |
| Final | **Crea tu red en un minuto** | Portada con el logo y la llamada a la acción |

Cambiar los textos, los canales de ejemplo o el orden: están arriba de `capture.py` (`TEXT`) y en `test_guion`.
Después hay que volver a grabar el guion (necesita Python y `pip install -r requirements-dev.txt`):

```bash
tools/promo_video/make.sh          # graba el guion y renderiza
```

o, paso a paso: `python -m pytest -p tests.conftest tools/promo_video/capture.py -q -n 0 -p no:cacheprovider` y luego
`node tools/promo_video/render.js`.

## Archivos

- `capture.py`: graba el guion (`guion_es.json`) usando el bot contra el Telegram falso de los tests.
- `guion_es.json`: el guion grabado (escenas, rótulos, mensajes, botones y toques). Con él basta para renderizar.
- `player.html`: el reproductor: el escenario 1:1, el iPhone y Telegram en tema oscuro.
- `render.js`: reproduce el guion fotograma a fotograma (Chromium) y lo codifica con ffmpeg.
- `banner.jpg`: la imagen de eMesh que se ve en el bot, en la portada y en la esquina.

El color del iPhone está en `player.html` (`#device`, un degradado de burdeos `#7a1f3f` a morado oscuro `#23092a`).
