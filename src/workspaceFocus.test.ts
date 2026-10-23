import { describe, expect, it, vi } from 'vitest'
import { findWorkspaceReturnFocusTarget } from './workspaceFocus'

describe('Search return focus', () => {
  it('prefers the open modal over the inert sidebar', () => {
    const modal = { isConnected: true, closest: () => null }
    const sidebar = { isConnected: true, closest: () => ({ inert: true }) }
    const root = { querySelector: vi.fn((selector: string) => selector.includes('[role="dialog"]') ? modal : sidebar) } as unknown as ParentNode
    expect(findWorkspaceReturnFocusTarget(root)).toBe(modal)
  })

  it('does not focus a hidden or inert control', () => {
    const hidden = { isConnected: true, closest: () => ({ inert: true }) }
    const root = { querySelector: vi.fn(() => hidden) } as unknown as ParentNode
    expect(findWorkspaceReturnFocusTarget(root)).toBeNull()
  })

  it('prefers the visible Search control when the sidebar is available', () => {
    const search = { isConnected: true, closest: () => null }
    const root = { querySelector: vi.fn((selector: string) => selector === '.sidebar [aria-label="Search"]' ? search : null) } as unknown as ParentNode
    expect(findWorkspaceReturnFocusTarget(root)).toBe(search)
  })
})
