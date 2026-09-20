import { useEffect, useRef, useState } from 'react'
import type { AppState } from './domain'
import { createCanvasRepository } from './canvasRepository'
import { createCanvasSession } from './canvasSession'

export function useCanvasWorkspace(state: AppState, update: (fn: (state: AppState) => AppState) => void, active: boolean) {
  const host = useRef({ state, update })
  host.current = { state, update }
  const [repository] = useState(() => createCanvasRepository(() => host.current.state, fn => host.current.update(current => {
    const next = fn(current)
    host.current.state = next
    return next
  })))
  const [session] = useState(() => createCanvasSession(repository))
  useEffect(() => {
    if (!active) { session.finishText(); return }
    const onKeyDown = (event: KeyboardEvent) => {
      const element = event.target as HTMLElement | null
      if (element?.closest('input, textarea, select, [contenteditable="true"]')) return
      if (!(event.metaKey || event.ctrlKey)) return
      const key = event.key.toLowerCase()
      if (key === 'z' && event.shiftKey || key === 'y') { event.preventDefault(); session.redo() }
      else if (key === 'z') { event.preventDefault(); session.undo() }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [active, session])
  return session
}
