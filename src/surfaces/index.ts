/**
 * Public composition boundary for application surfaces.
 *
 * Feature modules may consume these route contracts, but do not receive
 * storage capabilities through this barrel. Each surface keeps ownership of
 * its own persistence and observable state.
 */
export {
  appSurfaceForPath,
  appSurfaceDefinitionForPath,
  appSurfaceRegistry,
  defaultAppSurface,
  type AppSurface,
  type AppSurfaceDefinition,
  type SurfacePersistence,
} from '../appSurfaceRegistry'
