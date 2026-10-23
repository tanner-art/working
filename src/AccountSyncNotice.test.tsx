import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { AccountSyncNotice } from './AccountSyncNotice'

const base = { status: 'Synced with your account.', error: '', deviceOnly: -2, count: 140 }
describe('quiet account sync information', () => {
  it('keeps healthy sync and a different local backup out of the page header', () => {
    expect(renderToStaticMarkup(<AccountSyncNotice {...base} />)).toBe('')
    expect(renderToStaticMarkup(<AccountSyncNotice {...base} deviceOnly={0} />)).toBe('')
  })
  it('preserves count, sync status and backup guidance in Data settings', () => {
    const html = renderToStaticMarkup(<AccountSyncNotice {...base} details />)
    expect(html).toContain('140 saved thoughts')
    expect(html).toContain('Synced with your account.')
    expect(html).toContain('Device backup kept')
    expect(html).toContain('does not mean account sync failed')
    expect(html).toContain('Return to this device’s local data')
  })
  it('never hides actual extra device captures or an unreadable backup', () => {
    expect(renderToStaticMarkup(<AccountSyncNotice {...base} deviceOnly={30} />)).toContain('30 device-only captures preserved')
    expect(renderToStaticMarkup(<AccountSyncNotice {...base} deviceOnly={-1} />)).toContain('Device backup needs attention')
  })
  it.each(['Saving account changes…', 'Account changes waiting to save…', 'Account changes are not saved.', 'Saved to account. Updates resume when you finish editing.'])('keeps %s visible', status => {
    expect(renderToStaticMarkup(<AccountSyncNotice {...base} status={status} />)).toContain(status)
  })
  it('shows refresh errors as alerts regardless of a previously healthy save', () => {
    const html = renderToStaticMarkup(<AccountSyncNotice {...base} error="Refresh unavailable" />)
    expect(html).toContain('role="alert"')
    expect(html).toContain('Refresh unavailable')
  })
})
