// Renders the spot: spot_<lang>.json + assets/music.mp3 -> out/emesh_spot_<lang>.mp4 (1080x1080, 30 fps, with the music).
// The spot is cut to the music (spot.html): every scene starts on one of its hits.
// Usage: node render_spot.js [lang ...]
//   SCALE=2    render at 2160 px and scale down (sharper, slower; default 1.5)
//   STILLS=2   also save a frame every 2 seconds in out/stills_spot/
//   FROM=28 TO=38   render only that part (seconds), without the music: to review a moment quickly
//   FFMPEG=... path of ffmpeg when it isn't in the PATH
"use strict";
const { chromium } = require("playwright");
const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");

const FPS = 30;
const SIZE = 1080;
const HERE = __dirname;
const OUT = path.join(HERE, "out");
const SCALE = Number(process.env.SCALE || 1.5);

async function render(browser, lang) {
  const data = JSON.parse(fs.readFileSync(path.join(HERE, `spot_${lang}.json`), "utf8"));
  const music = JSON.parse(fs.readFileSync(path.join(HERE, "assets", "music.json"), "utf8"));
  const page = await browser.newPage({ viewport: { width: SIZE, height: SIZE }, deviceScaleFactor: SCALE });
  page.on("pageerror", (err) => { console.error("page error:", err.message); process.exitCode = 1; });
  await page.goto("file://" + path.join(HERE, "spot.html"));
  const duration = await page.evaluate(([d, m]) => window.__load(d, m), [data, music]);
  await page.evaluate(() => Promise.all([document.fonts.ready, ...[...document.images].map((i) => i.decode().catch(() => null))]));
  const partial = process.env.FROM !== undefined || process.env.TO !== undefined;
  const from = Number(process.env.FROM || 0), to = Math.min(duration, Number(process.env.TO || duration));
  fs.mkdirSync(OUT, { recursive: true });
  const target = path.join(OUT, `emesh_spot_${lang}${partial ? `_${from}-${to}` : ""}.mp4`);
  const audio = partial ? [] : ["-i", path.join(HERE, "assets", "music.mp3")];
  const mix = partial ? ["-an"] : ["-map", "0:v", "-map", "1:a", "-c:a", "aac", "-b:a", "192k",
    "-af", `afade=t=in:st=0:d=0.12,afade=t=out:st=${(duration - 0.6).toFixed(2)}:d=0.6`, "-t", String(duration)];
  const ff = spawn(process.env.FFMPEG || "ffmpeg", ["-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", String(FPS), "-i", "-", ...audio,
    "-vf", `scale=${SIZE}:${SIZE}:flags=lanczos`, "-c:v", "libx264", "-preset", "slow", "-crf", "17", "-pix_fmt", "yuv420p",
    "-profile:v", "high", "-movflags", "+faststart", ...mix, target], { stdio: ["pipe", "inherit", "inherit"] });
  const done = new Promise((resolve, reject) => ff.on("close", (code) => (code ? reject(new Error(`ffmpeg ${code}`)) : resolve())));
  const every = process.env.STILLS ? Math.round(FPS * Number(process.env.STILLS)) : 0;
  if (every) fs.mkdirSync(path.join(OUT, "stills_spot"), { recursive: true });
  const first = Math.round(from * FPS), last = Math.round(to * FPS);
  for (let i = first; i <= last; i++) {
    await page.evaluate((t) => window.__frame(t), i / FPS);
    const shot = await page.screenshot({ type: "jpeg", quality: 93 });
    if (!ff.stdin.write(shot)) await new Promise((r) => ff.stdin.once("drain", r));
    if (every && (i - first) % every === 0) fs.writeFileSync(path.join(OUT, "stills_spot", `${lang}_${(i / FPS).toFixed(1).padStart(5, "0")}s.jpg`), shot);
  }
  ff.stdin.end();
  await done;
  await page.close();
  const size = (fs.statSync(target).size / 1024 / 1024).toFixed(2);
  console.log(`${path.basename(target)}: ${(to - from).toFixed(1)} s, ${last - first + 1} frames, ${size} MB -> ${target}`);
}

(async () => {
  const langs = process.argv.slice(2).length ? process.argv.slice(2)
    : fs.readdirSync(HERE).filter((f) => /^spot_\w+\.json$/.test(f)).map((f) => f.replace(/^spot_|\.json$/g, "")).sort();
  const browser = await chromium.launch();
  try {
    for (const lang of langs) await render(browser, lang);
  } finally {
    await browser.close();
  }
})().catch((err) => { console.error(err); process.exit(1); });
