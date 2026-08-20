// RS AI Agent - Service Worker for Android PWA Support
const CACHE_NAME = 'rs-ai-agent-v2';
const ASSETS = [
  '/',
  '/static/css/style.css',
  '/static/js/dashboard.js',
  '/manifest.json',
  '/static/img/logo.png',
  '/static/img/icon-192.png',
  '/static/img/icon-512.png',
  '/static/img/favicon.png',
  '/favicon.ico'
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
