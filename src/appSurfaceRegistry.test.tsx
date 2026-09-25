import { describe, expect, it } from 'vitest'
import { appSurfaceDefinitionForPath, appSurfaceRegistry, defaultAppSurface } from './appSurfaceRegistry'

describe('application surface registry', () => {
  it('is the observable source of truth for every explicit hosted surface', () => {
    expect(appSurfaceRegistry).toEqual([
      { id: 'dashboard', path: '/dashboard', persistence: 'factory-projection' },
      { id: 'settings', path: '/settings', persistence: 'workspace' },
      { id: 'landing-preview', path: '/preview/landing', persistence: 'none' },
      { id: 'tutorial-preview', path: '/preview/tutorial', persistence: 'none' },
    ])
  })

  it('keeps the main workspace as the safe fallback without assigning persistence to previews', () => {
    expect(appSurfaceDefinitionForPath('/')).toBe(defaultAppSurface)
    expect(appSurfaceDefinitionForPath('/unknown')).toBe(defaultAppSurface)
    expect(appSurfaceDefinitionForPath('/preview/landing').persistence).toBe('none')
    expect(appSurfaceDefinitionForPath('/preview/tutorial').persistence).toBe('none')
  })
})
