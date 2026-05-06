// PPE Safety Monitor - Service Worker
// Offline support for app shell, read-only API payloads, and violation images.

const STATIC_CACHE = 'ppe-monitor-static-v95';
const API_CACHE = 'ppe-monitor-api-v70';
const IMAGE_CACHE = 'ppe-monitor-images-v70';
const REPORT_CACHE = 'ppe-monitor-reports-v10';
const JSON_HEADERS = { 'Content-Type': 'application/json' };
const OFFLINE_CLOUD_REPORT_MESSAGE = 'Cloud report details are unavailable while offline.';
const LOCAL_REPORT_SYNC_TAG = 'casm-local-report-sync';

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
  '/static/js/ui-animations.js',
  '/static/icons/icon-192x192.png',
  '/static/icons/icon-512x512.png',
  '/static/images/standards/ms183_helmet.jpg',
  '/static/images/standards/ms1731_vest.jpg',
  '/static/images/standards/iso20345_boots.jpg',
  '/static/images/standards/ms2323_mask.png',
  '/static/images/standards/ms2323_mask.png'
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
    const keep = new Set([STATIC_CACHE, API_CACHE, IMAGE_CACHE, REPORT_CACHE]);
    const names = await caches.keys();

    await Promise.all(
      names
        .filter((name) => !keep.has(name))
        .map((name) => caches.delete(name))
    );

    await self.clients.claim();
  })());
});

self.addEventListener('message', (event) => {
  const data = event && event.data ? event.data : {};
  if (data.type !== 'PPE_CLEAR_RUNTIME_API_CACHE') {
    return;
  }

  event.waitUntil((async () => {
    await caches.delete(API_CACHE);
    if (event.source && typeof event.source.postMessage === 'function') {
      event.source.postMessage({
        type: 'PPE_RUNTIME_API_CACHE_CLEARED',
        cacheName: API_CACHE,
        measuredAt: Date.now()
      });
    }
  })());
});

async function notifyWindowClients(message) {
  const clients = await self.clients.matchAll({
    type: 'window',
    includeUncontrolled: true
  });
  clients.forEach((client) => {
    try {
      client.postMessage(message);
    } catch (error) {
      // Ignore closed or unavailable clients.
    }
  });
}

if ('sync' in self.registration) {
  self.addEventListener('sync', (event) => {
    if (event.tag !== LOCAL_REPORT_SYNC_TAG) return;
    event.waitUntil(notifyWindowClients({
      type: 'PPE_BACKGROUND_SYNC_LOCAL_REPORTS',
      tag: LOCAL_REPORT_SYNC_TAG,
      reason: 'background-sync',
      measuredAt: Date.now()
    }));
  });
}

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

function isReportDocumentRequest(url) {
  return /^\/report\/[^/]+\/?$/i.test(url.pathname);
}

function isReportDetailsApiRequest(url) {
  return /^\/api\/report\/[^/]+\/status\/?$/i.test(url.pathname)
    || /^\/api\/violation\/[^/]+\/?$/i.test(url.pathname);
}

function offlineCloudReportJson() {
  return new Response(
    JSON.stringify({
      success: false,
      unavailable_offline: true,
      error: OFFLINE_CLOUD_REPORT_MESSAGE
    }),
    {
      status: 503,
      headers: JSON_HEADERS
    }
  );
}

function offlineCloudReportHtml() {
  return new Response(
    `<!doctype html><html><head><meta charset="utf-8"><title>Report unavailable offline</title></head><body><main style="font-family: system-ui, sans-serif; max-width: 640px; margin: 12vh auto; padding: 24px;"><h1>Report unavailable offline</h1><p>${OFFLINE_CLOUD_REPORT_MESSAGE}</p></main></body></html>`,
    {
      status: 503,
      headers: { 'Content-Type': 'text/html; charset=utf-8' }
    }
  );
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
    .catch(() => cached || new Response('', { status: 503 }));

  return cached || fetchPromise;
}

self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  if (request.method !== 'GET') {
    return;
  }

  if (isReportDocumentRequest(url)) {
    event.respondWith(
      networkFirstWithCache(request, REPORT_CACHE, offlineCloudReportHtml())
    );
    return;
  }

  if (isApiGetRequest(request, url)) {
    if (isReportDetailsApiRequest(url)) {
      event.respondWith(
        fetch(request, { cache: 'no-store' }).catch(() => offlineCloudReportJson())
      );
      return;
    }

    if (isNoStoreStatusApi(url)) {
      event.respondWith(
        fetch(request, { cache: 'no-store' }).catch(() => {
          return new Response(
            JSON.stringify({ error: 'Status endpoint unavailable while offline.' }),
            {
              status: 503,
              headers: JSON_HEADERS
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
              headers: JSON_HEADERS
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
          headers: JSON_HEADERS
        })
      )
    );
    return;
  }

  if (isViolationImageRequest(url)) {
    event.respondWith(staleWhileRevalidate(request, IMAGE_CACHE));
    return;
  }

  // HTML navigations: NETWORK-FIRST so HTML/script changes deploy immediately
  // (avoids the "PWA stuck on old cached index.html" problem).
  const isNavigation = request.mode === 'navigate'
    || (request.headers.get('accept') || '').includes('text/html');

  if (isNavigation) {
    event.respondWith((async () => {
      const cache = await caches.open(STATIC_CACHE);
      try {
        const networkResponse = await fetch(request);
        if (networkResponse && networkResponse.ok) {
          cache.put(request, networkResponse.clone());
        }
        return networkResponse;
      } catch (error) {
        const cached = await cache.match(request) || await cache.match('/');
        if (cached) return cached;
        throw error;
      }
    })());
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
