import { GlobalSearchView } from '../GlobalSearchView'
import { defineAppSurface, type WorkspaceSurfaceProps } from '../appSurfaceRegistry'

export const surface = defineAppSurface({ id: 'search', path: '/search', persistence: 'workspace' })

export function WorkspaceSurface({ state, snapshotToken, navigate }: WorkspaceSurfaceProps) {
  return <GlobalSearchView state={state} snapshotToken={snapshotToken} navigate={navigate} />
}
