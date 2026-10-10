import { useEffect, useMemo, useRef, useState } from 'react'
import type { AppState } from './domain'
import { createUniversalSearchIndex, searchDocumentsFromAppState, type SearchField, type SearchKind, type SearchResult } from './universalSearch'
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

export function searchResultPreview(result: SearchResult): { text: string; source: string } {
  const field = result.matchedFields[0] ?? Object.keys(result.document.fields)[0] as SearchField | undefined
  const text = field ? result.document.fields[field] ?? '' : ''
  return { text: text.length > 180 ? `${text.slice(0, 177)}…` : text, source: field ? fieldLabel[field] : 'Source' }
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
  const [refresh, setRefresh] = useState(0)
  const input = useRef<HTMLInputElement>(null)
  const navigateRef = useRef(navigate)
  navigateRef.current = navigate
  const index = useMemo(() => createUniversalSearchIndex(searchDocumentsFromAppState(state)), [state, refresh])
  const results = useMemo(() => index.query(query), [index, query])
  useEffect(() => { input.current?.focus() }, [])
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      event.preventDefault()
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
    const outcome = navigate({ type: 'open-search-result', document: result.document, snapshotToken })
    if (!outcome.ok) setMessage(outcome.message)
  }
  return <main className="page universal-search" aria-labelledby="universal-search-title">
    <header className="page-header"><div><p className="eyebrow">One place to find it</p><h1 id="universal-search-title">Search Threadline</h1></div><button type="button" className="secondary" onClick={close} aria-label="Close Search">Close</button></header>
    <label className="universal-search-label" htmlFor="universal-search-query">Search your thoughts</label>
    <input ref={input} id="universal-search-query" type="search" value={query} autoComplete="off" placeholder="Search anything" onChange={event => { setQuery(event.target.value); setVisible(initialVisible); setMessage('') }} />
    {message && <div role="alert" className="universal-search-error"><p>{message}</p><button type="button" className="secondary" onClick={() => { setRefresh(value => value + 1); setMessage('') }}>Refresh results</button></div>}
    {query.trim() ? <section aria-label="Search results">
      <p className="universal-search-count" role="status">{results.length} {results.length === 1 ? 'result' : 'results'}</p>
      {results.length ? <><ul className="universal-search-results">{results.slice(0, visible).map(result => {
        const preview = searchResultPreview(result)
        return <li key={`${result.document.kind}:${result.document.id}`}><button type="button" onClick={() => open(result)} aria-label={`Open ${kindLabel[result.document.kind]}: ${preview.text}`}>
          <span className="universal-search-kind">{kindLabel[result.document.kind]}</span><span className="universal-search-text">{preview.text}</span><small>{preview.source}</small>
        </button></li>
      })}</ul>{visible < results.length && <button type="button" className="secondary" onClick={() => setVisible(count => Math.min(results.length, count * 2))}>Show more results</button>}</> : <p className="empty">No matches. Try another word.</p>}
    </section> : <p className="empty">Find captures, actions, commitments, reminders, ideas, and canvases.</p>}
  </main>
}
