import { BrainView } from '../BrainView'
import { defineAppSurface, type WorkspaceSurfaceProps } from '../appSurfaceRegistry'
export const surface = defineAppSurface({ id: 'brain', path: '/brain', persistence: 'workspace' })
export function WorkspaceSurface(props: WorkspaceSurfaceProps) { return <BrainView {...props} /> }
