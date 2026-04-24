const CACHE = "incidentiq-v1";
const FILES = [
  "/", "/index.html", "/login.html",
  "/user-portal.html", "/manager-dashboard.html",
  "/css/style.css"
];

self.addEventListener("install", e =>
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(FILES)))
);

self.addEventListener("fetch", e =>
  e.respondWith(
    caches.match(e.request).then(r => r || fetch(e.request))
  )
);