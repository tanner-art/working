import { ScheduleView } from '../ScheduleView'
import { defineAppSurface, type WorkspaceSurfaceProps } from '../appSurfaceRegistry'

export const surface = defineAppSurface({ id: 'schedule', path: '/schedule', persistence: 'workspace' })
export function WorkspaceSurface({ state, update }: WorkspaceSurfaceProps) {
  return <ScheduleView state={state} update={update} />
}
