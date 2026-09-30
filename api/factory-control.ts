import { authenticateInterpretCaller } from './interpretAuth.js'
import { parseFactoryProjection, type FactoryControlSnapshot } from '../src/factoryControl.js'

// Node.js is deliberate: its private Supabase read can carry the base64 form
// (up to 1,398,104 bytes) of the 1 MiB gzip snapshot without Edge body limits.
export const config = { runtime: 'nodejs' }

declare const process: { env: Record<string, string | undefined> }

const MAX_COMPRESSED_BYTES = 1_048_576
const MAX_BASE64_BYTES = 4 * Math.ceil(MAX_COMPRESSED_BYTES / 3)
const MAX_EXPANDED_BYTES = 16 * MAX_COMPRESSED_BYTES
const SIGNATURE_PREFIX = 'sha256='
const SNAPSHOT_PATH = '/rest/v1/factory_dashboard_snapshot'

type MirrorConfig = { url: string; serviceKey: string; publishToken: string; signingSecret: string }

function response(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json', 'cache-control': 'private, no-store, max-age=0', 'x-content-type-options': 'nosniff', vary: 'origin, authorization' } })
}

export function readAllowedUserIds(value: string | undefined): Set<string> | undefined {
  const ids = value?.split(',').map(id => id.trim()).filter(Boolean)
  return ids?.length ? new Set(ids) : undefined
}

export function readMirrorConfig(env: Record<string, string | undefined>): MirrorConfig | undefined {
  const rawUrl = env.SUPABASE_URL ?? env.VITE_SUPABASE_URL
  const serviceKey = env.FACTORY_CONTROL_SUPABASE_SERVICE_ROLE_KEY?.trim()
  const publishToken = env.FACTORY_CONTROL_PUBLISH_TOKEN?.trim()
  const signingSecret = env.FACTORY_CONTROL_PROJECTION_SIGNING_SECRET?.trim()
  if (!rawUrl || !serviceKey || !publishToken || !signingSecret || signingSecret.length < 32) return undefined
  try {
    const url = new URL(rawUrl)
    if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash) return undefined
    return { url: url.origin, serviceKey, publishToken, signingSecret }
  } catch { return undefined }
}

function hex(bytes: Uint8Array): string { return Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('') }
function constantTimeEqual(left: string, right: string): boolean {
  if (left.length !== right.length) return false
  let difference = 0
  for (let index = 0; index < left.length; index++) difference |= left.charCodeAt(index) ^ right.charCodeAt(index)
  return difference === 0
}
function base64(bytes: Uint8Array): string {
  let encoded = ''
  for (let index = 0; index < bytes.length; index += 8192) encoded += String.fromCharCode(...bytes.subarray(index, index + 8192))
  return btoa(encoded)
}
function fromBase64(value: string): Uint8Array {
  if (!/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(value)) throw new Error('projection_invalid')
  return Uint8Array.from(atob(value), character => character.charCodeAt(0))
}
function arrayBuffer(bytes: Uint8Array): ArrayBuffer {
  const copy = new ArrayBuffer(bytes.byteLength)
  new Uint8Array(copy).set(bytes)
  return copy
}

async function expand(bytes: Uint8Array): Promise<string> {
  const reader = new Blob([arrayBuffer(bytes)]).stream().pipeThrough(new DecompressionStream('gzip')).getReader()
  const chunks: Uint8Array[] = []
  let size = 0
  try {
    for (;;) {
      const { value, done } = await reader.read()
      if (done) break
      size += value.length
      if (size > MAX_EXPANDED_BYTES) { await reader.cancel(); throw new Error('projection_invalid') }
      chunks.push(value)
    }
  } finally { reader.releaseLock() }
  const expanded = new Uint8Array(size)
  let offset = 0
  for (const chunk of chunks) { expanded.set(chunk, offset); offset += chunk.length }
  return new TextDecoder('utf-8', { fatal: true }).decode(expanded)
}
async function compress(value: string): Promise<Uint8Array> {
  const stream = new Blob([value]).stream().pipeThrough(new CompressionStream('gzip'))
  const body = new Uint8Array(await new Response(stream).arrayBuffer())
  if (body.length > MAX_COMPRESSED_BYTES) throw new Error('projection_invalid')
  return body
}

export async function verifyProjectionSignature(body: Uint8Array, header: string | null, secret: string): Promise<boolean> {
  if (!header?.startsWith(SIGNATURE_PREFIX)) return false
  const supplied = header.slice(SIGNATURE_PREFIX.length)
  if (!/^[a-f0-9]{64}$/.test(supplied)) return false
  const key = await crypto.subtle.importKey('raw', new TextEncoder().encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign'])
  const signature = await crypto.subtle.sign('HMAC', key, arrayBuffer(body))
  return constantTimeEqual(hex(new Uint8Array(signature)), supplied)
}
function storageHeaders(mirror: MirrorConfig): Record<string, string> { return { apikey: mirror.serviceKey, authorization: `Bearer ${mirror.serviceKey}`, accept: 'application/json' } }

async function loadProjection(mirror: MirrorConfig): Promise<FactoryControlSnapshot> {
  const upstream = await fetch(`${mirror.url}${SNAPSHOT_PATH}?id=eq.current&select=body,signature`, { headers: storageHeaders(mirror), cache: 'no-store', redirect: 'error' })
  if (!upstream.ok) throw new Error('projection_unavailable')
  const rows = await upstream.json() as Array<{ body?: unknown; signature?: unknown }>
  const row = Array.isArray(rows) ? rows[0] : undefined
  if (typeof row?.body !== 'string' || typeof row.signature !== 'string') throw new Error('projection_unavailable')
  if (row.body.length > MAX_BASE64_BYTES) throw new Error('projection_invalid')
  const compressed = fromBase64(row.body)
  if (compressed.length > MAX_COMPRESSED_BYTES || !await verifyProjectionSignature(compressed, row.signature, mirror.signingSecret)) throw new Error('projection_invalid')
  try {
    const projection = parseFactoryProjection(JSON.parse(await expand(compressed)))
    return { ...projection, verification: { status: 'verified', algorithm: 'HMAC-SHA-256', verifiedAt: new Date().toISOString() } }
  } catch { throw new Error('projection_invalid') }
}

async function publishProjection(request: Request, mirror: MirrorConfig): Promise<Response> {
  const auth = request.headers.get('authorization')
  if (!auth?.startsWith('Bearer ') || !constantTimeEqual(auth.slice(7), mirror.publishToken)) return response(401, { error: 'unauthorized' })
  if (!request.headers.get('content-type')?.toLowerCase().startsWith('application/gzip')) return response(415, { error: 'invalid_content_type' })
  const declaredLength = Number(request.headers.get('content-length'))
  if (Number.isFinite(declaredLength) && declaredLength > MAX_COMPRESSED_BYTES) return response(413, { error: 'projection_too_large' })
  const compressed = new Uint8Array(await request.arrayBuffer())
  if (compressed.length > MAX_COMPRESSED_BYTES) return response(413, { error: 'projection_too_large' })
  const signature = request.headers.get('x-threadline-factory-signature')
  if (!await verifyProjectionSignature(compressed, signature, mirror.signingSecret)) return response(400, { error: 'projection_invalid' })
  let projection
  try { projection = parseFactoryProjection(JSON.parse(await expand(compressed))) }
  catch { return response(400, { error: 'projection_invalid' }) }
  const saved = await fetch(`${mirror.url}${SNAPSHOT_PATH}?on_conflict=id`, {
    method: 'POST', headers: { ...storageHeaders(mirror), 'content-type': 'application/json', prefer: 'resolution=merge-duplicates' },
    body: JSON.stringify({ id: 'current', body: base64(compressed), signature, registry_revision: projection.registryRevision, published_at: new Date().toISOString() }), cache: 'no-store', redirect: 'error',
  })
  if (!saved.ok) return response(503, { error: 'snapshot_store_unavailable' })
  return response(200, { registryRevision: projection.registryRevision, generatedAt: projection.generatedAt })
}

export async function handler(request: Request): Promise<Response> {
  if (request.method !== 'GET' && request.method !== 'POST') return response(405, { error: 'method_not_allowed' })
  const mirror = readMirrorConfig(process.env)
  if (request.method === 'POST') {
    if (!mirror) return response(503, { error: 'projection_unconfigured' })
    try { return await publishProjection(request, mirror) } catch { return response(503, { error: 'snapshot_store_unavailable' }) }
  }
  const caller = await authenticateInterpretCaller(request, fetch, { allowSameOriginSafeRequestWithoutOrigin: true })
  if (!caller.ok) return response(caller.status, { error: caller.error, message: caller.message })
  const allowedUsers = readAllowedUserIds(process.env.FACTORY_CONTROL_ALLOWED_USER_IDS)
  if (!allowedUsers) return response(503, { error: 'authorization_unconfigured', message: 'Factory visibility authorization is not configured.' })
  if (!allowedUsers.has(caller.userId)) return response(403, { error: 'forbidden', message: 'This account is not authorized to view Factory operations.' })
  if (!mirror) return response(503, { error: 'projection_unconfigured', message: 'Factory visibility is not configured for this deployment.' })
  try {
    const snapshot = await loadProjection(mirror)
    const body = await compress(JSON.stringify(snapshot))
    return new Response(arrayBuffer(body), { status: 200, headers: { 'content-type': 'application/json', 'content-encoding': 'gzip', 'cache-control': 'private, no-store, max-age=0', 'x-content-type-options': 'nosniff', vary: 'origin, authorization' } })
  } catch (error) {
    const code = error instanceof Error && error.message === 'projection_invalid' ? 'projection_invalid' : 'projection_unavailable'
    return response(503, { error: code, message: 'The verified Factory snapshot is unavailable.' })
  }
}

// Vercel's fetch export passes a Web Request; a default function receives a Node request.
export default { fetch: handler }
