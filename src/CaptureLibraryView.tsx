import { useEffect, useRef, useState, type DragEvent } from 'react'
import type { ThoughtObject } from './domain'
import { captureFolderId, filterCaptureCompletion, isCaptureCompleted, folderDestinations, folderTrail, searchCaptures, type CaptureCompletionFilter, type CaptureLibraryState, type LibraryChange } from './captureLibrary'
import { folderColors, type FolderColor } from './organization'
import './captureLibrary.css'
import { useSearchHandoffGuard } from './useSearchHandoffGuard'
import type { RegisterSearchHandoffGuard } from './searchHandoffGuards'

type FolderEditor = { id: string; name: string; color: FolderColor; emoji: string }
type MoveEditor = { id: string; name: string; destination: string }
type Editor = ({ type: 'create' } & FolderEditor) | ({ type: 'edit' } & FolderEditor)
  | ({ type: 'move-folder' } & MoveEditor) | ({ type: 'move-capture' } & MoveEditor)
const dragType = 'application/x-threadline-library'
type DragItem = { type: 'folder' | 'capture'; id: string }

export function CaptureLibrary({ objects, library, onChange, onOpen, focusRequest = 0, registerSearchHandoffGuard }: {
  objects: readonly ThoughtObject[]; library: CaptureLibraryState; onChange: (change: LibraryChange) => void; onOpen: (id: string) => void; focusRequest?: number; registerSearchHandoffGuard?: RegisterSearchHandoffGuard
}) {
  const [query, setQuery] = useState('')
  const [completion, setCompletion] = useState<CaptureCompletionFilter>('all')
  const [folderId, setFolderId] = useState<string | null>(null)
  const [allCaptures, setAllCaptures] = useState(true)
  const [editor, setEditor] = useState<Editor | null>(null)
  useSearchHandoffGuard(registerSearchHandoffGuard, 'capture-library', () => !editor)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [dragOver, setDragOver] = useState<string | null>(null)
  const search = useRef<HTMLInputElement>(null)
  const firstField = useRef<HTMLInputElement | HTMLSelectElement | null>(null)
  const opener = useRef<HTMLElement | null>(null)
  useEffect(() => { if (focusRequest) { search.current?.focus(); search.current?.scrollIntoView({ block: 'center' }) } }, [focusRequest])
  useEffect(() => { if (editor) firstField.current?.focus() }, [editor?.type, editor?.id])
  const currentFolder = library.folders.find(folder => folder.id === folderId && !folder.tombstone)
  const currentId = currentFolder?.id ?? null
  const trail = folderTrail(library, currentId)
  const searching = query.trim().length > 0
  const results = filterCaptureCompletion(searchCaptures(objects, query, library), library, completion).filter(object => searching || allCaptures || captureFolderId(library, object.id) === currentId)
  const folders = library.folders.filter(folder => !folder.tombstone && folder.parentId === currentId).sort((a, b) => a.name.localeCompare(b.name))
  const openFolder = (id: string | null) => { setFolderId(id); setAllCaptures(false); setQuery(''); setError(''); setEditor(null) }
  const begin = (next: Editor) => {
    const active = document.activeElement as HTMLElement | null
    const menu = active?.closest('details.library-menu')
    const trigger = menu?.querySelector('summary')
    opener.current = trigger instanceof HTMLElement ? trigger : active
    if (menu) menu.removeAttribute('open')
    setEditor(next); setError('')
  }
  const closeEditor = () => { setEditor(null); opener.current?.focus() }
  const apply = (change: LibraryChange, notice: string) => {
    try { onChange(change); setError(''); setMessage(notice); return true }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'The change could not be saved.'); return false }
  }
  const startDrag = (event: DragEvent, item: DragItem) => { event.dataTransfer.setData(dragType, JSON.stringify(item)); event.dataTransfer.effectAllowed = 'move' }
  const targetProps = (id: string | null) => ({
    onDragOver: (event: DragEvent) => {
      if (!event.dataTransfer.types.includes(dragType)) return
      event.preventDefault(); event.dataTransfer.dropEffect = 'move'; setDragOver(id ?? 'root')
    },
    onDragLeave: () => setDragOver(null),
    onDrop: (event: DragEvent) => {
      event.preventDefault(); event.stopPropagation(); setDragOver(null)
      try {
        const item = JSON.parse(event.dataTransfer.getData(dragType)) as DragItem
        if (typeof item.id !== 'string' || !['folder', 'capture'].includes(item.type)) return
        apply(item.type === 'folder' ? { type: 'move-folder', id: item.id, parentId: id } : { type: 'move-capture', id: item.id, folderId: id }, 'Moved. Folder contents and capture history are preserved.')
      } catch { setError('This item could not be moved. Try its Move to menu.') }
    },
  })
  return <section className="capture-library" aria-labelledby="capture-library-heading">
    <div className="library-toolbar"><h2 id="capture-library-heading">Captures</h2><button className="secondary" onClick={() => begin({ type: 'create', id: crypto.randomUUID(), name: '', color: 'slate', emoji: '' })}>+ Folder</button></div>
    <div className="library-completion-filters" role="group" aria-label="Capture completion">{(['all', 'open', 'completed'] as const).map(filter => <button type="button" key={filter} aria-pressed={completion === filter} onClick={() => setCompletion(filter)}>{filter === 'all' ? 'All' : filter === 'open' ? 'Not completed' : 'Completed'}</button>)}</div>
    <div className="library-search"><label htmlFor="capture-search" className="library-sr-only">Search all captures</label><input ref={search} id="capture-search" type="search" placeholder="Search all captures…" value={query} onChange={event => { setQuery(event.target.value); setEditor(null) }} /><button className="secondary" disabled={!query} onClick={() => { setQuery(''); search.current?.focus() }}>Clear</button></div>
    <nav className="library-breadcrumbs" aria-label="Capture folders"><button aria-current={!searching && allCaptures ? 'page' : undefined} onClick={() => { setAllCaptures(true); setFolderId(null); setQuery(''); setEditor(null) }}>All captures</button><span aria-hidden="true">/</span><button {...targetProps(null)} data-drag-over={dragOver === 'root'} aria-current={!searching && !allCaptures && !currentId ? 'page' : undefined} onClick={() => openFolder(null)}>My folders</button>{trail.map(folder => <span className="library-crumb" key={folder.id}><span aria-hidden="true">/</span><button {...targetProps(folder.id)} data-drag-over={dragOver === folder.id} aria-current={!searching && !allCaptures && folder.id === currentId ? 'page' : undefined} onClick={() => openFolder(folder.id)}>{folder.emoji} {folder.name}</button></span>)}</nav>
    {error && <p role="alert" className="library-error">{error}</p>}
    <p role="status" className="library-sr-only">{message}</p>
    {editor && <form className="library-editor" aria-label={editor.type === 'create' ? 'New folder' : editor.type === 'edit' ? 'Edit folder' : 'Move item'} onSubmit={event => {
      event.preventDefault()
      const change: LibraryChange = editor.type === 'create' ? { ...editor, parentId: currentId } : editor.type === 'edit' ? editor : editor.type === 'move-folder' ? { type: 'move-folder', id: editor.id, parentId: editor.destination || null } : { type: 'move-capture', id: editor.id, folderId: editor.destination || null }
      if (apply(change, editor.type.startsWith('move') ? 'Moved.' : 'Folder saved.')) {
        if (editor.type === 'create') { setQuery(''); setAllCaptures(false) }
        closeEditor()
      }
    }}>
      <h3>{editor.type === 'create' ? 'New folder' : editor.type === 'edit' ? 'Edit folder' : `Move “${editor.name}”`}</h3>
      {editor.type === 'create' || editor.type === 'edit' ? <>
        <label>Name<input ref={node => { firstField.current = node }} required maxLength={120} value={editor.name} onChange={event => setEditor({ ...editor, name: event.target.value })} /></label>
        <details open={editor.type === 'edit' || undefined}><summary>Color & emoji</summary><div className="library-appearance"><label>Color<select value={editor.color} onChange={event => setEditor({ ...editor, color: event.target.value as FolderColor })}>{folderColors.map(color => <option key={color} value={color}>{color}</option>)}</select></label><label>Emoji<input aria-label="Folder emoji" placeholder="📁" maxLength={32} value={editor.emoji} onChange={event => setEditor({ ...editor, emoji: event.target.value })} /></label></div></details>
      </> : <label>Destination<select ref={node => { firstField.current = node }} value={editor.destination} onChange={event => setEditor({ ...editor, destination: event.target.value })}><option value="">My folders (top level)</option>{folderDestinations(library, editor.type === 'move-folder' ? editor.id : undefined).map(folder => <option key={folder.id} value={folder.id}>{folderTrail(library, folder.id).map(parent => parent.name).join(' / ')}</option>)}</select></label>}
      <div className="library-editor-actions"><button className="primary">{editor.type.startsWith('move') ? 'Move here' : 'Save folder'}</button><button className="secondary" type="button" onClick={closeEditor}>Cancel</button></div>
    </form>}
    {!searching && <div className="library-folder-grid">{folders.map(folder => <article className="library-folder" key={folder.id} draggable onDragStart={event => startDrag(event, { type: 'folder', id: folder.id })} onDragEnd={() => setDragOver(null)} {...targetProps(folder.id)} data-drag-over={dragOver === folder.id}>
      <button className="library-folder-open" draggable onClick={() => openFolder(folder.id)} aria-label={`Open folder ${folder.name}`}><span className={`library-folder-icon folder-${folder.color ?? 'slate'}`} aria-hidden="true">{folder.emoji || '📁'}</span><span>{folder.name}</span></button>
      <details className="library-menu"><summary aria-label={`Options for folder ${folder.name}`}>⋯</summary><div><button onClick={() => begin({ type: 'edit', id: folder.id, name: folder.name, color: folder.color ?? 'slate', emoji: folder.emoji ?? '' })}>Rename / customize</button><button onClick={() => begin({ type: 'move-folder', id: folder.id, name: folder.name, destination: folder.parentId ?? '' })}>Move to…</button></div></details>
    </article>)}</div>}
    <p className="library-result-count" role="status">{searching ? `${results.length} ${results.length === 1 ? 'result' : 'results'} across all captures` : allCaptures ? `${results.length} captures · all folders` : `${results.length} ${results.length === 1 ? 'capture' : 'captures'}${currentId ? ' in this folder' : ' not in a folder'}`}</p>
    <div className="library-captures">{results.map(object => <article className="library-capture" key={object.id} draggable onDragStart={event => startDrag(event, { type: 'capture', id: object.id })}>
      <button className="library-capture-open" draggable onClick={() => onOpen(object.id)}><strong>{object.currentContent ?? object.originalContent}</strong>{searching && object.currentContent && object.currentContent !== object.originalContent && <small>Original: {object.originalContent}</small>}<small>{folderTrail(library, captureFolderId(library, object.id)).map(folder => folder.name).join(' / ') || 'Unfiled'} · {object.status} · {new Date(object.createdAt).toLocaleDateString()}</small></button>
      <div className="library-capture-actions"><button type="button" className="library-done" aria-label={`${isCaptureCompleted(library, object) ? 'Reopen' : 'Mark completed'}: ${object.currentContent ?? object.originalContent}`} aria-pressed={isCaptureCompleted(library, object)} onClick={() => apply({ type: 'complete-capture', id: object.id, completed: !isCaptureCompleted(library, object) }, isCaptureCompleted(library, object) ? 'Capture reopened.' : 'Capture marked completed. Linked actions and events are unchanged.')}>{isCaptureCompleted(library, object) ? 'Reopen' : 'Done'}</button><button className="library-move" aria-label={`Move capture ${object.currentContent ?? object.originalContent}`} title="Move to folder" onClick={() => begin({ type: 'move-capture', id: object.id, name: object.currentContent ?? object.originalContent, destination: captureFolderId(library, object.id) ?? '' })}>↗</button></div>
    </article>)}</div>
    {!results.length && <p className="library-empty">{searching ? 'No captures match. Try fewer words or Clear to browse.' : 'No captures here yet. Move one here from All captures.'}</p>}
  </section>
}
