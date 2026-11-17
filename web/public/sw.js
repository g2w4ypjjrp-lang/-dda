/*
 * Match Intelligence AI — servis çalışanı (PWA).
 *
 * İlke: canlı veri önbellekten sunulmaz. API (/v1, /admin) ve sayfalar her zaman ağdan gelir;
 * ağ yoksa yalnızca çevrimdışı sayfası gösterilir. Değişmeyen statik dosyalar (/_next/static,
 * ikonlar, fontlar) önbellekten hızlı açılır.
 */
const VERSION = "mi-v1";
const STATIC = `${VERSION}-static`;
const OFFLINE = "/offline.html";
const PRECACHE = [OFFLINE, "/icon-192.png", "/icon-512.png", "/icon.svg", "/manifest.webmanifest"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(STATIC).then((c) => c.addAll(PRECACHE)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => !k.startsWith(VERSION)).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/v1/") || url.pathname.startsWith("/admin/")) return; // canlı veri: önbellek yok

  if (req.mode === "navigate") {
    event.respondWith(fetch(req).catch(() => caches.match(OFFLINE)));
    return;
  }
  if (url.pathname.startsWith("/_next/static/") || /\.(png|svg|woff2?)$/.test(url.pathname)) {
    event.respondWith(
      caches.match(req).then((hit) =>
        hit || fetch(req).then((res) => {
          if (res.ok) {
            const copy = res.clone();
            caches.open(STATIC).then((c) => c.put(req, copy));
          }
          return res;
        }),
      ),
    );
  }
});
