const CACHE_NAME = 'tennis-court-v1';
const PRECACHE = [
    '/static/style.css',
];

self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(CACHE_NAME).then(cache => cache.addAll(PRECACHE))
    );
    self.skipWaiting();
});

self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys().then(keys =>
            Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
        )
    );
    self.clients.claim();
});

self.addEventListener('fetch', event => {
    const url = new URL(event.request.url);

    if (url.pathname.startsWith('/static/')) {
        event.respondWith(
            caches.match(event.request).then(cached =>
                cached || fetch(event.request).then(resp => {
                    const clone = resp.clone();
                    caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
                    return resp;
                })
            )
        );
        return;
    }

    event.respondWith(
        fetch(event.request)
            .then(resp => {
                if (event.request.method === 'GET') {
                    const clone = resp.clone();
                    caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
                }
                return resp;
            })
            .catch(() => caches.match(event.request))
    );
});
