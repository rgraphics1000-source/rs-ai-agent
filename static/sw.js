// RS AI Agent - Service Worker for Android PWA Support
const CACHE_NAME = 'rs-ai-agent-v5';

self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.map((key) => {
          if (key !== CACHE_NAME) {
            return caches.delete(key);
          }
        })
      );
    }).then(() => clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  // Always network-first for fresh dashboard updates
  event.respondWith(
    fetch(event.request).catch(() => caches.match(event.request))
  );
});

