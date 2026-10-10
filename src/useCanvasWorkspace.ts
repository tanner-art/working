import { useEffect, useRef } from 'react'
import type { AppState } from './domain'
import { createCanvasRepository } from './canvasRepository'
import { createCanvasSession } from './canvasSession'

export function handleCanvasShortcut(event: KeyboardEvent, session: Pick<ReturnType<typeof createCanvasSession>, 'undo' | 'redo'>, enabled: boolean): void {
  if (!enabled) return
  const element = event.target as HTMLElement | null
  if (element?.closest('input, textarea, select, [contenteditable="true"]')) return
  if (!(event.metaKey || event.ctrlKey)) return
  const key = event.key.toLowerCase()
  if (key === 'z' && event.shiftKey || key === 'y') { event.preventDefault(); session.redo() }
  else if (key === 'z') { event.preventDefault(); session.undo() }
}

export function useCanvasWorkspace(state: AppState, update: (fn: (state: AppState) => AppState) => void, canvasId: string | null, shortcutsEnabled = true) {
  const host = useRef({ state, update })
  host.current = { state, update }
  const sessions = useRef(new Map<string, ReturnType<typeof createCanvasSession>>())
  let session = canvasId ? sessions.current.get(canvasId) : undefined
  if (canvasId && !session) {
    const repository = createCanvasRepository(canvasId, () => host.current.state, fn => host.current.update(current => {
      const next = fn(current)
      host.current.state = next
      return next
    }))
    session = createCanvasSession(repository)
    sessions.current.set(canvasId, session)
  }
  useEffect(() => {
    if (!session || !shortcutsEnabled) return
    const onKeyDown = (event: KeyboardEvent) => handleCanvasShortcut(event, session, shortcutsEnabled)
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [session, shortcutsEnabled])
  return session
}
