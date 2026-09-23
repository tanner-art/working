/** The default lifetime of unsaved raw voice audio, measured in whole days. */
export const DEFAULT_RAW_AUDIO_RETENTION_DAYS = 14
const DAY_MS = 24 * 60 * 60 * 1000

export type RawAudioRetentionDays = number | 'indefinite'

export interface VoiceRetentionSettings {
  /** `indefinite` keeps raw audio until the user explicitly removes it. */
  rawAudioRetentionDays?: RawAudioRetentionDays | null
}

export interface VoiceNoteRetentionInput {
  recordedAt: string
  /** A saved note is protected regardless of the configured retention period. */
  saved?: boolean
}

export type RetentionDate = Date | string | number

const validInstant = (value: RetentionDate): number | undefined => {
  if (typeof value === 'string') {
    const datePart = /^(\d{4})-(\d{2})-(\d{2})(?:$|T|\s)/.exec(value)
    if (datePart) {
      const year = Number(datePart[1]); const month = Number(datePart[2]); const day = Number(datePart[3])
      if (month < 1 || month > 12 || day < 1 || day > new Date(Date.UTC(year, month, 0)).getUTCDate()) return undefined
    }
  }
  const time = value instanceof Date ? value.getTime() : typeof value === 'number' ? value : Date.parse(value)
  return Number.isFinite(time) ? time : undefined
}

const retentionDays = (settings: VoiceRetentionSettings | undefined): number | 'indefinite' | undefined => {
  const configured = settings?.rawAudioRetentionDays
  if (configured === undefined) return DEFAULT_RAW_AUDIO_RETENTION_DAYS
  if (configured === null || configured === 'indefinite') return 'indefinite'
  return Number.isInteger(configured) && configured > 0 ? configured : undefined
}

/**
 * Returns the instant at which an unsaved note expires. `null` means that the
 * note is explicitly saved or retention is indefinite; `undefined` means the
 * input cannot be trusted and must be left untouched.
 */
export function getVoiceNoteExpiryTime(
  note: VoiceNoteRetentionInput,
  settings?: VoiceRetentionSettings,
): string | null | undefined {
  if (typeof note?.recordedAt !== 'string') return undefined
  const recordedAt = validInstant(note.recordedAt)
  if (recordedAt === undefined || typeof note.saved !== 'boolean' && note.saved !== undefined) return undefined
  if (note.saved) return null
  const days = retentionDays(settings)
  if (days === undefined || days === 'indefinite') return days === 'indefinite' ? null : undefined
  return new Date(recordedAt + days * DAY_MS).toISOString()
}

/** Returns true only when a valid, unsaved note is at or beyond its expiry. */
export function isVoiceNoteExpired(
  note: VoiceNoteRetentionInput,
  now: RetentionDate,
  settings?: VoiceRetentionSettings,
): boolean {
  const expiry = getVoiceNoteExpiryTime(note, settings)
  if (expiry === null || expiry === undefined) return false
  const current = validInstant(now)
  const expiration = validInstant(expiry)
  return current !== undefined && expiration !== undefined && current >= expiration
}

/**
 * Returns whole user-facing days remaining, rounding a partial day up. `null`
 * means no expiry and `undefined` means invalid input/settings.
 */
export function getVoiceNoteDaysRemaining(
  note: VoiceNoteRetentionInput,
  now: RetentionDate,
  settings?: VoiceRetentionSettings,
): number | null | undefined {
  const expiry = getVoiceNoteExpiryTime(note, settings)
  if (expiry === null) return null
  if (expiry === undefined) return undefined
  const current = validInstant(now)
  const expiration = validInstant(expiry)
  if (current === undefined || expiration === undefined) return undefined
  return Math.max(0, Math.ceil((expiration - current) / DAY_MS))
}
