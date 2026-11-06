// Минимальный service worker: нужен, чтобы панель можно было «установить» как приложение.
// Ничего не кэширует — всегда берём свежие данные с сервера.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', () => {});
