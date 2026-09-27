import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { createAppSurfaceRegistry, surfaceModulesFromDiscoveredModules, workspaceSurfaceModuleForPath, type WorkspaceSurfaceProps } from '../appSurfaceRegistry'
import { WorkspaceSurfaceRenderer } from './surfaceRendering'
import type { AppState } from '../domain'

const state = { objects: [], canvas: [] } as AppState

describe('workspace surface rendering', () => {
  it('renders a synthetic workspace module with the canonical state and update callback', () => {
    let received: WorkspaceSurfaceProps | undefined
    const module = {
      surface: { id: 'schedule', path: '/schedule', persistence: 'workspace' as const },
      WorkspaceSurface: (props: WorkspaceSurfaceProps) => {
        received = props
        return <p>{props.state.objects.length} workspace objects</p>
      },
    }
    const registry = createAppSurfaceRegistry({ './schedule.tsx': module })
    const resolved = workspaceSurfaceModuleForPath({ './schedule.tsx': module }, registry, '/schedule')
    expect(resolved).toBe(module)
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
