import { describe, expect, it } from 'vitest'
import {
  BETA_SMOKE_MANIFEST,
  SMOKE_PLACEHOLDERS,
  dailyBetaSmokeSubset,
  filterBetaSmokeByArea,
} from './betaSmoke'

describe('beta smoke manifest', () => {
  it('covers the friends-and-family acceptance areas', () => {
    const text = JSON.stringify(BETA_SMOKE_MANIFEST)
    for (const phrase of [
      'landing', 'numeric-code', 'Continue locally', 'tutorial', 'persistence',
      'Review', 'Day', 'Week', 'canvas', 'installed', 'offline', 'deterministic', 'provider',
    ]) expect(text).toContain(phrase)
  })

  it('has unique stable IDs and preserves declared order', () => {
    const ids = BETA_SMOKE_MANIFEST.map(item => item.id)
    expect(new Set(ids).size).toBe(ids.length)
    expect(ids).toEqual([
      'auth-landing-sign-in-link', 'auth-sign-in-numeric-code', 'local-continue-without-account',
      'capture-tutorial-skip-or-complete', 'capture-persistence-after-refresh',
      'review-confirmation-preserves-capture', 'calendar-day-week-commitment-entry',
      'canvas-create-edit-exit', 'install-refresh-update-boundary', 'offline-recovery',
      'ai-deterministic-fallback', 'ai-provider-interpretation-when-enabled',
    ])
    for (const item of BETA_SMOKE_MANIFEST) {
      expect(item.id).toMatch(/^[a-z0-9]+(?:-[a-z0-9]+)+$/)
      expect(item.preconditions.length).toBeGreaterThan(0)
      expect(item.steps.length).toBeGreaterThan(0)
      expect(item.expectedOutcomes.length).toBeGreaterThan(0)
    }
  })

  it('uses privacy-safe placeholders and contains no credential-like content', () => {
    const text = JSON.stringify(BETA_SMOKE_MANIFEST)
    expect(text).toContain(SMOKE_PLACEHOLDERS.email)
    expect(text).toContain(SMOKE_PLACEHOLDERS.capture)
    expect(text).not.toMatch(/\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/i)
    expect(text).not.toMatch(/(?:sk|pk|sbp|eyJ)[_-]?[A-Za-z0-9]{20,}/)
    expect(text).not.toMatch(/\b\d{6,10}\b/)
    expect(text).not.toMatch(/\b(?:deployed|production)\s+(?:provider|integration|status)\b/i)
  })

  it('returns the compact daily subset in stable order', () => {
    const daily = dailyBetaSmokeSubset()
    expect(daily.length).toBeGreaterThan(0)
    expect(daily.length).toBeLessThan(BETA_SMOKE_MANIFEST.length)
    expect(daily.every(item => item.daily)).toBe(true)
    expect(daily.map(item => item.id)).toEqual([
      'auth-landing-sign-in-link', 'auth-sign-in-numeric-code', 'local-continue-without-account',
      'capture-tutorial-skip-or-complete', 'capture-persistence-after-refresh',
      'review-confirmation-preserves-capture', 'calendar-day-week-commitment-entry',
      'canvas-create-edit-exit', 'offline-recovery', 'ai-deterministic-fallback',
    ])
  })

  it('filters by area without changing order', () => {
    expect(filterBetaSmokeByArea(BETA_SMOKE_MANIFEST, 'ai').map(item => item.id)).toEqual([
      'ai-deterministic-fallback', 'ai-provider-interpretation-when-enabled',
    ])
    expect(filterBetaSmokeByArea(BETA_SMOKE_MANIFEST, 'calendar').map(item => item.area)).toEqual(['calendar'])
  })

  it('does not mutate the source manifest or its scenario arrays', () => {
    const before = JSON.stringify(BETA_SMOKE_MANIFEST)
    const daily = dailyBetaSmokeSubset(BETA_SMOKE_MANIFEST)
    const ai = filterBetaSmokeByArea(BETA_SMOKE_MANIFEST, 'ai')
    daily.pop()
    ai.pop()
    expect(JSON.stringify(BETA_SMOKE_MANIFEST)).toBe(before)
    expect(BETA_SMOKE_MANIFEST).toHaveLength(12)
  })
})
