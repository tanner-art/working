import { ChatView } from '../ChatView'
import { defineAppSurface, type WorkspaceSurfaceProps } from '../appSurfaceRegistry'
export const surface = defineAppSurface({ id: 'chat', path: '/chat', persistence: 'workspace' })
export function WorkspaceSurface({ navigate, registerExitGuard }: WorkspaceSurfaceProps) { return <ChatView navigate={navigate} registerExitGuard={registerExitGuard} /> }
