// Node-only packaging regression; intentionally outside the browser TypeScript target.
import { describe, expect, it } from 'vitest'
import entry from './main.tsx?raw'
import app from './App.tsx?raw'
import { readFileSync } from 'node:fs'
import { appSurfaceRegistry, appSurfaceDefinitionForPath } from './appRoutes'
const styles = readFileSync(new URL('./styles.css', import.meta.url), 'utf8')

describe('product repository boundary', () => {
  it('boots the product without bundling the Factory dashboard', () => {
    expect(entry).toContain('render(<App />)')
    expect(entry).not.toMatch(/BuildDashboard|factoryControl|appSurfaceForPath/)
    expect(entry).toContain("register('/sw.js')")
  })
  it('removes the internal operations entry point but keeps product previews', () => {
    expect(app).not.toContain('Open agent dashboard')
    expect(app).toContain('Test landing page and tutorial')
    expect(appSurfaceRegistry.some(surface => surface.path === '/dashboard')).toBe(false)
    expect(appSurfaceDefinitionForPath('/settings').persistence).toBe('workspace')
  })
  it('retains product styles without operational dashboard rules', () => {
    expect(styles).toContain('.app-shell')
    expect(styles).toContain('.capture-page')
    expect(styles).not.toMatch(/\.factory-shell|\.factory-auth|\.public-dashboard/)
  })
})
