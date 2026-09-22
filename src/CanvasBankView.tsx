import { useEffect, useRef } from 'react'
import { listCanvases } from './canvasBank'
import type { CanvasBank as CanvasBankModel } from './domain'

export function CanvasBank({ bank, focusTarget, onCreate, onOpen }: {
  bank: CanvasBankModel
  focusTarget: 'create' | string | null
  onCreate: () => void
  onOpen: (id: string) => void
}) {
  const createRef = useRef<HTMLButtonElement>(null)
  const cardRefs = useRef(new Map<string, HTMLButtonElement>())
  const canvases = listCanvases(bank)
  useEffect(() => {
    if (!focusTarget) return
    ;(focusTarget === 'create' ? createRef.current : cardRefs.current.get(focusTarget))?.focus()
  }, [focusTarget])
  return <div className="page canvas-bank-page">
    <header className="canvas-bank-header">
      <div><p className="eyebrow">Visual thinking</p><h1>Canvas Bank</h1><p className="lede">Open a canvas or begin a new space for your ideas.</p></div>
      <button ref={createRef} className="primary canvas-create" onClick={onCreate}>Think visually <span aria-hidden="true">＋</span></button>
    </header>
    {canvases.length === 0 ? <section className="canvas-bank-empty"><h2>Your canvases will live here.</h2><p>Create one to start thinking visually. It saves automatically on this device or in your active account workspace.</p></section> :
      <section className="canvas-bank-grid" aria-label="Saved canvases">{canvases.map(canvas => <button
        ref={element => { if (element) cardRefs.current.set(canvas.id, element); else cardRefs.current.delete(canvas.id) }}
        className="canvas-bank-card" key={canvas.id} onClick={() => onOpen(canvas.id)} aria-label={`Open ${canvas.title}`}>
        <span className="canvas-card-visual" aria-hidden="true"><i/><i/><i/></span>
        <span className="canvas-card-copy"><strong>{canvas.title}</strong><small>{canvas.elements.length} {canvas.elements.length === 1 ? 'block' : 'blocks'}</small><small>{canvas.updatedAt.startsWith('1970-') ? 'Recovered from your original canvas' : `Edited ${new Date(canvas.updatedAt).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })}`}</small></span>
        <span aria-hidden="true">→</span>
      </button>)}</section>}
  </div>
}
