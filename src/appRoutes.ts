export type AppSurface = 'app' | 'settings' | 'landing-preview' | 'tutorial-preview' | 'dashboard'

export function appSurfaceForPath(pathname: string): AppSurface {
  if (pathname === '/dashboard') return 'dashboard'
  if (pathname === '/settings') return 'settings'
  if (pathname === '/preview/landing') return 'landing-preview'
  if (pathname === '/preview/tutorial') return 'tutorial-preview'
  return 'app'
}
