#!/usr/bin/env python3
"""把 index.html（Artifact 格式，沒有 <html>/<head>）包成可以自己架站的完整網站 docs/（GitHub Pages 直接用這個資料夾），並打包成 zip。

用法：python3 tools/build.py
"""
import hashlib
import json
import re
import shutil
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "docs"
NAME = "注音溝通板"
SLUG = "zhuyin-communicate"

HEAD = f"""<!doctype html>
<html lang="zh-Hant-TW">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover,user-scalable=no">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<meta name="apple-mobile-web-app-title" content="{NAME}">
<meta name="theme-color" content="#E5EBE8" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#0F1619" media="(prefers-color-scheme: dark)">
<link rel="manifest" href="manifest.webmanifest">
<link rel="apple-touch-icon" href="icons/icon-180.png">
<style>:root{{box-sizing:border-box;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px);color-scheme:light}}body{{margin:0;font:14px system-ui,sans-serif}}img{{max-width:100%}}[hidden]{{display:none!important}}</style>
</head>
<body>
"""
TAIL = """
<script>
if ('serviceWorker' in navigator && window.isSecureContext) {
  navigator.serviceWorker.register('sw.js').catch(() => {});
  if (navigator.storage && navigator.storage.persist) navigator.storage.persist().catch(() => {}); // 請瀏覽器不要自動清掉離線資料
}
</script>
</body>
</html>
"""

CORE_FILES = ["./", "index.html", "data/zhuyin-dict.js", "manifest.webmanifest",
              "icons/icon-180.png", "icons/icon-192.png"]
FONT_FILE = "fonts/zhuyinboard-round.woff2"

SW = """// 離線快取：先用快取（沒有網路也能馬上打開），同時在背景抓新版，下次打開就是新版
const CACHE = '%(slug)s-%(hash)s';
const FILES = %(files)s;

self.addEventListener('install', e => e.waitUntil((async () => {
  await (await caches.open(CACHE)).addAll(FILES);
  await self.skipWaiting();
})()));

// 只清掉本站自己的舊版快取，以及舊的眼控版留下的快取（同一個 github.io 網域上別的網站的快取不動）
self.addEventListener('activate', e => e.waitUntil((async () => {
  for (const k of await caches.keys()) {
    if ((k.startsWith('%(slug)s-') && k !== CACHE) || k.startsWith('zhuyin-eye-')) await caches.delete(k);
  }
  await self.clients.claim();
})()));

self.addEventListener('fetch', e => {
  const req = e.request, url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== location.origin || !url.href.startsWith(self.registration.scope)) return;
  e.respondWith((async () => {
    const cache = await caches.open(CACHE);
    const hit = await cache.match(req, { ignoreSearch: true });
    const net = fetch(req).then(res => { if (res.ok) cache.put(req, res.clone()); return res; });
    if (hit) { e.waitUntil(net.catch(() => { })); return hit; }
    try { return await net; }
    catch (err) { return (req.mode === 'navigate' && await cache.match('index.html')) || Response.error(); }
  })());
});
"""


def icon(size: int) -> Image.Image:
    """圓角方塊裡的對話框，框裡四塊注音鍵：聲母藍、介音綠、韻母黃、聲調紫。"""
    s = size * 4
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * 0.22), fill=(10, 102, 112, 255))
    white = (251, 252, 251, 255)
    d.rounded_rectangle([s * 0.13, s * 0.15, s * 0.87, s * 0.71], radius=int(s * 0.12), fill=white)
    d.polygon([(s * 0.27, s * 0.66), (s * 0.22, s * 0.87), (s * 0.45, s * 0.69)], fill=white)
    colors = [(77, 130, 190, 255), (76, 160, 110, 255), (222, 166, 64, 255), (140, 112, 196, 255)]
    xs = [(0.24, 0.48), (0.52, 0.76)]
    ys = [(0.25, 0.42), (0.45, 0.62)]
    for i, (y0, y1) in enumerate(ys):
        for j, (x0, x1) in enumerate(xs):
            d.rounded_rectangle([s * x0, s * y0, s * x1, s * y1], radius=int(s * 0.04), fill=colors[i * 2 + j])
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    if DIST.exists():
        shutil.rmtree(DIST)
    (DIST / "icons").mkdir(parents=True)
    page = (ROOT / "index.html").read_text(encoding="utf-8")
    files = list(CORE_FILES)
    if (ROOT / FONT_FILE).exists():  # 自架版用本機字型，離線時字形才不會換掉
        page = re.sub(r'<link rel="preconnect"[^>]*>\n', "", page)
        gf = '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Huninn&display=swap">'
        assert gf in page, "Google Fonts link not found in index.html"
        page = page.replace(gf, '<style>@font-face{font-family:"ZhuyinBoard Round";src:url("%s") format("woff2");font-display:swap}</style>' % FONT_FILE)
        stack = '--font-board: "Huninn",'
        assert stack in page, "font stack not found in index.html"
        page = page.replace(stack, '--font-board: "ZhuyinBoard Round",')  # 修改版字型依 OFL 不能沿用原名
        (DIST / "fonts").mkdir()
        for f in (Path(FONT_FILE).name, "OFL.txt"):
            if (ROOT / "fonts" / f).exists():
                shutil.copy2(ROOT / "fonts" / f, DIST / "fonts" / f)
        files.append(FONT_FILE)
    (DIST / "index.html").write_text(HEAD + page + TAIL, encoding="utf-8")
    for f in ["data/zhuyin-dict.js", "data/README.md"]:
        (DIST / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / f, DIST / f)
    for size in (180, 192, 512):
        icon(size).save(DIST / "icons" / f"icon-{size}.png")
    manifest = {
        "id": "./", "name": NAME, "short_name": NAME, "lang": "zh-Hant-TW", "start_url": "./", "scope": "./",
        "display": "standalone", "orientation": "any",
        "background_color": "#E5EBE8", "theme_color": "#0A6670",
        "icons": [{"src": f"icons/icon-{n}.png", "sizes": f"{n}x{n}", "type": "image/png"} for n in (192, 512)],
    }
    (DIST / "manifest.webmanifest").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    digest = hashlib.sha256()
    for f in files:
        if f != "./":
            digest.update((DIST / f).read_bytes())
    (DIST / "sw.js").write_text(SW % {"slug": SLUG, "hash": digest.hexdigest()[:10], "files": json.dumps(files)}, encoding="utf-8")
    (DIST / ".nojekyll").write_text("", encoding="utf-8")  # GitHub Pages 不要處理檔案
    z = ROOT / f"{SLUG}-site.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(DIST.rglob("*")):
            if p.is_file():
                zf.write(p, p.relative_to(DIST))
    total = sum(p.stat().st_size for p in DIST.rglob("*") if p.is_file())
    print(f"docs/ {total / 1e6:.1f} MB, zip {z.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
