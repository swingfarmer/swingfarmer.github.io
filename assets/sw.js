const CACHE = 'sf-assets-v1';
self.addEventListener('install', e => { self.skipWaiting(); });
self.addEventListener('activate', e => { e.waitUntil(self.clients.claim()); });
// 네트워크 우선 (오프라인 시 캐시 폴백). 설치 가능 조건 충족용 최소 SW.
self.addEventListener('fetch', e => {
  e.respondWith(
    fetch(e.request).catch(() => caches.match(e.request))
  );
});
