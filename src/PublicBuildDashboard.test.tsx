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
})
