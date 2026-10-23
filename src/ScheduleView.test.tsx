import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { ScheduleView } from './ScheduleView'
import { stageAction } from './actionStaging'
import { legacyUiProjection, migrateLegacyState, reconcileLegacyUi } from './migration'
import type { ThoughtObject } from './domain'
import { setObjectStatus, updateObject } from './objectWorkflow'
import { setActionPlanEligibility } from './adaptivePlan'

it('renders an accessible five-value priority control and an explicit CalendarEvent confirmation', () => {
  const action: ThoughtObject = { id: 'a', kind: 'action', status: 'review', originalContent: 'Prepare', source: 'text', createdAt: '2026-09-27T08:00:00.000Z', confidence: .8, interpretation: { summary: 'Prepare launch', suggestedKind: 'action', rationale: 'Work' }, metadata: {}, relationships: [], history: [] }
  const state = legacyUiProjection(migrateLegacyState({ objects: [stageAction(action)], canvas: [] }))
  const markup = renderToStaticMarkup(<ScheduleView state={state} update={() => undefined} />)
  expect(markup).toContain('aria-label="Priority for Prepare launch"')
  expect(markup).toContain('>5 of 5</option>')
  expect(markup).toContain('Confirm CalendarEvent')
  expect(markup).toContain('stay out of Today and notifications')
  expect(markup).toContain('Adding one to the Adaptive Plan does not book calendar time')
  expect(markup).toContain('Add to plan')
  expect(markup).toContain('<summary>Adaptive Plan (0)</summary>')
  expect(markup).not.toContain('href="/adaptive-plan"')
})

it('removes a completed staged Action from the active Schedule list', () => {
  const action: ThoughtObject = { id: 'a', kind: 'action', status: 'review', originalContent: 'Prepare', source: 'text', createdAt: '2026-09-27T08:00:00.000Z', confidence: .8,
    interpretation: { summary: 'Prepare launch', suggestedKind: 'action', rationale: 'Work' }, metadata: {}, relationships: [], history: [] }
  const initial = legacyUiProjection(migrateLegacyState({ objects: [stageAction(action)], canvas: [] }))
  const completed = updateObject(initial.objects[0], setObjectStatus(initial.objects[0], 'complete'))
  const state = legacyUiProjection(reconcileLegacyUi({ ...initial, objects: [completed] }))
  const markup = renderToStaticMarkup(<ScheduleView state={state} update={() => undefined} />)
  expect(state.model?.semanticObjects.find(item => item.id === 'a')?.status).toBe('complete')
  expect(markup).toContain('No staged Actions yet.')
  expect(markup).not.toContain('Priority for Prepare launch')
})

it('uses the current account projection for the plan without navigating away or displaying a stale plan on snapshot failure', () => {
  const review: ThoughtObject = { id: 'a', kind: 'action', status: 'review', originalContent: 'Prepare', source: 'text', createdAt: '2026-09-27T08:00:00.000Z', confidence: .8,
    interpretation: { summary: 'Prepare launch', suggestedKind: 'action', rationale: 'Work' }, metadata: {}, relationships: [], history: [] }
  const loaded = legacyUiProjection(migrateLegacyState({ objects: [review], canvas: [] }))
  const eligible = setActionPlanEligibility({ ...loaded, objects: [stageAction(loaded.objects[0])] }, 'a', true)
  const accountModel = reconcileLegacyUi(eligible)
  // A stale loaded model from another workspace must not outrank the account snapshot.
  const state = { ...eligible, model: migrateLegacyState({ objects: [{ ...review, id: 'old', kind: 'idea' }], canvas: [] }) }
  const markup = renderToStaticMarkup(<ScheduleView state={state} update={() => undefined} readAccountModel={() => accountModel} />)
  expect(markup).toContain('Adaptive Plan recommends next: Prepare launch')
  expect(markup).not.toContain('href="/adaptive-plan"')

  const degraded = renderToStaticMarkup(<ScheduleView state={{ ...eligible, model: accountModel }} update={() => undefined}
    readAccountModel={() => { throw new Error('Account snapshot unavailable') }} />)
  expect(degraded).toContain('Adaptive Plan unavailable')
  expect(degraded).not.toContain('Adaptive Plan recommends next: Prepare launch')
  expect(degraded).not.toContain('<summary>Adaptive Plan (1)</summary>')
  expect(degraded).toContain('type="button" disabled="">Remove from plan')
})
