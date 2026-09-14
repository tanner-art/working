// Minimal, conservative app-shell service worker.
// Same-origin GET requests only. Never touches localStorage.
const CACHE_VERSION = 'v1'
const CACHE_NAME = `threadline-shell-${CACHE_VERSION}`
const CACHE_PREFIX = 'threadline-shell-'

self.addEventListener('install', (event) => {
  // The first page load is not controlled yet, so explicitly cache the built
  // HTML and every same-origin asset it references. This makes the very next
  // launch usable offline without requiring a second online navigation.
  event.waitUntil(
    (async () => {
      const cache = await caches.open(CACHE_NAME)
      const shell = await fetch('/')
      if (!isCacheableResponse(shell)) return
      await cache.put('/', shell.clone())

      const html = await shell.text()
      const paths = [...html.matchAll(/(?:src|href)=["'](\/[A-Za-z0-9_./-]+)["']/g)]
        .map((match) => match[1])
        .filter((path, index, all) => !path.startsWith('/api/') && all.indexOf(path) === index)

      await Promise.all(paths.map(async (path) => {
        const response = await fetch(path)
        if (isCacheableResponse(response)) await cache.put(path, response)
      }))
      await self.skipWaiting()
    })(),
  )
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => key.startsWith(CACHE_PREFIX) && key !== CACHE_NAME)
            .map((key) => caches.delete(key)),
        ),
      )
      .then(() => self.clients.claim()),
  )
})

function isCacheableResponse(response) {
  return Boolean(response) && response.ok && response.type === 'basic'
}

self.addEventListener('fetch', (event) => {
  const { request } = event

  // Only handle same-origin, successful GET requests. Everything else
  // (POST/PUT/etc, cross-origin requests, API calls) passes straight
  // through to the network untouched and uncached.
  if (request.method !== 'GET') return

  const url = new URL(request.url)
  if (url.origin !== self.location.origin) return
  if (url.pathname.startsWith('/api/')) return

  const acceptsHtml = (request.headers.get('accept') || '').includes('text/html')
  const isNavigation = request.mode === 'navigate' || acceptsHtml

  if (isNavigation) {
    // Network-first for HTML so the app shell never goes stale while
    // the user is online; fall back to the cached shell only when offline.
    event.respondWith(
      fetch(request)
        .then(async (response) => {
          if (isCacheableResponse(response)) {
            const cache = await caches.open(CACHE_NAME)
            await cache.put(request, response.clone())
          }
          return response
        })
        .catch(() => caches.match(request).then((cached) => cached || caches.match('/'))),
    )
    return
  }

  // Cache-first for static assets (Vite emits content-hashed filenames,
  // so a cached match is always the correct version for that URL).
  event.respondWith(
    caches.match(request).then((cached) => {
      if (cached) return cached
      return fetch(request).then(async (response) => {
        if (isCacheableResponse(response)) {
          const cache = await caches.open(CACHE_NAME)
          await cache.put(request, response.clone())
        }
        return response
      })
    }),
  )
})
