// 離線快取：先用快取（沒有網路也能馬上打開），同時在背景抓新版，下次打開就是新版
const CACHE = 'zhuyin-communicate-3621e63a6f';
const FILES = ["./", "index.html", "data/zhuyin-dict.js", "manifest.webmanifest", "icons/icon-180.png", "icons/icon-192.png", "fonts/zhuyinboard-round.woff2"];

self.addEventListener('install', e => e.waitUntil((async () => {
  await (await caches.open(CACHE)).addAll(FILES);
  await self.skipWaiting();
})()));

// 只清掉本站自己的舊版快取，以及舊的眼控版留下的快取（同一個 github.io 網域上別的網站的快取不動）
self.addEventListener('activate', e => e.waitUntil((async () => {
  for (const k of await caches.keys()) {
    if ((k.startsWith('zhuyin-communicate-') && k !== CACHE) || k.startsWith('zhuyin-eye-')) await caches.delete(k);
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
