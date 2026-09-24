import { authenticateInterpretCaller } from './interpretAuth'
import { parseFactoryProjection, type FactoryControlSnapshot } from '../src/factoryControl'

export const config = { runtime: 'edge' }

declare const process: { env: Record<string, string | undefined> }

const MAX_SNAPSHOT_BYTES = 1_048_576
const SIGNATURE_PREFIX = 'sha256='

function response(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: {
    'content-type': 'application/json',
    'cache-control': 'private, no-store, max-age=0',
    'x-content-type-options': 'nosniff',
    'vary': 'origin, authorization',
  } })
}

type ProjectionTransport = { url: string; token: string; signingSecret: string }

export function readAllowedUserIds(value: string | undefined): Set<string> | undefined {
  const ids = value?.split(',').map(id => id.trim()).filter(Boolean)
  return ids?.length ? new Set(ids) : undefined
}

export function readProjectionTransport(env: Record<string, string | undefined>): ProjectionTransport | undefined {
  const rawUrl = env.FACTORY_CONTROL_PROJECTION_URL?.trim()
  const token = env.FACTORY_CONTROL_PROJECTION_TOKEN?.trim()
  const signingSecret = env.FACTORY_CONTROL_PROJECTION_SIGNING_SECRET?.trim()
  if (!rawUrl || !token || !signingSecret || signingSecret.length < 32) return undefined
  try {
    const url = new URL(rawUrl)
    if (url.protocol !== 'https:' || url.username || url.password || url.hash) return undefined
    return { url: url.toString(), token, signingSecret }
  } catch { return undefined }
}

function hex(bytes: Uint8Array): string {
  return Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('')
}

function constantTimeEqual(left: string, right: string): boolean {
  if (left.length !== right.length) return false
  let difference = 0
  for (let index = 0; index < left.length; index++) difference |= left.charCodeAt(index) ^ right.charCodeAt(index)
  return difference === 0
}

export async function verifyProjectionSignature(body: string, header: string | null, secret: string): Promise<boolean> {
  if (!header?.startsWith(SIGNATURE_PREFIX)) return false
  const supplied = header.slice(SIGNATURE_PREFIX.length)
  if (!/^[a-f0-9]{64}$/.test(supplied)) return false
  const key = await crypto.subtle.importKey('raw', new TextEncoder().encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign'])
  const signature = await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(body))
  return constantTimeEqual(hex(new Uint8Array(signature)), supplied)
}

async function loadProjection(transport: ProjectionTransport): Promise<FactoryControlSnapshot> {
  const upstream = await fetch(transport.url, {
    method: 'GET',
    headers: { accept: 'application/json', authorization: `Bearer ${transport.token}` },
    cache: 'no-store',
    redirect: 'error',
  })
  if (!upstream.ok || !upstream.headers.get('content-type')?.toLowerCase().includes('application/json')) {
    throw new Error('projection_unavailable')
  }
  const declaredLength = Number(upstream.headers.get('content-length'))
  if (Number.isFinite(declaredLength) && declaredLength > MAX_SNAPSHOT_BYTES) throw new Error('projection_invalid')
  const raw = await upstream.text()
  if (new TextEncoder().encode(raw).byteLength > MAX_SNAPSHOT_BYTES) throw new Error('projection_invalid')
  if (!await verifyProjectionSignature(raw, upstream.headers.get('x-threadline-factory-signature'), transport.signingSecret)) {
    throw new Error('projection_invalid')
  }
  let projection
  try { projection = parseFactoryProjection(JSON.parse(raw)) }
  catch { throw new Error('projection_invalid') }
  return { ...projection, verification: { status: 'verified', algorithm: 'HMAC-SHA-256', verifiedAt: new Date().toISOString() } }
}

export default async function handler(request: Request): Promise<Response> {
  if (request.method !== 'GET') return response(405, { error: 'method_not_allowed' })
  const caller = await authenticateInterpretCaller(request)
  if (!caller.ok) return response(caller.status, { error: caller.error, message: caller.message })
  const allowedUsers = readAllowedUserIds(process.env.FACTORY_CONTROL_ALLOWED_USER_IDS)
  if (!allowedUsers) return response(503, { error: 'authorization_unconfigured', message: 'Factory visibility authorization is not configured.' })
  if (!allowedUsers.has(caller.userId)) return response(403, { error: 'forbidden', message: 'This account is not authorized to view Factory operations.' })
  const transport = readProjectionTransport(process.env)
  if (!transport) return response(503, { error: 'projection_unconfigured', message: 'Factory visibility is not configured for this deployment.' })
  try {
    return response(200, await loadProjection(transport))
  } catch (error) {
    const code = error instanceof Error && error.message === 'projection_invalid' ? 'projection_invalid' : 'projection_unavailable'
    return response(503, { error: code, message: 'The verified Factory snapshot is unavailable.' })
  }
}
