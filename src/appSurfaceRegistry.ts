/**
 * Declarative boundary between URL routing and feature surfaces.
 *
 * This registry deliberately describes composition only. Surface components
 * retain ownership of their state and persistence; routing must not create a
 * second storage path or move data between surfaces.
 */
export type AppSurface = 'app' | 'settings' | 'landing-preview' | 'tutorial-preview' | 'dashboard'

export type SurfacePersistence = 'workspace' | 'none' | 'factory-projection'

export type AppSurfaceDefinition = {
  id: AppSurface
  path: string
  persistence: SurfacePersistence
}

export const appSurfaceRegistry: readonly AppSurfaceDefinition[] = [
  { id: 'dashboard', path: '/dashboard', persistence: 'factory-projection' },
  { id: 'settings', path: '/settings', persistence: 'workspace' },
  { id: 'landing-preview', path: '/preview/landing', persistence: 'none' },
  { id: 'tutorial-preview', path: '/preview/tutorial', persistence: 'none' },
]

export const defaultAppSurface: AppSurfaceDefinition = {
  id: 'app',
  path: '/',
  persistence: 'workspace',
}

/** Resolves a URL without giving routing authority over surface state. */
export function appSurfaceDefinitionForPath(pathname: string): AppSurfaceDefinition {
  return appSurfaceRegistry.find(surface => surface.path === pathname) ?? defaultAppSurface
}

export function appSurfaceForPath(pathname: string): AppSurface {
  return appSurfaceDefinitionForPath(pathname).id
}
