// Sieve PWA service worker.
// Trading data must never be stale, so /api/* is ALWAYS network-only (never cached).
// Only the app shell (page + icons + manifest) is cached, as an offline fallback.
const SHELL = "sieve-shell-v2";                // v2: phones get the app (app.html) at "/", the full page at "/web"
const ASSETS = ["/", "/web", "/app", "/manifest.webmanifest", "/icon-192.png", "/icon-512.png", "/icon.png"];

self.addEventListener("install", (e) => {
  self.skipWaiting();
  e.waitUntil(caches.open(SHELL).then((c) => c.addAll(ASSETS)).catch(() => {}));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((ks) =>
    Promise.all(ks.filter((k) => k !== SHELL).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  // Never cache the API: always hit the network so live state and stop/export are real.
  if (url.pathname.startsWith("/api/")) return;
  if (e.request.method !== "GET") return;
  // App shell: network first, fall back to cache only when offline.
  e.respondWith(
    fetch(e.request).then((r) => {
      const copy = r.clone();
      caches.open(SHELL).then((c) => c.put(e.request, copy)).catch(() => {});
      return r;
    }).catch(() => caches.match(e.request).then((m) => m || caches.match("/")))
  );
});
