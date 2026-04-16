// PPE Safety Monitor - Service Worker
// Offline support for app shell, read-only API payloads, and violation images.

const STATIC_CACHE = 'ppe-monitor-static-v7';
const API_CACHE = 'ppe-monitor-api-v7';
const IMAGE_CACHE = 'ppe-monitor-images-v7';

const STATIC_ASSETS = [
  '/',
  '/manifest.json',
  '/static/css/style.css',
  '/static/js/runtime-config.js',
  '/static/js/config.js',
  '/static/js/notifications.js',
  '/static/js/timezone.js',
  '/static/js/violation-monitor.js',
  '/static/js/api.js',
  '/static/js/realtime.js',
  '/static/js/router.js',
  '/static/js/pages/home.js',
  '/static/js/pages/live.js',
  '/static/js/pages/reports.js',
  '/static/js/pages/analytics.js',
  '/static/js/pages/about.js',
  '/static/js/app.js',
  '/static/icons/icon-192x192.png',
  '/static/icons/icon-512x512.png'
];

const CDN_ASSETS = [
  'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css'
];

self.addEventListener('install', (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(STATIC_CACHE);

    await Promise.all(
      STATIC_ASSETS.map(async (assetUrl) => {
        try {
          await cache.add(assetUrl);
        } catch (error) {
          console.warn('[SW] Failed to cache static asset:', assetUrl, error);
        }
      })
    );

    await Promise.all(
      CDN_ASSETS.map(async (assetUrl) => {
        try {
          await cache.add(assetUrl);
        } catch (error) {
          console.warn('[SW] Failed to cache CDN asset:', assetUrl, error);
        }
      })
    );

    await self.skipWaiting();
  })());
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const keep = new Set([STATIC_CACHE, API_CACHE, IMAGE_CACHE]);
    const names = await caches.keys();

    await Promise.all(
      names
        .filter((name) => !keep.has(name))
        .map((name) => caches.delete(name))
    );

    await self.clients.claim();
  })());
});

function isApiGetRequest(request, url) {
  return request.method === 'GET' && url.pathname.startsWith('/api/');
}

function isLiveOrMutatingApi(url) {
  return (
    url.pathname.startsWith('/api/live/') ||
    url.pathname.startsWith('/api/inference/') ||
    url.pathname.startsWith('/api/realtime/stream')
  );
}

function isNoStoreStatusApi(url) {
  return (
    url.pathname === '/api/local-mode/provisioning/status' ||
    url.pathname === '/api/providers/runtime-status' ||
    url.pathname === '/api/reports/recovery/options' ||
    url.pathname === '/api/system/startup-status'
  );
}

function isViolationImageRequest(url) {
  return /\/image\/.+\/(annotated|original)\.jpg$/i.test(url.pathname);
}

async function networkFirstWithCache(request, cacheName, offlineFallback = null) {
  const cache = await caches.open(cacheName);

  try {
    const networkResponse = await fetch(request);
    if (networkResponse && networkResponse.ok) {
      cache.put(request, networkResponse.clone());
    }
    return networkResponse;
  } catch (error) {
    const cached = await cache.match(request);
    if (cached) {
      return cached;
    }
    if (offlineFallback) {
      return offlineFallback;
    }
    throw error;
  }
}

async function staleWhileRevalidate(request, cacheName) {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(request);

  const fetchPromise = fetch(request)
    .then((response) => {
      if (response && response.ok) {
        cache.put(request, response.clone());
      }
      return response;
    })
    .catch(() => cached);

  return cached || fetchPromise;
}

self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  if (request.method !== 'GET') {
    return;
  }

  if (isApiGetRequest(request, url)) {
    if (isNoStoreStatusApi(url)) {
      event.respondWith(
        fetch(request, { cache: 'no-store' }).catch(() => {
          return new Response(
            JSON.stringify({ error: 'Status endpoint unavailable while offline.' }),
            {
              status: 503,
              headers: { 'Content-Type': 'application/json' }
            }
          );
        })
      );
      return;
    }

    if (isLiveOrMutatingApi(url)) {
      event.respondWith(
        fetch(request).catch(() => {
          return new Response(
            JSON.stringify({ error: 'Live endpoint unavailable while offline.' }),
            {
              status: 503,
              headers: { 'Content-Type': 'application/json' }
            }
          );
        })
      );
      return;
    }

    event.respondWith(
      networkFirstWithCache(
        request,
        API_CACHE,
        new Response(JSON.stringify({ error: 'Offline and no cached API response available.' }), {
          status: 503,
          headers: { 'Content-Type': 'application/json' }
        })
      )
    );
    return;
  }

  if (isViolationImageRequest(url)) {
    event.respondWith(staleWhileRevalidate(request, IMAGE_CACHE));
    return;
  }

  event.respondWith((async () => {
    const cache = await caches.open(STATIC_CACHE);
    const cached = await cache.match(request);

    if (cached) {
      fetch(request)
        .then((response) => {
          if (response && response.ok) {
            cache.put(request, response.clone());
          }
        })
        .catch(() => undefined);
      return cached;
    }

    try {
      const response = await fetch(request);
      if (response && response.ok) {
        cache.put(request, response.clone());
      }
      return response;
    } catch (error) {
      if (request.headers.get('accept')?.includes('text/html')) {
        return cache.match('/');
      }
      throw error;
    }
  })());
});
