# Vídeos promocionales de eMesh (1:1)

Dos vídeos cuadrados (1080×1080, 30 fps) hechos con el bot **de verdad**: las pantallas salen del propio bot (contra
el Telegram falso de los tests), no están dibujadas a mano.

| Vídeo | Qué es | Comando | Sale en |
|---|---|---|---|
| **Spot** | 50 s, montado sobre la música: pantalla en 3D, una animación por función y fotos reales en los mensajes | `node render_spot.js es` | `out/emesh_spot_es.mp4` |
| **Paseo** | Unos 70 s, sin música: el bot paso a paso, con el titular de cada escena | `node render.js es` | `out/emesh_promo_es.mp4` |

## Renderizarlos en tu PC

Hace falta [Node.js](https://nodejs.org) y [ffmpeg](https://ffmpeg.org) (en Windows: `winget install ffmpeg`).

```bash
cd tools/promo_video
npm install playwright
npx playwright install chromium
node render_spot.js es     # el spot con música
node render.js es          # el paseo
```

Opciones (variables de entorno; en PowerShell: `$env:SCALE="2"; node render_spot.js es`):

| Variable | Qué hace | Por defecto |
|---|---|---|
| `SCALE` | Nitidez: se dibuja a `1080 × SCALE` y se reduce. `2` es más nítido y más lento | `1.5` |
| `STILLS` | Guarda además un fotograma cada N segundos en `out/` | no |
| `FROM`, `TO` | Solo el spot: renderiza solo ese tramo (segundos), sin música, para revisar un momento | todo |
| `SPEED` | Solo el paseo: velocidad. `1` ≈ 93 s, `1.3` ≈ 70 s, `1.5` ≈ 62 s | `1.3` |
| `FFMPEG` | Ruta de ffmpeg si no está en el PATH | `ffmpeg` |

El texto usa la fuente Inter si está instalada (si no, la del sistema).

## El spot (50 s, sobre la música)

La música (`assets/music.mp3`) va a 150 pulsos por minuto. Cada escena empieza en uno de sus golpes, las palabras del
titular entran al ritmo y el brillo del fondo sigue el volumen (`assets/music.json`).

| Segundo | En la música | Qué pasa |
|---|---|---|
| 0 – 6,2 | Subida | «Un mensaje.» «Todos tus canales.» «A la vez.» |
| 6,2 | Primer golpe | Aparece el logo de eMesh |
| 10,4 – 12 | | El logo sube a su esquina y entra el iPhone girando |
| 12 – 18,4 | Golpe | **Toda tu red, de un vistazo**: el inicio del bot y los números de la red |
| 18,4 – 25,5 | | **Añade canales en dos toques**: elegir canal, permisos; la red crece |
| 25,5 | Golpe | «✅ añadido a la red» |
| 26,4 – 30,6 | Redoble | **Escribe una vez…**: el mensaje con su foto; el dedo espera sobre ✅ Enviar |
| 30,6 – 37,2 | El golpe grande | **…publica en todos**: el mensaje vuela a cada canal, uno por pulso |
| 37,2 – 40,4 | Golpe | **Cada mensaje, a su hora**: el día con la hora de cada mensaje |
| 40,4 – 43,6 | | **Tus asociados suman canales**: llega una solicitud y se acepta |
| 43,6 – 46,8 | | **Mide cada envío**: entregados y alcance |
| 46,8 – 50 | Golpe final | Logo, «Crea tu red en un minuto» y eSoft |

Cambiar los textos del spot: `TEXTS` en `spot.html`. Cambiar los tiempos: `T` (los golpes), `VIEWS` (qué pantalla
se ve), `TAPS` (los toques del dedo) y `POSE` (la posición 3D del teléfono), también en `spot.html`.
Con otra música hay que volver a medir sus golpes y cambiar esos tiempos.

## El paseo (unos 70 s, sin música)

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

Cambiar los textos, los canales de ejemplo, los mensajes o el orden: están arriba de `capture.py` (`TEXT`) y en
`test_guion` / `test_spot`. Después hay que volver a grabar (necesita Python y `pip install -r requirements-dev.txt`):

```bash
tools/promo_video/make.sh          # graba y renderiza los dos vídeos
```

o, paso a paso: `python -m pytest -p tests.conftest tools/promo_video/capture.py -q -n 0 -p no:cacheprovider` y luego
`node tools/promo_video/render_spot.js` y `node tools/promo_video/render.js`.

## Archivos

- `capture.py`: graba lo que se ve del bot: `guion_es.json` (el paseo, paso a paso) y `spot_es.json` (las pantallas del spot).
- `spot.html` + `render_spot.js`: el spot. `spot.html` dibuja cualquier segundo del spot; `render_spot.js` lo recorre
  fotograma a fotograma (Chromium) y lo une a la música con ffmpeg.
- `player.html` + `render.js`: el paseo.
- `phone.css`: el iPhone y Telegram en tema oscuro, común a los dos. El color del iPhone está en `#device`
  (un degradado de burdeos `#7a1f3f` a morado oscuro `#23092a`).
- `assets/`: `logo.png` y `logo_banner.jpg` (logo de eMesh), `avatar.jpg` (avatar del bot), `esoft.png` (eSoft),
  `music.mp3` y `music.json` (la música y su volumen medido), y las fotos de los mensajes de ejemplo
  (`post_*.jpg`, de [Unsplash](https://unsplash.com/license): uso libre, también comercial).
