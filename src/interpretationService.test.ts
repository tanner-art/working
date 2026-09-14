import { describe, expect, it } from 'vitest'
import type { CaptureRecord } from './domain'
import { createInterpretedObject } from './captureInterpretation'
import { interpretationService, type InterpretationService } from './interpretationService'
import { isPersistedState, legacyUiProjection, reconcileLegacyUi } from './migration'
import { confirmedActions, confirmObject } from './objectWorkflow'

const capture: CaptureRecord = Object.freeze({ id: 'capture:test', source: 'text',
  createdAt: '2026-09-14T00:00:00.000Z', originalContent: 'Give marketing guys access',
  context: 'Marketing', evidence: 'text-only' })
const interpret = (originalContent: string) => interpretationService.interpret({ ...capture, originalContent })

describe('Interpretation service regressions', () => {
  it.each(['Maybe send the proposal', 'If approved, buy the monitor', "Don’t email the client",
    "Don't email the client", 'Should I call Ahmed?', 'Cancel the call', 'Cancelled meeting',
    'Canceled appointment', 'I might send it', 'Could buy a monitor', 'Perhaps email Ahmed',
    'Consider buying screws', 'Do not send it', 'Not sure about the deadline', 'Email Ahmed?'])
  ('caps uncertain, conditional, negative and questioned meaning: %s', async content => {
    const result = await interpret(content)
    expect(result.confidence).toBeLessThanOrEqual(.64)
    expect(result.reviewState).toBe('review')
    expect(result.rationale).toContain('uncertainty')
  })

  it.each(['Screws for monitor / selling arm things / better keyboard', 'Buy screws, sell monitor arm'])
  ('detects clusters: %s', async content => {
    expect(await interpret(content)).toMatchObject({ proposedKind: 'project', confidence: .68, reviewState: 'review' })
  })

  it.each(['Remind me to buy screws tomorrow', 'Reminder to launch a new product tomorrow',
    'Remember to send the proposal', 'Call Ahmed 9/15', 'Ahmed Monday convo', 'Meeting tomorrow'])
  ('keeps reminder/timing requests unresolved without inventing an obligation: %s', async content => {
    const result = await interpret(content)
    expect(result).toMatchObject({ proposedKind: 'unresolved', confidence: .74, reviewState: 'review',
      proposedReminder: { captureIds: [capture.id], deliveryState: 'needs-review',
        trigger: { kind: 'unresolved', wording: content } } })
    expect(result.proposedAction).toBeUndefined()
  })

  it('applies uncertainty after reminder routing and project rules after clustering', async () => {
    expect(await interpret('Maybe remind me to buy screws tomorrow?')).toMatchObject({ proposedKind: 'unresolved', confidence: .64 })
    expect(await interpret('Build a new product, launch next year')).toMatchObject({ proposedKind: 'project', confidence: .71 })
  })

  it('is deterministic, keeps original evidence intact, and truncates only the summary', async () => {
    const longCapture = Object.freeze({ ...capture, originalContent: `  ${'idea '.repeat(25)}\n` })
    const before = structuredClone(longCapture)
    const first = await interpretationService.interpret(longCapture)
    expect(first).toEqual(await interpretationService.interpret(longCapture))
    expect(longCapture).toEqual(before)
    expect(first.summary).toBe(`${longCapture.originalContent.slice(0, 81)}…`)
  })
})

describe('service substitution and persistence boundary', () => {
  it('uses an asynchronous substitute through the same capture consumer', async () => {
    let received: CaptureRecord | undefined
    const service: InterpretationService = { async interpret(input) {
      await Promise.resolve()
      received = input
      return { summary: 'Provider proposal', rationale: 'Test substitute', confidence: .99,
        proposedKind: 'action', proposedAction: { summary: 'Provider proposal' }, reviewState: 'review' }
    } }
    const item = await createInterpretedObject('  Preserve my words\n', 'Context', service)
    expect(received).toEqual({ id: `capture:${item.id}`, source: 'text', createdAt: item.createdAt,
      originalContent: '  Preserve my words\n', context: 'Context', evidence: 'text-only' })
    expect(item.status).toBe('review')
    expect(confirmedActions([item])).toEqual([])
    const model = reconcileLegacyUi({ objects: [item], canvas: [] })
    expect(isPersistedState(model)).toBe(true)
    expect(model.captures[0]).toEqual(received)
    expect(model.interpretations[0]).toMatchObject({ captureIds: [received!.id], version: 1,
      proposedKind: 'action', proposedAction: { summary: 'Provider proposal' }, reviewState: 'review' })
    expect(model.semanticObjects).toEqual([])
    const confirmed = confirmObject(legacyUiProjection(model).objects[0])
    const accepted = reconcileLegacyUi({ objects: [confirmed], canvas: [], model })
    expect(accepted.semanticObjects[0].kind).toBe('action')
    expect(accepted.interpretations[0]).toEqual(model.interpretations[0])
  })

  it('rejects substitute meaning that the compatibility writer would otherwise lose', async () => {
    const service: InterpretationService = { async interpret() {
      return { summary: 'One reading', rationale: 'Test', confidence: .9, proposedKind: 'action',
        proposedAction: { summary: 'Different work' }, reviewState: 'review' }
    } }
    await expect(createInterpretedObject('Capture', undefined, service)).rejects.toThrow('cannot be represented')
  })

  it('propagates service failures without substituting a successful interpretation', async () => {
    const service: InterpretationService = { async interpret() { throw new Error('Unavailable') } }
    await expect(createInterpretedObject('My draft', undefined, service)).rejects.toThrow('Unavailable')
  })

  it.each(['Remind me about the software idea tomorrow', 'Call Ahmed 9/15', 'Maybe send the proposal',
    'Screws for monitor / selling arm things / better keyboard'])
  ('preserves routing and evidence through save/reload: %s', async content => {
    const proposal = await interpret(content)
    const item = await createInterpretedObject(content)
    const model = reconcileLegacyUi({ objects: [item], canvas: [] })
    const restored = legacyUiProjection(JSON.parse(JSON.stringify(model)))
    expect(isPersistedState(model)).toBe(true)
    expect(restored.objects[0].status).toBe('review')
    expect(model.interpretations[0]).toMatchObject({ proposedKind: proposal.proposedKind,
      confidence: proposal.confidence, rationale: proposal.rationale, reviewState: 'review' })
    expect(model.captures[0].originalContent).toBe(content)
    expect(model.calendarEvents).toEqual([])
    expect(confirmedActions(restored.objects)).toEqual([])
    if (proposal.proposedKind === 'unresolved') {
      expect(model.semanticObjects).toEqual([])
      expect(model.interpretations[0].proposedReminder).toMatchObject({
        captureIds: [`capture:${item.id}`], deliveryState: 'needs-review',
        trigger: proposal.proposedReminder.trigger,
      })
    }
  })
})
