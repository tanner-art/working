import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { ScheduleView } from './ScheduleView'
import { stageAction } from './actionStaging'
import { legacyUiProjection, migrateLegacyState, reconcileLegacyUi } from './migration'
import type { ThoughtObject } from './domain'
import { setObjectStatus, updateObject } from './objectWorkflow'

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
