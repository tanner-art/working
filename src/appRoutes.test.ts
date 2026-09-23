import { describe, expect, it } from 'vitest'
import { appSurfaceForPath } from './appRoutes'

describe('hosted app routes', () => {
  it('maps the stable hosted utility routes', () => {
    expect(appSurfaceForPath('/dashboard')).toBe('dashboard')
    expect(appSurfaceForPath('/settings')).toBe('settings')
    expect(appSurfaceForPath('/preview/landing')).toBe('landing-preview')
    expect(appSurfaceForPath('/preview/tutorial')).toBe('tutorial-preview')
  })

  it('keeps all other paths on the main app', () => {
    expect(appSurfaceForPath('/')).toBe('app')
    expect(appSurfaceForPath('/unknown')).toBe('app')
  })
})
