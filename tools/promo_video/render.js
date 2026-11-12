// Renders guion_<lang>.json into out/emesh_promo_<lang>.mp4: a 1:1 video (1080x1080, 30 fps) of the player.
// Usage: node render.js [lang ...]            (no args: every guion_*.json here)
//   SCALE=2    render at 2160 px and scale down (sharper, slower; default 1.5)
//   SPEED=1.2  plays the story faster or slower (default 1.3: about 70 seconds)
//   STILLS=2   also save a frame every 2 seconds in out/stills/ (to review the video without playing it)
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
const SPEED = Number(process.env.SPEED || 1.3);
const MAX_SECONDS = 300;

async function render(browser, lang) {
  const data = JSON.parse(fs.readFileSync(path.join(HERE, `guion_${lang}.json`), "utf8"));
  data.banner = "assets/logo_banner.jpg";  // the logo: the corner, the covers and the bot's home image
  data.avatar = "assets/avatar.jpg";       // the bot's avatar in Telegram
  const page = await browser.newPage({ viewport: { width: SIZE, height: SIZE }, deviceScaleFactor: SCALE });
  await page.goto("file://" + path.join(HERE, "player.html"));
  await page.evaluate(() => document.fonts.ready);
  await page.evaluate(([d, speed]) => window.__load(d, speed), [data, SPEED]);
  fs.mkdirSync(OUT, { recursive: true });
  const target = path.join(OUT, `emesh_promo_${lang}.mp4`);
  const ff = spawn(process.env.FFMPEG || "ffmpeg", ["-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", String(FPS),
    "-i", "-", "-vf", `scale=${SIZE}:${SIZE}:flags=lanczos`, "-c:v", "libx264", "-preset", "slow", "-crf", "18",
    "-pix_fmt", "yuv420p", "-profile:v", "high", "-movflags", "+faststart", "-an", target],
    { stdio: ["pipe", "inherit", "inherit"] });
  const done = new Promise((resolve, reject) => ff.on("close", (code) => (code ? reject(new Error(`ffmpeg ${code}`)) : resolve())));
  const every = process.env.STILLS ? Math.round(FPS * Number(process.env.STILLS)) : 0;
  if (every) fs.mkdirSync(path.join(OUT, "stills"), { recursive: true });
  let frames = 0;
  for (let i = 0; i <= MAX_SECONDS * FPS; i++) {
    const finished = await page.evaluate((t) => window.__frame(t), i / FPS);
    const shot = await page.screenshot({ type: "jpeg", quality: 93 });
    if (!ff.stdin.write(shot)) await new Promise((r) => ff.stdin.once("drain", r));
    if (every && i % every === 0) fs.writeFileSync(path.join(OUT, "stills", `${lang}_${String(i / FPS | 0).padStart(3, "0")}s.jpg`), shot);
    frames = i + 1;
    if (finished) break;
  }
  ff.stdin.end();
  await done;
  await page.close();
  const size = (fs.statSync(target).size / 1024 / 1024).toFixed(2);
  console.log(`emesh_promo_${lang}.mp4: ${(frames / FPS).toFixed(1)} s, ${frames} frames, ${size} MB -> ${target}`);
}

(async () => {
  const langs = process.argv.slice(2).length ? process.argv.slice(2)
    : fs.readdirSync(HERE).filter((f) => /^guion_\w+\.json$/.test(f)).map((f) => f.replace(/^guion_|\.json$/g, "")).sort();
  const browser = await chromium.launch();
  try {
    for (const lang of langs) await render(browser, lang);
  } finally {
    await browser.close();
  }
})().catch((err) => { console.error(err); process.exit(1); });
