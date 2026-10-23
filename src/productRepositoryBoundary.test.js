// Node-only packaging regression; intentionally outside the browser TypeScript target.
import { describe, expect, it } from 'vitest'
import entry from './main.tsx?raw'
import app from './App.tsx?raw'
import { existsSync, readFileSync, readdirSync } from 'node:fs'
import { appSurfaceRegistry, appSurfaceDefinitionForPath } from './appRoutes'
import removedFactoryStyleRoots from './testSupport/removedFactoryStyleRoots.json'
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
  it('has no product consumers of removed dashboard-only class names', () => {
    // All selector roots removed from efd2dba styles.css, not just the seven
    // generic-looking legacy dashboard roots called out in the first review.
    const removed = new RegExp('\\b(' + removedFactoryStyleRoots.join('|') + ')\\b')
    const sourceRoot = new URL('./', import.meta.url)
    for (const path of readdirSync(sourceRoot, { recursive: true })) {
      if (!/\.(ts|tsx|js|jsx)$/.test(path) || /\.(test|spec)\./.test(path)) continue
      expect(readFileSync(new URL(path, sourceRoot), 'utf8'), path).not.toMatch(removed)
    }
  })
  it('contains no orphaned Factory Python runtime or mutable extraction links', () => {
    for (const path of ['scripts/runner', 'scripts/factory_registry']) {
      const directory = new URL('../' + path, import.meta.url)
      // Git does not track empty directories left by a checkout or local edit.
      const files = existsSync(directory) ? readdirSync(directory, { recursive: true }).filter(file => file.endsWith('.py')) : []
      expect(files, path).toEqual([])
    }
    for (const path of ['TASKS.md', 'docs/ARCHITECTURE.md', 'docs/DECISIONS.md']) {
      expect(readFileSync(new URL('../' + path, import.meta.url), 'utf8')).not.toContain('blob/codex/factory-extraction-')
    }
  })
})
