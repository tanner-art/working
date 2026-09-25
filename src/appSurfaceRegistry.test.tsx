import { describe, expect, it } from 'vitest'
import {
  createAppSurfaceRegistry,
  defaultAppSurface,
  surfaceDefinitionForPath,
} from './appSurfaceRegistry'
import { appSurfaceDefinitionForPath, appSurfaceRegistry } from './surfaces'

const moduleFor = (id: string, path: string, persistence = 'none') => ({
  surface: { id, path, persistence },
})

describe('application surface registry', () => {
  it('discovers every existing hosted surface from separate modules', () => {
    expect(appSurfaceRegistry).toEqual(expect.arrayContaining([
      { id: 'dashboard', path: '/dashboard', persistence: 'factory-projection' },
      { id: 'settings', path: '/settings', persistence: 'workspace' },
      { id: 'landing-preview', path: '/preview/landing', persistence: 'none' },
      { id: 'tutorial-preview', path: '/preview/tutorial', persistence: 'none' },
    ]))
    expect(appSurfaceRegistry).toHaveLength(4)
  })

  it('keeps the main workspace as the safe fallback without assigning persistence to previews', () => {
    expect(appSurfaceDefinitionForPath('/')).toBe(defaultAppSurface)
    expect(appSurfaceDefinitionForPath('/unknown')).toBe(defaultAppSurface)
    expect(appSurfaceDefinitionForPath('/preview/landing').persistence).toBe('none')
    expect(appSurfaceDefinitionForPath('/preview/tutorial').persistence).toBe('none')
  })

  it('allows a new module to join without editing a shared list', () => {
    const registry = createAppSurfaceRegistry({
      './review.surface.ts': moduleFor('review', '/review'),
      './schedule.surface.ts': moduleFor('schedule', '/schedule', 'workspace'),
    })
    expect(surfaceDefinitionForPath(registry, '/review').id).toBe('review')
    expect(surfaceDefinitionForPath(registry, '/schedule').id).toBe('schedule')
  })

  it('fails closed on duplicate ids and duplicate paths', () => {
    expect(() => createAppSurfaceRegistry({
      './a.surface.ts': moduleFor('review', '/review'),
      './b.surface.ts': moduleFor('review', '/another-review'),
    })).toThrow('Duplicate surface id review')
    expect(() => createAppSurfaceRegistry({
      './a.surface.ts': moduleFor('review', '/review'),
      './b.surface.ts': moduleFor('schedule', '/review'),
    })).toThrow('Duplicate surface path /review')
  })

  it('fails closed on malformed modules and definitions', () => {
    expect(() => createAppSurfaceRegistry({ './missing.surface.ts': {} })).toThrow('Malformed surface module')
    expect(() => createAppSurfaceRegistry({
      './extra.surface.ts': { surface: { id: 'review', path: '/review', persistence: 'none', shell: true } },
    })).toThrow('Malformed surface definition')
    expect(() => createAppSurfaceRegistry({
      './bad-path.surface.ts': moduleFor('review', 'review'),
    })).toThrow('Malformed surface definition')
    expect(() => createAppSurfaceRegistry({
      './bad-persistence.surface.ts': moduleFor('review', '/review', 'database'),
    })).toThrow('Malformed surface persistence')
  })

  it('rejects attempts to override the application shell', () => {
    expect(() => createAppSurfaceRegistry({
      './id-override.surface.ts': moduleFor('app', '/replacement'),
    })).toThrow('cannot override the application shell')
    expect(() => createAppSurfaceRegistry({
      './path-override.surface.ts': moduleFor('replacement', '/'),
    })).toThrow('cannot override the application shell')
  })
})
