import { describe, expect, it } from 'vitest'
import { connectionDisplayLabels, connectionFullLabels } from './connectionLabels'
import type { ConnectionNode } from './semanticLinks'

const node = (id: string, label: string): ConnectionNode => ({ id, label, kind: 'idea' })

describe('connection graph display labels', () => {
  it('keeps ordinary parenthetical titles distinct without interpreting their suffixes as IDs', () => {
    const labels = connectionDisplayLabels([
      node('thought:alex', 'Call Alex (re: budget)'), node('thought:sam', 'Call Sam (re: budget)'),
    ])
    expect(labels.get('thought:alex')).toBe('Call Alex (re: budget)')
    expect(labels.get('thought:sam')).toBe('Call Sam (re: budget)')
  })

  it('disambiguates distinct titles and duplicate summaries that shorten to the same text', () => {
    const labels = connectionDisplayLabels([
      node('thought:abcd', 'A very long matching thought summary (idea abcd)'),
      node('thought:efgh', 'A very long matching thought summary (idea efgh)'),
      node('thought:ijkl', 'A very long matching thought from another source'),
    ])
    expect(new Set(labels.values()).size).toBe(3)
    expect(labels.get('thought:abcd')).toContain('·abcd')
    expect(labels.get('thought:efgh')).toContain('·efgh')
    expect(labels.get('thought:ijkl')).toContain('·ijkl')
  })

  it('collapses whitespace and resolves a literal title that resembles an identity suffix', () => {
    const nodes = [
      node('thought:abcd', 'Plan'), node('thought:efgh', 'Plan  '),
      node('thought:ijkl', 'Plan ·abcd'),
    ]
    for (const labels of [connectionFullLabels(nodes), connectionDisplayLabels(nodes)]) {
      expect(new Set(labels.values()).size).toBe(3)
      expect(labels.get('thought:ijkl')).toBe('Plan ·abcd')
      expect(labels.get('thought:abcd')).not.toBe('Plan ·abcd')
      expect([...labels.values()].every(label => label === label.trim() && !/\s{2}/.test(label))).toBe(true)
    }
  })

  it('does not let same-suffix IDs or whitespace-only variants collide', () => {
    const nodes = [node('thought:one-abcd', 'Plan'), node('thought:two-abcd', 'Plan\n'),
      node('thought:three', 'Plan ·abcd'), node('thought:four', 'Plan ·abcd-2')]
    for (const labels of [connectionFullLabels(nodes), connectionDisplayLabels(nodes)]) {
      expect(new Set(labels.values()).size).toBe(nodes.length)
      expect(labels.get('thought:three')).toBe('Plan ·abcd')
      expect(labels.get('thought:four')).toBe('Plan ·abcd-2')
    }
  })
})
