import { defineAppSurface } from '../appSurfaceRegistry'

export const surface = defineAppSurface({
  id: 'dashboard',
  path: '/dashboard',
  persistence: 'factory-projection',
})
