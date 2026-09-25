import { defineAppSurface } from '../appSurfaceRegistry'

export const surface = defineAppSurface({
  id: 'settings',
  path: '/settings',
  persistence: 'workspace',
})
