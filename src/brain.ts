import type { AppState, PersistedState } from './domain'
import { reconcileCurrentSession } from './store'
import { captureLibraryFor, folderTrail } from './captureLibrary'
import { createUniversalSearchIndex, searchProjectionFromAppState, type SearchDocument, type SearchKind } from './universalSearch'

export const brainKindLabels: Record<SearchKind, string> = { capture: 'Captures', action: 'Actions', commitment: 'Commitments', reminder: 'Reminders', idea: 'Ideas', canvas: 'Canvases' }
export const brainKey = (document: SearchDocument) => `${document.kind}:${document.id}`
export const brainTitle = (document: SearchDocument) => document.fields['current-meaning'] || document.fields['canvas-title'] || document.fields['corrected-source'] || document.fields.original || document.fields['reminder-source'] || 'Untitled'
export interface BrainNode { id: string; title: string; group: string; groupLabel: string; document: SearchDocument }
export interface BrainLink { source: string; target: string; label: string }
export interface BrainModel { nodes: BrainNode[]; links: BrainLink[]; incomplete: boolean }

/** Read-only view of actual source, membership and confirmed relationships. No inferred meaning is saved. */
export function buildBrain(state: AppState, readModel: (state: AppState) => PersistedState = reconcileCurrentSession): BrainModel {
  try {
    const model = readModel(state)
    const projection = searchProjectionFromAppState(state, () => model)
    const index = createUniversalSearchIndex(projection.documents)
    const library = captureLibraryFor(state.objects, model.captureLibrary ?? state.captureLibrary)
    const folders = new Map(library.placements.filter(p => p.folderId).map(p => [
      `capture:${p.id}`, { id: `folder:${p.folderId}`, label: folderTrail(library, p.folderId).map(f => `${f.emoji ? `${f.emoji} ` : ''}${f.name}`).join(' / ') },
    ]))
    const nodes = projection.documents.map(document => {
      const folder = document.captureIds.map(id => folders.get(id)).find(Boolean)
      return { id: brainKey(document), title: brainTitle(document), group: folder?.id || `kind:${document.kind}`,
        groupLabel: folder?.label || brainKindLabels[document.kind], document }
    })
    const ids = new Set(nodes.map(n => n.id))
    const semantic = new Map(nodes.filter(n => !['capture', 'canvas', 'reminder'].includes(n.document.kind)).map(n => [n.document.id, n.id]))
    const links: BrainLink[] = []
    const seen = new Set<string>()
    const add = (source: string | undefined, target: string | undefined, label: string) => {
      if (!source || !target || source === target || !ids.has(source) || !ids.has(target)) return
      const key = [source, target].sort().join('\u0000') + label
      if (!seen.has(key)) { seen.add(key); links.push({ source, target, label }) }
    }
    for (const node of nodes) {
      if (node.document.kind !== 'capture') for (const id of node.document.captureIds) add(`capture:${id}`, node.id, 'Source capture')
      if (node.document.targetId) add(node.id, semantic.get(node.document.targetId), 'Reminds you about')
    }
    for (const link of model.relationships) if (link.provenance.evidence === 'user-confirmed') add(semantic.get(link.sourceId), semantic.get(link.targetId), link.type.replaceAll('_', ' '))
    for (const link of model.groupingReview?.relationships ?? []) add(`capture:${link.sourceCaptureId}`, `capture:${link.targetCaptureId}`, 'Confirmed connection')
    return { nodes, links, incomplete: !projection.complete || index.omittedCount > 0 }
  } catch { return { nodes: [], links: [], incomplete: true } }
}

export function filterBrain(model: BrainModel, query: string, group: string): BrainModel {
  const matches = query.trim() ? new Set(createUniversalSearchIndex(model.nodes.map(n => n.document)).query(query).map(r => brainKey(r.document))) : undefined
  const nodes = model.nodes.filter(n => (!group || n.group === group) && (!matches || matches.has(n.id)))
  const ids = new Set(nodes.map(n => n.id))
  return { ...model, nodes, links: model.links.filter(l => ids.has(l.source) && ids.has(l.target)) }
}

/** Stable clusters without a perpetual force-simulation or per-frame React work. */
export function layoutBrain(nodes: readonly BrainNode[], viewportWidth = 960) {
  const groups = [...new Set(nodes.map(n => n.group))]
  const positions = new Map<string, { x: number; y: number }>()
  const columns = Math.max(1, Math.min(Math.floor(viewportWidth / 320), Math.ceil(Math.sqrt(groups.length))))
  const cell = Math.max(320, viewportWidth / columns, ...groups.map(group => 110 + 120 * Math.sqrt(nodes.filter(n => n.group === group).length)))
  groups.forEach((group, index) => {
    const members = nodes.filter(n => n.group === group)
    members.forEach((node, i) => {
      const angle = i * 2.399963229728653
      const radius = 60 * Math.sqrt(i)
      positions.set(node.id, { x: cell / 2 + index % columns * cell + Math.cos(angle) * radius, y: cell / 2 + Math.floor(index / columns) * cell + Math.sin(angle) * radius })
    })
  })
  return { positions, width: columns * cell, height: Math.max(1, Math.ceil(groups.length / columns)) * cell }
}
