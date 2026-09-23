import { describe, expect, it } from 'vitest'
import { agentFromLabels, buildTaskRows, formatAge, statusFromLabels, summarizeAgents } from './buildDashboard'

describe('build dashboard helpers', () => {
  it('maps runner labels into public task status', () => {
    expect(statusFromLabels([{ name: 'runner:running' }])).toBe('running')
    expect(statusFromLabels([{ name: 'runner:review' }])).toBe('review')
    expect(statusFromLabels([{ name: 'runner:failed' }])).toBe('failed')
    expect(statusFromLabels([{ name: 'runner:ready' }])).toBe('ready')
    expect(statusFromLabels([])).toBe('open')
  })

  it('maps agent labels into friendly names', () => {
    expect(agentFromLabels([{ name: 'agent:claude' }])).toBe('Claude')
    expect(agentFromLabels([{ name: 'agent:codex-a' }])).toBe('Agent A')
    expect(agentFromLabels([{ name: 'agent:codex-b' }])).toBe('Agent B')
    expect(agentFromLabels([{ name: 'documentation' }])).toBe('Unassigned')
  })

  it('builds rows from issues and recent merged PRs', () => {
    const rows = buildTaskRows([
      { number: 1, title: 'Task', html_url: 'u', state: 'open', labels: [{ name: 'runner:running' }, { name: 'agent:claude' }], created_at: '2026-09-15T00:00:00Z', updated_at: '2026-09-15T01:00:00Z' },
      { number: 2, title: 'PR issue', html_url: 'u', state: 'open', labels: [], created_at: '2026-09-15T00:00:00Z', updated_at: '2026-09-15T01:00:00Z', pull_request: {} },
      { number: 4, title: 'Completed issue with stale review label', html_url: 'u', state: 'closed', labels: [{ name: 'runner:review' }, { name: 'agent:codex-a' }], created_at: '2026-09-15T00:00:00Z', updated_at: '2026-09-15T03:00:00Z' },
    ], [
      { number: 3, title: 'Merged', html_url: 'p', state: 'closed', merged_at: '2026-09-15T02:00:00Z', created_at: '2026-09-15T00:00:00Z', updated_at: '2026-09-15T02:00:00Z' },
    ])
    expect(rows.map(row => row.number)).toEqual([3, 1])
    expect(rows[1].agent).toBe('Claude')
  })

  it('summarizes visible work by agent', () => {
    const summary = summarizeAgents([
      { number: 1, title: 'A', url: 'u', status: 'running', agent: 'Agent A', createdAt: '', updatedAt: '' },
      { number: 2, title: 'B', url: 'u', status: 'review', agent: 'Agent A', createdAt: '', updatedAt: '' },
      { number: 3, title: 'C', url: 'u', status: 'failed', agent: 'Claude', createdAt: '', updatedAt: '' },
    ])
    expect(summary.find(item => item.agent === 'Agent A')).toMatchObject({ running: 1, review: 1, total: 2 })
    expect(summary.find(item => item.agent === 'Claude')).toMatchObject({ failed: 1, total: 1 })
  })

  it('formats rough working times', () => {
    const now = new Date('2026-09-15T03:30:00Z')
    expect(formatAge('2026-09-15T03:29:30Z', now)).toBe('just now')
    expect(formatAge('2026-09-15T03:00:00Z', now)).toBe('30m ago')
    expect(formatAge('2026-09-15T01:00:00Z', now)).toBe('2h ago')
  })
})
