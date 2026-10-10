import { AdaptivePlanView } from '../AdaptivePlanView'
import { defineAppSurface, type WorkspaceSurfaceProps } from '../appSurfaceRegistry'

export const surface = defineAppSurface({ id: 'adaptive-plan', path: '/adaptive-plan', persistence: 'workspace' })
export function WorkspaceSurface({ state }: WorkspaceSurfaceProps) {
  return <AdaptivePlanView state={state} />
}
