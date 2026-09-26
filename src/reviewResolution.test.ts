import { describe, expect, it } from 'vitest'
import type { ThoughtObject } from './domain'
import { resolveReviewCapture } from './reviewResolution'

const pending = (): ThoughtObject => ({
  id: 'thought:review',
  kind: 'idea',
  originalContent: 'Send the launch plan tomorrow',
  source: 'text',
  confidence: .7,
  status: 'review',
  context: '',
  createdAt: '2026-09-26T08:00:00.000Z',
  interpretation: { summary: 'Send the launch plan tomorrow', suggestedKind: 'action', rationale: 'Work is implied.' },
  metadata: {},
  relationships: [],
  history: [],
})

describe('Review resolution', () => {
  it('confirms an Idea through the single Review resolution path', async () => {
    const result = await resolveReviewCapture(pending(), 'idea')
    expect(result.status).toBe('completed')
    if (result.status === 'completed') {
      expect(result.object.status).toBe('confirmed')
      expect(result.object.kind).toBe('idea')
      expect(result.object.history.at(-1)?.confirmation?.source).toBe('review-confirmation')
    }
  })

  it('delegates an Action and preserves Review when its continuation is unavailable', async () => {
    const result = await resolveReviewCapture(pending(), 'action', {
      action: object => ({ status: 'unavailable', message: `${object.id} still needs action setup.` }),
    })
    expect(result).toEqual({ status: 'recoverable-error', message: 'thought:review still needs action setup.' })
  })

  it.each(['action', 'commitment', 'reminder'] as const)('keeps %s in Review when its registered continuation is unavailable', async kind => {
    const object = pending()
    const result = await resolveReviewCapture(object, kind)
    expect(result.status).toBe('recoverable-error')
    expect(object.status).toBe('review')
    expect(object.history).toEqual([])
  })

  it('turns a thrown continuation into a recoverable error without mutating the capture', async () => {
    const object = pending()
    const result = await resolveReviewCapture(object, 'action', { action: () => { throw new Error('boom') } })
    expect(result.status).toBe('recoverable-error')
    expect(object.history).toEqual([])
  })

  it('cannot resolve an item that has already left Review', async () => {
    const result = await resolveReviewCapture({ ...pending(), status: 'confirmed' }, 'idea')
    expect(result.status).toBe('recoverable-error')
  })
})
