import { useEffect, useMemo, useRef, useState } from 'react'
import type { AppState } from './domain'
import { createUniversalSearchIndex, searchProjectionFromAppState, type SearchField, type SearchKind, type SearchResult } from './universalSearch'
import type { WorkspaceNavigationOutcome, WorkspaceNavigationRequest } from './workspaceNavigation'
import './universalSearch.css'

const kindLabel: Record<SearchKind, string> = {
  capture: 'Capture', action: 'Action', commitment: 'Commitment', reminder: 'Reminder', idea: 'Idea', canvas: 'Canvas',
}
const fieldLabel: Record<SearchField, string> = {
  original: 'Original capture', 'corrected-source': 'Corrected source', 'current-meaning': 'Current meaning',
  'reminder-source': 'Reminder source', 'canvas-title': 'Canvas title', 'canvas-element': 'Canvas content',
}
const initialVisible = 40
export const nextVisibleSearchCount = (current: number, total: number) => Math.min(total, current * 2)

export function searchResultPreview(result: SearchResult, query = ''): { text: string; source: string } {
  const field = result.matchedFields[0] ?? Object.keys(result.document.fields)[0] as SearchField | undefined
  const text = field ? result.document.fields[field] ?? '' : ''
  const firstTerm = query.trim().split(/\s+/)[0]?.toLocaleLowerCase() ?? ''
  const matchAt = firstTerm ? text.toLocaleLowerCase().indexOf(firstTerm) : -1
  const start = matchAt > 48 ? matchAt - 48 : 0
  const excerpt = text.slice(start, start + 177)
  return { text: `${start ? '…' : ''}${excerpt}${start + 177 < text.length ? '…' : ''}`, source: field ? fieldLabel[field] : 'Source' }
}

export function searchEscapeAction(composing: boolean, hasQuery: boolean): 'ignore' | 'clear' | 'close' {
  return composing ? 'ignore' : hasQuery ? 'clear' : 'close'
}

export function openSearchResult(result: SearchResult, snapshotToken: string,
  navigate: (request: WorkspaceNavigationRequest) => WorkspaceNavigationOutcome): WorkspaceNavigationOutcome {
  return navigate({ type: 'open-search-result', document: result.document, snapshotToken })
}

/** The sole global text-search surface. The source model remains the authority on every click. */
export function GlobalSearchView({ state, snapshotToken, navigate, initialQuery = '' }: {
  state: AppState
  snapshotToken: string
  navigate: (request: WorkspaceNavigationRequest) => WorkspaceNavigationOutcome
  initialQuery?: string
}) {
  const [query, setQuery] = useState(initialQuery)
  const [visible, setVisible] = useState(initialVisible)
  const [message, setMessage] = useState('')
  const navigateRef = useRef(navigate)
  navigateRef.current = navigate
  const queryRef = useRef(query)
  queryRef.current = query
  const projection = useMemo(() => searchProjectionFromAppState(state), [state])
  const index = useMemo(() => createUniversalSearchIndex(projection.documents), [projection])
  const incomplete = !projection.complete || index.omittedCount > 0
  const results = useMemo(() => index.query(query), [index, query])
  useEffect(() => { setMessage('') }, [state])
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      const action = searchEscapeAction(event.isComposing || event.keyCode === 229, !!queryRef.current.trim())
      if (action === 'ignore') return
      event.preventDefault()
      if (action === 'clear') { setQuery(''); setVisible(initialVisible); setMessage(''); return }
      const outcome = navigateRef.current({ type: 'close-surface' })
      if (!outcome.ok) setMessage(outcome.message)
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [])
  const close = () => {
    const outcome = navigate({ type: 'close-surface' })
    if (!outcome.ok) setMessage(outcome.message)
  }
  const open = (result: SearchResult) => {
    const outcome = openSearchResult(result, snapshotToken, navigate)
    if (!outcome.ok) setMessage(outcome.message)
  }
  return <main className="page universal-search" aria-labelledby="universal-search-title">
    <header className="page-header"><div><p className="eyebrow">One place to find it</p><h1 id="universal-search-title">Search Threadline</h1></div><button type="button" className="secondary" onClick={close} aria-label="Close Search">Close</button></header>
    <label className="universal-search-label" htmlFor="universal-search-query">Search your thoughts</label>
    <input autoFocus id="universal-search-query" type="search" value={query} autoComplete="off" placeholder="Search anything" onChange={event => { setQuery(event.target.value); setVisible(initialVisible); setMessage('') }} />
    {message && <p role="alert" className="universal-search-error">{message} Reopen Search after checking your account and saved workspace.</p>}
    {incomplete && <p role="alert" className="universal-search-error">Some items could not be indexed, so these results may be incomplete.</p>}
    <p className="universal-search-count" role="status" aria-live="polite">{query.trim() ? `${results.length} ${results.length === 1 ? 'matching item' : 'matching items'}${incomplete ? ' shown; results may be incomplete' : ''}` : 'Enter a search term.'}</p>
    {query.trim() ? <section aria-label="Search results">
      {results.length ? <><ul className="universal-search-results">{results.slice(0, visible).map(result => {
        const preview = searchResultPreview(result, query)
        return <li key={`${result.document.kind}:${result.document.id}`}><button type="button" onClick={() => open(result)} aria-label={`Open ${kindLabel[result.document.kind]} from ${preview.source}: ${preview.text}`}>
          <span className="universal-search-kind">{kindLabel[result.document.kind]}</span><span className="universal-search-text">{preview.text}</span><small>{preview.source}</small>
        </button></li>
      })}</ul>{visible < results.length && <button type="button" className="secondary" onClick={() => setVisible(count => nextVisibleSearchCount(count, results.length))}>Show more results</button>}</> : <p className="empty">{incomplete ? 'No indexed matches. Some items could not be searched.' : 'No matches. Try another word.'}</p>}
    </section> : <p className="empty">Find captures, actions, commitments, reminders, ideas, and canvases.</p>}
  </main>
}
