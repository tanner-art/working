import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { ScheduleView } from './ScheduleView'
import { stageAction } from './actionStaging'
import { legacyUiProjection, migrateLegacyState } from './migration'
import type { ThoughtObject } from './domain'

it('renders an accessible five-value priority control and an explicit CalendarEvent confirmation', () => {
  const action: ThoughtObject = { id: 'a', kind: 'action', status: 'review', originalContent: 'Prepare', source: 'text', createdAt: '2026-09-27T08:00:00.000Z', confidence: .8, interpretation: { summary: 'Prepare launch', suggestedKind: 'action', rationale: 'Work' }, metadata: {}, relationships: [], history: [] }
  const state = legacyUiProjection(migrateLegacyState({ objects: [stageAction(action)], canvas: [] }))
  const markup = renderToStaticMarkup(<ScheduleView state={state} update={() => undefined} />)
  expect(markup).toContain('aria-label="Priority for Prepare launch"')
  expect(markup).toContain('>5 of 5</option>')
  expect(markup).toContain('Confirm CalendarEvent')
  expect(markup).toContain('out of Today, notifications, and the Adaptive Plan until you explicitly add them')
  expect(markup).toContain('Add to plan')
  expect(markup).toContain('<summary>Adaptive Plan (0)</summary>')
  expect(markup).not.toContain('href="/adaptive-plan"')
})
