/**
 * Public surface-composition boundary. Adding a surface means adding one
 * `*.surface.ts` module; App.tsx and this discovery module remain unchanged.
 */
import {
  createAppSurfaceRegistry,
  defaultAppSurface,
  surfaceDefinitionForPath,
  type AppSurface,
  type AppSurfaceDefinition,
  type SurfaceModule,
  type SurfacePersistence,
} from '../appSurfaceRegistry'

const discoveredSurfaceModules = import.meta.glob<SurfaceModule>('./*.surface.ts', { eager: true })

export const appSurfaceRegistry = createAppSurfaceRegistry(discoveredSurfaceModules)

export function appSurfaceDefinitionForPath(pathname: string): AppSurfaceDefinition {
  return surfaceDefinitionForPath(appSurfaceRegistry, pathname)
}

export function appSurfaceForPath(pathname: string): AppSurface {
  return appSurfaceDefinitionForPath(pathname).id
}

export {
  defaultAppSurface,
  type AppSurface,
  type AppSurfaceDefinition,
  type SurfacePersistence,
}
