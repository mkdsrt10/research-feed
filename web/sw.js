const CACHE = "research-feed-v1";
const SHELL = ["/app", "/app/styles.css", "/app/app.js", "/app/manifest.json"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (url.pathname.startsWith("/api/")) return; // always network for data
  event.respondWith(
    caches.match(event.request).then((cached) => cached || fetch(event.request))
  );
});
