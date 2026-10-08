import { describe, expect, it, vi } from 'vitest'
import { confirmCommitmentDeadline, scheduleCommitment } from './calendarEntry'
import { resolveCommitment } from './commitmentWorkflow'
import type { ThoughtObject } from './domain'
import { legacyUiProjection, migrateLegacyState } from './migration'

const review: ThoughtObject = { id: 'commitment', kind: 'commitment', status: 'review', originalContent: 'Send contract', source: 'text', createdAt: '2026-10-01T08:00:00.000Z', confidence: .7, interpretation: { summary: 'Send contract', suggestedKind: 'commitment', rationale: 'Promise' }, metadata: {}, relationships: [], history: [{ at: '2026-10-01T08:00:00.000Z', event: 'Captured' }] }
const prepared = () => {
  const baseline = legacyUiProjection(migrateLegacyState({ objects: [review], canvas: [] }))
  return { ...baseline, objects: [resolveCommitment(baseline.objects[0], { title: 'Send contract', date: '2026-10-02', time: '09:30', dependencyIds: [] })] }
}

describe('Commitment calendar confirmations', () => {
  it('keeps deadline and CalendarEvent confirmations distinct and rejects invalid or repeated paths', () => {
    vi.stubGlobal('crypto', { randomUUID: vi.fn().mockReturnValueOnce('deadline').mockReturnValueOnce('event').mockReturnValueOnce('event-confirmation') })
    const state = prepared()
    const deadline = confirmCommitmentDeadline(state, 'commitment')
    expect(deadline.temporalHistory).toMatchObject([{ target: { kind: 'fixed-deadline', objectId: 'commitment', date: '2026-10-02' } }])
    expect(deadline.model?.calendarEvents).toEqual([])
    expect(() => confirmCommitmentDeadline(deadline, 'commitment')).toThrow('already confirmed')
    const scheduled = scheduleCommitment(deadline, 'commitment', 'America/Kentucky/Louisville')
    expect(scheduled.model?.calendarEvents).toMatchObject([{ id: 'event', objectIds: ['commitment'], status: 'scheduled' }])
    expect(scheduled.temporalHistory?.map(entry => entry.target.kind)).toEqual(['fixed-deadline', 'event-scheduling'])
    expect(() => scheduleCommitment(scheduled, 'commitment')).toThrow('already has a CalendarEvent')
    vi.unstubAllGlobals()
  })

  it('fails safely when scheduling has no valid saved date and time', () => {
    const baseline = legacyUiProjection(migrateLegacyState({ objects: [review], canvas: [] }))
    const noTime = { ...baseline, objects: [resolveCommitment(baseline.objects[0], { title: 'Send contract', date: '2026-10-02', dependencyIds: [] })] }
    expect(() => scheduleCommitment(noTime, 'commitment')).toThrow('both a date and time')
    expect(() => confirmCommitmentDeadline(noTime, 'missing')).toThrow('no longer available')
  })
})
