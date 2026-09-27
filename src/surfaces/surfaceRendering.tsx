import type { RenderedWorkspaceSurfaceModule, WorkspaceSurfaceProps } from '../appSurfaceRegistry'

/** The only renderer bridge for registered, already-initialized workspace state. */
export function WorkspaceSurfaceRenderer({ module, state, update }: WorkspaceSurfaceProps & {
  module: RenderedWorkspaceSurfaceModule
}) {
  const Surface = module.WorkspaceSurface
  return <Surface state={state} update={update} />
}
