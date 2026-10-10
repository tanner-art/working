import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import { canvasBankForState, createCanvasRecord } from './canvasBank'
import { CanvasBank } from './CanvasBankView'
import { legacyUiProjection, migrateLegacyState } from './migration'
import { confirmObject, resolvedIdeas, setObjectStatus } from './objectWorkflow'
import { makeObject } from './store'
import { confirmedConnectionGraph, connectThoughts } from './semanticLinks'

const canvas = (id: string, title: string, updatedAt: string) => ({
  ...createCanvasRecord('2026-09-26T08:00:00.000Z', id),
  title,
  updatedAt,
})

describe('Canvas Bank search surface', () => {
  it('renders an accessible search input, result count, and original canvas card callbacks', () => {
    const productMap = canvas('canvas:product', 'Product map', '2026-09-26T10:00:00.000Z')
    const launchPlan = canvas('canvas:launch', 'Launch plan', '2026-09-26T09:00:00.000Z')
    const onOpen = vi.fn()
    const markup = renderToStaticMarkup(<CanvasBank bank={{ canvases: [launchPlan, productMap] }} ideas={[]} focusTarget={null} onCreate={() => undefined} onOpen={onOpen} onOpenIdea={() => undefined} />)

    expect(markup).toContain('<label for="canvas-bank-search">Search canvases</label>')
    expect(markup).toContain('type="search"')
    expect(markup).toContain('2 canvases saved')
    expect(markup.indexOf('Product map')).toBeLessThan(markup.indexOf('Launch plan'))
    expect(markup).toContain('aria-label="Open Product map"')
    expect(markup).toContain('aria-label="Open Launch plan"')
    expect(onOpen).not.toHaveBeenCalled()
  })

  it('keeps the existing empty-bank state instead of showing search controls', () => {
    const markup = renderToStaticMarkup(<CanvasBank bank={{ canvases: [] }} ideas={[]} focusTarget={null} onCreate={() => undefined} onOpen={() => undefined} onOpenIdea={() => undefined} />)

    expect(markup).toContain('Your canvases will live here.')
    expect(markup).not.toContain('canvas-bank-search')
    expect(markup).toContain('No resolved ideas yet.')
  })

  it('shows persisted resolved ideas beside saved canvases without exposing pending or archived thoughts', () => {
    const proposed = makeObject({ kind: 'idea', source: 'text', originalContent: 'A <quiet> workspace', confidence: .6,
      interpretation: { summary: 'A calm place for thought', suggestedKind: 'idea', rationale: 'User idea' } })
    const resolved = confirmObject(proposed)
    const pending = makeObject({ kind: 'idea', source: 'text', originalContent: 'Pending thought', confidence: .6,
      interpretation: { summary: 'Unresolved idea', suggestedKind: 'idea', rationale: 'User idea' } })
    const archived = setObjectStatus(confirmObject(makeObject({ kind: 'idea', source: 'text', originalContent: 'Archived idea', confidence: .6,
      interpretation: { summary: 'Old concept', suggestedKind: 'idea', rationale: 'User idea' } })), 'archived')
    const state = legacyUiProjection(migrateLegacyState({ objects: [resolved, pending, archived], canvas: [] }))
    const markup = renderToStaticMarkup(<CanvasBank bank={canvasBankForState(state)} ideas={resolvedIdeas(state.objects)} focusTarget={null}
      onCreate={() => undefined} onOpen={() => undefined} onOpenIdea={() => undefined} />)

    expect(markup).toContain('Your canvases will live here.')
    expect(markup).toContain('id="canvas-bank-ideas-heading">Ideas <span>1</span>')
    expect(markup).toContain('aria-label="Open idea: A &lt;quiet&gt; workspace"')
    expect(markup).toContain('A calm place for thought')
    expect(markup).not.toContain('Pending thought')
    expect(markup).not.toContain('Archived idea')
    expect(markup).not.toContain('Old concept')
  })

  it('keeps canvas cards and idea cards together on the same Bank screen', () => {
    const idea = confirmObject(makeObject({ kind: 'idea', source: 'text', originalContent: 'Build a garden', confidence: .6,
      interpretation: { summary: 'Garden idea', suggestedKind: 'idea', rationale: 'User idea' } }))
    const markup = renderToStaticMarkup(<CanvasBank bank={{ canvases: [canvas('canvas:one', 'Product map', '2026-09-26T10:00:00.000Z')] }}
      ideas={[idea]} focusTarget={null} onCreate={() => undefined} onOpen={() => undefined} onOpenIdea={() => undefined} />)

    expect(markup).toContain('aria-label="Open Product map"')
    expect(markup).toContain('aria-label="Open idea: Build a garden"')
  })

  it('shows only confirmed semantic links with a navigable list and a tucked-away authoring control', () => {
    const first = confirmObject(makeObject({ kind: 'idea', source: 'text', originalContent: 'Garden', confidence: .9,
      interpretation: { summary: 'Garden', suggestedKind: 'idea', rationale: 'Idea' } }))
    const second = confirmObject(makeObject({ kind: 'idea', source: 'text', originalContent: 'Sunlight', confidence: .9,
      interpretation: { summary: 'Sunlight', suggestedKind: 'idea', rationale: 'Idea' } }))
    const baseline = legacyUiProjection(migrateLegacyState({ objects: [first, second], canvas: [] }))
    const linked = connectThoughts(baseline, first.id, second.id, 'gesture:ui', '2026-10-10T12:00:00.000Z')
    const markup = renderToStaticMarkup(<CanvasBank bank={{ canvases: [] }} ideas={[first, second]}
      connections={confirmedConnectionGraph(linked)} focusTarget={null} onCreate={() => undefined}
      onOpen={() => undefined} onOpenIdea={() => undefined} onConnect={() => undefined} />)
    expect(markup).toContain('Connections <span>1</span>')
    expect(markup).toContain('<summary>＋ Connect thoughts</summary>')
    expect(markup).toContain('Canvas arrows and older unverified links stay separate.')
    expect(markup).toContain('aria-label="Open Garden"')
    expect(markup).toContain('aria-label="Open Sunlight"')
    expect(markup).toContain('<line')
  })
})
