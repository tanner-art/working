/**
 * Validated composition contract for URL-addressable application surfaces.
 *
 * Surface modules are discovered by `src/surfaces/index.ts`. This module owns
 * validation only; it does not own rendering or persistence capabilities.
 */
export type AppSurface = 'app' | 'settings' | 'landing-preview' | 'tutorial-preview' | 'dashboard' | (string & {})

export type SurfacePersistence = 'workspace' | 'none' | 'factory-projection'

export type AppSurfaceDefinition = Readonly<{
  id: AppSurface
  path: string
  persistence: SurfacePersistence
}>

export type SurfaceModule = Readonly<{ surface: AppSurfaceDefinition }>

const definitionKeys = ['id', 'path', 'persistence'] as const
const persistenceValues = new Set<SurfacePersistence>(['workspace', 'none', 'factory-projection'])

export const defaultAppSurface: AppSurfaceDefinition = Object.freeze({
  id: 'app',
  path: '/',
  persistence: 'workspace',
})

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function validatedDefinition(value: unknown, modulePath: string): AppSurfaceDefinition {
  if (!isRecord(value)) throw new Error(`Invalid surface export in ${modulePath}`)
  const keys = Object.keys(value).sort()
  if (keys.length !== definitionKeys.length || definitionKeys.some(key => !keys.includes(key))) {
    throw new Error(`Malformed surface definition in ${modulePath}`)
  }
  const { id, path, persistence } = value
  if (typeof id !== 'string' || !id.trim() || typeof path !== 'string' || !path.startsWith('/') || path.includes('?') || path.includes('#')) {
    throw new Error(`Malformed surface definition in ${modulePath}`)
  }
  if (!persistenceValues.has(persistence as SurfacePersistence)) {
    throw new Error(`Malformed surface persistence in ${modulePath}`)
  }
  if (id === defaultAppSurface.id || path === defaultAppSurface.path) {
    throw new Error(`Surface ${modulePath} cannot override the application shell`)
  }
  return Object.freeze({ id, path, persistence: persistence as SurfacePersistence })
}

/** Validate one module at authoring time and again when the discovered set is assembled. */
export function defineAppSurface(definition: AppSurfaceDefinition): AppSurfaceDefinition {
  return validatedDefinition(definition, 'surface module')
}

/**
 * Build a deterministic registry from discovered modules. Any malformed
 * export, duplicate id/path, or application-shell override aborts startup.
 */
export function createAppSurfaceRegistry(modules: Record<string, unknown>): readonly AppSurfaceDefinition[] {
  const definitions: AppSurfaceDefinition[] = []
  const ids = new Set<string>()
  const paths = new Set<string>()
  for (const modulePath of Object.keys(modules).sort()) {
    const module = modules[modulePath]
    if (!isRecord(module) || Object.keys(module).length !== 1 || !('surface' in module)) {
      throw new Error(`Malformed surface module ${modulePath}`)
    }
    const definition = validatedDefinition(module.surface, modulePath)
    if (ids.has(definition.id)) throw new Error(`Duplicate surface id ${definition.id}`)
    if (paths.has(definition.path)) throw new Error(`Duplicate surface path ${definition.path}`)
    ids.add(definition.id)
    paths.add(definition.path)
    definitions.push(definition)
  }
  return Object.freeze(definitions)
}

export function surfaceDefinitionForPath(
  registry: readonly AppSurfaceDefinition[],
  pathname: string,
): AppSurfaceDefinition {
  return registry.find(surface => surface.path === pathname) ?? defaultAppSurface
}
