// RS AI Agent - Service Worker for Android PWA Support
const CACHE_NAME = 'rs-ai-agent-v1';
const ASSETS = [
  '/',
  '/static/css/style.css',
  '/static/js/dashboard.js',
  '/manifest.json'
];

self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(clients.claim());
});

self.addEventListener('fetch', (event) => {
  // Let network handle dynamic API requests
  if (event.request.url.includes('/api/') || event.request.url.includes('/webhook/')) {
    return;
  }
  event.respondWith(
    fetch(event.request).catch(() => caches.match(event.request))
  );
});
