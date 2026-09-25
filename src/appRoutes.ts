// Kept as the route-facing module for existing callers. The surface registry
// is the single source of truth for route-to-surface composition.
export { appSurfaceForPath, appSurfaceDefinitionForPath, type AppSurface, type AppSurfaceDefinition, type SurfacePersistence } from './appSurfaceRegistry'
