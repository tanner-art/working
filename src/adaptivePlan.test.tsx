import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { AppState, ThoughtObject } from './domain'
import { stageAction, scheduleStagedAction } from './actionStaging'
import { calculateAdaptivePlan, setActionPlanEligibility } from './adaptivePlan'
import { isPersistedState, legacyUiProjection, migrateLegacyState, reconcileLegacyUi } from './migration'
import { reverseObject, setObjectKind } from './objectWorkflow'
import { accountData } from './accountStorage'
import { defaultSettings } from './settings'
import { disabledDelivery } from './digestDelivery'
import { ScheduleView } from './ScheduleView'

const action = (id = 'a', priority = 3 as const): AppState => {
  const review: ThoughtObject = { id, kind: 'action', status: 'review', originalContent: 'Prepare launch', source: 'text',
    createdAt: '2026-09-27T08:00:00.000Z', confidence: .8,
    interpretation: { summary: 'Prepare launch', suggestedKind: 'action', rationale: 'Work' }, metadata: {}, relationships: [], history: [] }
  const state = legacyUiProjection(migrateLegacyState({ objects: [review], canvas: [] }))
  return { ...state, objects: [stageAction(state.objects[0], priority)] }
}

describe('WP-08 Adaptive Plan behavior', () => {
  it('excludes a staged Action until a dedicated gesture, recommends it, and removes it after reversal', () => {
    const staged = action()
    expect(calculateAdaptivePlan(staged).recommendations).toEqual([])
    const eligible = setActionPlanEligibility(staged, 'a', true)
    expect(eligible.objects[0].history.at(-1)?.planEligibility).toEqual({ objectId: 'a', eligible: true, source: 'schedule-plan-eligibility' })
    expect(calculateAdaptivePlan(eligible).recommendations).toMatchObject([{ objectId: 'a', title: 'Prepare launch', priority: 3 }])
    expect(reconcileLegacyUi(eligible).calendarEvents).toEqual([])
    expect(renderToStaticMarkup(<ScheduleView state={eligible} update={() => undefined} />)).toContain('Adaptive Plan recommends next: Prepare launch')
    const reversed = setActionPlanEligibility(eligible, 'a', false)
    expect(calculateAdaptivePlan(reversed).recommendations).toEqual([])
    expect(reversed.objects[0].history.map(entry => entry.planEligibility?.eligible).filter(value => value !== undefined)).toEqual([true, false])
    expect(calculateAdaptivePlan({ ...eligible, objects: [reverseObject(eligible.objects[0])] }).recommendations).toEqual([])
  })

  it('survives local and account serialization while plan output remains derived', () => {
    const eligible = setActionPlanEligibility(action(), 'a', true)
    const model = reconcileLegacyUi(eligible)
    expect(isPersistedState(structuredClone(model))).toBe(true)
    expect(legacyUiProjection(model).objects[0].history.at(-1)?.planEligibility?.eligible).toBe(true)
    expect(calculateAdaptivePlan(legacyUiProjection(model)).recommendations).toHaveLength(1)
    const account = accountData(eligible, defaultSettings, disabledDelivery)
    expect(isPersistedState(account.model)).toBe(true)
    expect(calculateAdaptivePlan(legacyUiProjection(account.model)).recommendations).toHaveLength(1)
    const accountMarkup = renderToStaticMarkup(<ScheduleView state={legacyUiProjection(account.model)} update={() => undefined} />)
    expect(accountMarkup).toContain('Adaptive Plan recommends next: Prepare launch')
    expect(accountMarkup).toContain('Remove from plan')
    expect(accountMarkup).not.toContain('href="/adaptive-plan"')
    expect('adaptivePlan' in model).toBe(false)
  })

  it('does not consume scheduled or dependency-blocked Actions', () => {
    const eligible = setActionPlanEligibility(action(), 'a', true)
    const scheduled = scheduleStagedAction(eligible, 'a', '2026-10-10T10:00:00.000Z', 'UTC')
    expect(calculateAdaptivePlan(scheduled).recommendations).toEqual([])
    const prerequisite: ThoughtObject = { id: 'b', kind: 'idea', status: 'review', originalContent: 'Prerequisite', source: 'text',
      createdAt: '2026-09-27T08:00:00.000Z', confidence: .7,
      interpretation: { summary: 'Prerequisite', suggestedKind: 'idea', rationale: 'Need' }, metadata: {}, relationships: [], history: [] }
    const blockedAction = { ...action().objects[0], relationships: [{ targetId: 'b', type: 'depends_on' as const }] }
    const blockedState = legacyUiProjection(migrateLegacyState({ objects: [blockedAction, prerequisite], canvas: [] }))
    const blocked = setActionPlanEligibility(blockedState, 'a', true)
    expect(calculateAdaptivePlan(blocked)).toMatchObject({ recommendations: [], blockedCount: 1 })
  })

  it('rejects eligibility without an active staged Action and malformed audit chains', () => {
    expect(() => setActionPlanEligibility(action(), 'missing', true)).toThrow('no longer staged')
    const eligible = setActionPlanEligibility(action(), 'a', true)
    const wrongTarget = structuredClone(eligible)
    wrongTarget.objects[0].history.at(-1)!.planEligibility!.objectId = 'other'
    expect(() => reconcileLegacyUi(wrongTarget)).toThrow()
    const duplicate = structuredClone(eligible)
    duplicate.objects[0].history.push({ at: '2026-10-09T00:00:00.000Z', event: 'Added Action to Adaptive Plan',
      planEligibility: { objectId: 'a', eligible: true, source: 'schedule-plan-eligibility' } })
    expect(() => reconcileLegacyUi(duplicate)).toThrow()
    const scheduled = scheduleStagedAction(eligible, 'a', '2026-10-10T10:00:00.000Z', 'UTC')
    expect(() => setActionPlanEligibility(scheduled, 'a', false)).toThrow('no longer staged')
    scheduled.objects[0].history.push({ at: '2026-10-11T00:00:00.000Z', event: 'Removed Action from Adaptive Plan',
      planEligibility: { objectId: 'a', eligible: false, source: 'schedule-plan-eligibility' } })
    expect(() => reconcileLegacyUi(scheduled)).toThrow()
    const raw: ThoughtObject = { ...action().objects[0], kind: 'idea', history: [{ at: '2026-10-11T00:00:00.000Z', event: 'Added Action to Adaptive Plan',
      planEligibility: { objectId: 'a', eligible: true, source: 'schedule-plan-eligibility' } }] }
    expect(() => migrateLegacyState({ objects: [raw], canvas: [] })).toThrow()
    const idea = structuredClone(eligible)
    idea.objects[0] = setObjectKind(idea.objects[0], 'idea')
    expect(reconcileLegacyUi(idea).stagedActions).toEqual([])
    expect(idea.objects[0].history.some(entry => entry.planEligibility)).toBe(true)
  })

  it('keeps the plan inside the active Schedule workspace with no full-page navigation', () => {
    const before = renderToStaticMarkup(<ScheduleView state={action()} update={() => undefined} />)
    const after = renderToStaticMarkup(<ScheduleView state={setActionPlanEligibility(action(), 'a', true)} update={() => undefined} />)
    expect(before).toContain('<summary>Adaptive Plan (0)</summary>')
    expect(after).toContain('<summary>Adaptive Plan (1)</summary>')
    expect(after).toContain('Recommended next: Prepare launch')
    expect(after).not.toContain('href="/adaptive-plan"')
  })
})
