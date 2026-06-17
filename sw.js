// 스윙파머 PWA service worker
// 목적: 크롬 '앱 설치' 조건 충족 + 최소 오프라인 대응
// 캐싱은 최소로 (자주 업데이트되는 사이트라 강한 캐싱은 피함)

const CACHE = 'sf-pwa-v1';

self.addEventListener('install', e => {
  // 즉시 활성화
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  // 예전 캐시 정리
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

// 네트워크 우선 (항상 최신 받아옴, 실패 시에만 캐시)
self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  e.respondWith(
    fetch(e.request)
      .then(res => {
        // 성공한 응답을 캐시에 저장(오프라인 대비)
        const copy = res.clone();
        caches.open(CACHE).then(c => c.put(e.request, copy)).catch(()=>{});
        return res;
      })
      .catch(() => caches.match(e.request)) // 오프라인이면 캐시에서
  );
});
