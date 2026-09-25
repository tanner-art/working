// Compatibility entry point for existing route consumers. Surface discovery
// and validation live behind the public composition boundary.
export {
  appSurfaceForPath,
  appSurfaceDefinitionForPath,
  appSurfaceRegistry,
  defaultAppSurface,
  type AppSurface,
  type AppSurfaceDefinition,
  type SurfacePersistence,
} from './surfaces'
