/**
 * Public surface-composition boundary. Adding a surface means adding one
 * `*.surface.ts` module; App.tsx and this discovery module remain unchanged.
 */
import {
  createAppSurfaceRegistry,
  defaultAppSurface,
  surfaceDefinitionForPath,
  surfaceModulesFromDiscoveredModules,
  workspaceSurfaceModuleForPath as registeredWorkspaceSurfaceModuleForPath,
  type AppSurface,
  type AppSurfaceDefinition,
  type RenderedWorkspaceSurfaceModule,
  type SurfaceModule,
  type SurfacePersistence,
} from '../appSurfaceRegistry'

const discoveredSurfaceModules = surfaceModulesFromDiscoveredModules({
  ...import.meta.glob<SurfaceModule>('./*.surface.ts', { eager: true }),
  ...import.meta.glob<SurfaceModule>(['./*.tsx', '!./*.test.tsx'], { eager: true }),
})

export const appSurfaceRegistry = createAppSurfaceRegistry(discoveredSurfaceModules)

export function appSurfaceDefinitionForPath(pathname: string): AppSurfaceDefinition {
  return surfaceDefinitionForPath(appSurfaceRegistry, pathname)
}

export function appSurfaceForPath(pathname: string): AppSurface {
  return appSurfaceDefinitionForPath(pathname).id
}

export function workspaceSurfaceModuleForPath(pathname: string): RenderedWorkspaceSurfaceModule | undefined {
  return registeredWorkspaceSurfaceModuleForPath(discoveredSurfaceModules, appSurfaceRegistry, pathname)
}

export {
  defaultAppSurface,
  type AppSurface,
  type AppSurfaceDefinition,
  type RenderedWorkspaceSurfaceModule,
  type SurfacePersistence,
}
