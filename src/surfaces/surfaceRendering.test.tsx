import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { createAppSurfaceRegistry, surfaceModulesFromDiscoveredModules, workspaceSurfaceModuleForPath, type WorkspaceSurfaceProps } from '../appSurfaceRegistry'
import { WorkspaceSurfaceRenderer } from './surfaceRendering'
import type { AppState } from '../domain'
import { surface as dashboardSurface } from './dashboard.surface'
import { surface as landingPreviewSurface } from './landing-preview.surface'
import { surface as settingsSurface } from './settings.surface'
import { surface as tutorialPreviewSurface } from './tutorial-preview.surface'

const state = { objects: [], canvas: [] } as AppState
const builtinModules = {
  './dashboard.surface.ts': { surface: dashboardSurface },
  './landing-preview.surface.ts': { surface: landingPreviewSurface },
  './settings.surface.ts': { surface: settingsSurface },
  './tutorial-preview.surface.ts': { surface: tutorialPreviewSurface },
}

describe('workspace surface rendering', () => {
  it('renders a synthetic extension alongside builtins and a legitimate schedule module', () => {
    let received: WorkspaceSurfaceProps | undefined
    const fixtureExtension = {
      surface: { id: 'fixture-extension', path: '/__test__/fixture-extension', persistence: 'workspace' as const },
      WorkspaceSurface: (props: WorkspaceSurfaceProps) => {
        received = props
        return <p>{props.state.objects.length} workspace objects</p>
      },
    }
    const scheduleModule = {
      surface: { id: 'schedule', path: '/schedule', persistence: 'workspace' as const },
      WorkspaceSurface: () => null,
    }
    const modules = {
      ...builtinModules,
      './fixture-extension.surface.tsx': fixtureExtension,
      './schedule.surface.tsx': scheduleModule,
    }
    const registry = createAppSurfaceRegistry(modules)
    expect(registry).toEqual(expect.arrayContaining([
      dashboardSurface,
      landingPreviewSurface,
      settingsSurface,
      tutorialPreviewSurface,
      fixtureExtension.surface,
      scheduleModule.surface,
    ]))
    const resolved = workspaceSurfaceModuleForPath(modules, registry, '/__test__/fixture-extension')
    expect(resolved).toBe(fixtureExtension)
    expect(workspaceSurfaceModuleForPath(modules, registry, '/schedule')).toBe(scheduleModule)
    expect(renderToStaticMarkup(<WorkspaceSurfaceRenderer module={resolved!} state={state} update={updater => { received = { state: updater(state), update: () => undefined } }} />)).toContain('0 workspace objects')
    received!.update(current => ({ ...current, objects: [{ id: 'fixture' }] as AppState['objects'] }))
    expect(received!.state.objects[0].id).toBe('fixture')
  })

  it('rejects malformed rendered modules and never resolves previews or factory projections', () => {
    expect(() => createAppSurfaceRegistry({ './bad.tsx': { surface: { id: 'bad', path: '/bad', persistence: 'workspace' }, WorkspaceSurface: 'not-a-component' } })).toThrow('Malformed workspace surface module')
    expect(() => createAppSurfaceRegistry({
      './schedule.tsx': { surface: { id: 'schedule', path: '/schedule', persistence: 'workspace' }, WorkspaceSurface: () => null },
      './schedule-copy.tsx': { surface: { id: 'schedule', path: '/schedule-copy', persistence: 'workspace' }, WorkspaceSurface: () => null },
    })).toThrow('Duplicate surface id schedule')
    const modules = {
      './preview.tsx': { surface: { id: 'preview', path: '/preview', persistence: 'none' as const } },
      './dashboard.tsx': { surface: { id: 'dashboard', path: '/dashboard', persistence: 'factory-projection' as const } },
    }
    const registry = createAppSurfaceRegistry(modules)
    expect(workspaceSurfaceModuleForPath(modules, registry, '/preview')).toBeUndefined()
    expect(workspaceSurfaceModuleForPath(modules, registry, '/dashboard')).toBeUndefined()
  })

  it('only selects TSX modules that explicitly declare a surface export', () => {
    expect(surfaceModulesFromDiscoveredModules({ './canvas.tsx': { MobileCanvasToolbar: () => null }, './schedule.tsx': { surface: { id: 'schedule', path: '/schedule', persistence: 'workspace' } } })).toEqual({ './schedule.tsx': { surface: { id: 'schedule', path: '/schedule', persistence: 'workspace' } } })
  })
})
