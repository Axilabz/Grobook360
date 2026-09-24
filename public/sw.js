// PWA service worker (PROMPT-001 S15 foundation; scope confirmed unchanged
// by PROMPT-028).
//
// Caches ONLY the static app shell so the app can load offline (§6/§21 of
// PROMPT-028's own spec: "the following may be cached for offline
// application startup... dynamic business data must use controlled local
// persistence"). Offline business write/sync (Sales Invoice / Customer /
// Supplier quick-add, the sync queue, conflict handling) is implemented
// entirely in `pwa/*.ts` + IndexedDB (`saas_offline_db`) — NOT in this
// file. `/api/` requests are deliberately never intercepted here so the
// service worker can never serve stale or cross-tenant business data;
// every business read/write goes through the real network (or IndexedDB
// directly) under the application's own tenant/auth-aware logic.

// Bump this on every shell asset change. A cache-first index.html/manifest
// silently keeps serving a stale shell forever otherwise — the version
// string is what forces install()/activate() to fetch+swap in the new
// files (a real incident: an index.html scrollbar-CSS fix wasn't visible
// to an already-installed user until this was bumped).
const SHELL_CACHE = 'app-shell-v2';
const SHELL_ASSETS = ['/', '/index.html', '/manifest.json'];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(SHELL_CACHE).then((cache) => cache.addAll(SHELL_ASSETS)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== SHELL_CACHE).map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // Never cache API calls here: business data freshness/offline-write behavior
  // is governed by the future Offline Sync specification, not this shell cache.
  if (url.pathname.startsWith('/api/')) {
    return;
  }

  if (event.request.method !== 'GET') {
    return;
  }

  // Navigation/HTML requests: network-first, falling back to the cached
  // shell only when offline. A cache-first strategy here would mean every
  // future index.html edit (styling, meta tags, etc.) stays invisible to
  // an already-installed user indefinitely, even after this file's own
  // cache-bust — the whole point of the app shell is offline *fallback*,
  // not a permanent pin to whatever HTML happened to be live at install
  // time.
  const isHtmlRequest = event.request.mode === 'navigate' || url.pathname === '/index.html';
  if (isHtmlRequest) {
    event.respondWith(
      fetch(event.request)
        .then((response) => {
          const responseClone = response.clone();
          caches.open(SHELL_CACHE).then((cache) => cache.put(event.request, responseClone));
          return response;
        })
        .catch(() => caches.match(event.request))
    );
    return;
  }

  event.respondWith(
    caches.match(event.request).then((cached) => cached ?? fetch(event.request))
  );
});
