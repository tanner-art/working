import { localDateKey, validDateKey } from './morningDigest'

export const DIGEST_DELIVERY_KEY = 'threadline-morning-digest-v1'
export interface DigestDelivery { enabled: boolean; confirmedAt?: string; deliveredDay?: string }
export const disabledDelivery: DigestDelivery = { enabled: false }

export function readDelivery(storage: Pick<Storage, 'getItem'>): DigestDelivery {
  const raw = storage.getItem(DIGEST_DELIVERY_KEY)
  if (raw === null) return { ...disabledDelivery }
  const value = JSON.parse(raw) as DigestDelivery
  if (!value || typeof value.enabled !== 'boolean' ||
    (value.enabled && (!value.confirmedAt || !Number.isFinite(Date.parse(value.confirmedAt)))) ||
    (value.deliveredDay !== undefined && !validDateKey(value.deliveredDay))) throw new Error('Invalid digest settings')
  return value
}

/** Consent is specific to this in-app schedule, not to individual reminder instructions. */
export function setDeliveryEnabled(previous: DigestDelivery, enabled: boolean, now: Date): DigestDelivery {
  return { ...previous, enabled, confirmedAt: now.toISOString() }
}

export function digestIsDue(settings: DigestDelivery, now: Date, visible: boolean): boolean {
  return settings.enabled && !!settings.confirmedAt && visible && now.getHours() >= 7 &&
    settings.deliveredDay !== localDateKey(now)
}
