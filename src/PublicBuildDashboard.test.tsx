import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { DashboardView, type View } from './PublicBuildDashboard'
import { factoryControlFixture } from './factoryControl.fixture'

const viewHeadings: Record<View, string> = {
  overview: 'Everyone at a glance',
  queue: 'Feature queue',
  workers: 'Worker diagnostics',
  reviews: 'Independent review queue',
  capacity: 'Capacity scopes',
  history: 'History and provenance',
  failures: 'Failures requiring attention',
}

describe('Factory Control Center components', () => {
  it.each(Object.entries(viewHeadings) as Array<[View, string]>)('renders the %s view with a named section and refresh control', (view, heading) => {
    const markup = renderToStaticMarkup(<DashboardView view={view} snapshot={factoryControlFixture} refreshing={false} onRefresh={() => undefined} />)
    expect(markup).toContain(`<h2>${heading}</h2>`)
    expect(markup).toContain('<button type="button"')
    expect(markup).toContain('>Refresh</button>')
  })

  it('renders queue filters as labeled controls and exposes expandable Features', () => {
    const markup = renderToStaticMarkup(<DashboardView view="queue" snapshot={factoryControlFixture} refreshing={false} onRefresh={() => undefined} />)
    for (const label of ['State', 'Lane', 'Worker', 'Priority', 'Feature', 'Blocked reason']) expect(markup).toContain(label)
    expect(markup).toContain('aria-label="Queue filters"')
    expect(markup).toContain('<details')
    expect(markup).toContain('<summary>')
  })

  it('renders unsafe evidence and pull-request URLs as text instead of links', () => {
    const snapshot = structuredClone(factoryControlFixture)
    snapshot.features[0].packages[0].pullRequestUrl = 'javascript:alert(1)'
    snapshot.features[0].packages[0].evidence[0].url = 'data:text/html,unsafe'
    const markup = renderToStaticMarkup(<DashboardView view="queue" snapshot={snapshot} refreshing={false} onRefresh={() => undefined} />)
    expect(markup).toContain('<span>Open PR</span>')
    expect(markup).toContain('<span>Contract tests</span>')
    expect(markup).not.toContain('href="javascript:')
    expect(markup).not.toContain('href="data:')
  })

  it('renders the complete Feature to evidence provenance drill-through', () => {
    const markup = renderToStaticMarkup(<DashboardView view="history" snapshot={factoryControlFixture} refreshing={false} onRefresh={() => undefined} />)
    for (const value of ['Feature CONTROL-001', 'Package CONTROL-UI', 'Attempt 1', 'Branch', 'Commit', 'Pull request', 'Evidence', 'c4f2da8cb51c32923cde379660b51186f59674c5']) expect(markup).toContain(value)
    expect(markup).toContain('aria-label="Provenance for attempt-control-ui-1"')
    expect(markup).toContain('Registry event timeline')
  })

  it.each(['workers', 'capacity'] as const)('shows per-invocation Claude usage history in %s', view => {
    const markup = renderToStaticMarkup(<DashboardView view={view} snapshot={factoryControlFixture} refreshing={false} onRefresh={() => undefined} />)
    for (const value of ['session-review-001', 'approved-claude-account', '16,788', '23,484', 'SUCCEEDED', 'CLI JSON', 'TRANSCRIPT']) expect(markup).toContain(value)
    expect(markup).toContain('<table>')
    expect(markup).toContain('<th scope="col">Cache read</th>')
    expect(markup).toContain('<th scope="col">Source history</th>')
  })

  it('keeps unsafe attempt provenance URLs non-clickable', () => {
    const snapshot = structuredClone(factoryControlFixture)
    snapshot.features[1].packages[0].attempts[0].pullRequestUrl = 'javascript:alert(1)'
    snapshot.features[1].packages[0].attempts[0].evidence[0].url = 'data:text/html,unsafe'
    const markup = renderToStaticMarkup(<DashboardView view="history" snapshot={snapshot} refreshing={false} onRefresh={() => undefined} />)
    expect(markup).not.toContain('href="javascript:')
    expect(markup).not.toContain('href="data:')
  })
})
