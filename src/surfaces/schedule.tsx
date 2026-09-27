import { defineAppSurface, type WorkspaceSurfaceProps } from '../appSurfaceRegistry'
import { ScheduleView } from '../ScheduleView'

export const surface = defineAppSurface({ id: 'schedule', path: '/schedule', persistence: 'workspace' })

export function WorkspaceSurface({ state, update }: WorkspaceSurfaceProps) {
  return <ScheduleView state={state} update={update} />
}
