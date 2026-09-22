import { describe, expect, it } from 'vitest'
import {
  DEFAULT_RAW_AUDIO_RETENTION_DAYS,
  getVoiceNoteDaysRemaining,
  getVoiceNoteExpiryTime,
  isVoiceNoteExpired,
  type VoiceNoteRetentionInput,
} from './voiceRetention'

const recordedAt = '2026-01-01T12:00:00.000Z'
const note: VoiceNoteRetentionInput = { recordedAt }
const clock = '2026-01-01T12:00:00.000Z'

describe('voice-note retention policy', () => {
  it('uses fourteen days by default and exposes the exact expiry', () => {
    expect(DEFAULT_RAW_AUDIO_RETENTION_DAYS).toBe(14)
    expect(getVoiceNoteExpiryTime(note)).toBe('2026-01-15T12:00:00.000Z')
    expect(getVoiceNoteDaysRemaining(note, clock)).toBe(14)
  })

  it('treats the exact expiry instant as expired and preserves the boundary before it', () => {
    const expiry = '2026-01-15T12:00:00.000Z'
    expect(isVoiceNoteExpired(note, '2026-01-15T11:59:59.999Z')).toBe(false)
    expect(isVoiceNoteExpired(note, expiry)).toBe(true)
    expect(getVoiceNoteDaysRemaining(note, '2026-01-15T11:59:59.999Z')).toBe(1)
    expect(getVoiceNoteDaysRemaining(note, expiry)).toBe(0)
  })

  it('never expires explicitly saved notes', () => {
    const saved = { ...note, saved: true }
    expect(getVoiceNoteExpiryTime(saved)).toBeNull()
    expect(isVoiceNoteExpired(saved, '2099-01-01T00:00:00.000Z')).toBe(false)
    expect(getVoiceNoteDaysRemaining(saved, '2099-01-01T00:00:00.000Z')).toBeNull()
  })

  it('supports a valid per-user override and indefinite retention', () => {
    expect(getVoiceNoteExpiryTime(note, { rawAudioRetentionDays: 30 })).toBe('2026-01-31T12:00:00.000Z')
    expect(getVoiceNoteExpiryTime(note, { rawAudioRetentionDays: 'indefinite' })).toBeNull()
    expect(getVoiceNoteExpiryTime(note, { rawAudioRetentionDays: null })).toBeNull()
  })

  it.each([
    { rawAudioRetentionDays: 0 },
    { rawAudioRetentionDays: -1 },
    { rawAudioRetentionDays: 1.5 },
    { rawAudioRetentionDays: Number.NaN },
  ])('fails closed for invalid settings: $rawAudioRetentionDays', settings => {
    expect(getVoiceNoteExpiryTime(note, settings)).toBeUndefined()
    expect(isVoiceNoteExpired(note, '2099-01-01T00:00:00.000Z', settings)).toBe(false)
    expect(getVoiceNoteDaysRemaining(note, clock, settings)).toBeUndefined()
  })

  it('fails closed for invalid dates without treating data as deletable', () => {
    const invalid = { recordedAt: 'not-a-date' }
    expect(getVoiceNoteExpiryTime(invalid)).toBeUndefined()
    expect(getVoiceNoteExpiryTime({ recordedAt: '2026-02-30T12:00:00.000Z' })).toBeUndefined()
    expect(isVoiceNoteExpired(invalid, '2099-01-01T00:00:00.000Z')).toBe(false)
    expect(getVoiceNoteDaysRemaining(invalid, clock)).toBeUndefined()
    expect(isVoiceNoteExpired(note, 'not-a-date')).toBe(false)
    expect(getVoiceNoteDaysRemaining(note, 'not-a-date')).toBeUndefined()
  })

  it('uses the supplied clock rather than the system clock', () => {
    expect(getVoiceNoteDaysRemaining(note, '2026-01-10T12:00:00.000Z')).toBe(5)
    expect(getVoiceNoteDaysRemaining(note, '2026-01-14T12:00:00.000Z')).toBe(1)
  })
})
