import { useEffect, useRef } from 'react'

/** Flush local work before hiding/leaving. Account writes must finish before exit. */
export function useWorkspaceExitGuard(flush: () => boolean) {
  const latest = useRef(flush)
  latest.current = flush
  useEffect(() => {
    const hidden = () => { if (document.visibilityState === 'hidden') latest.current() }
    const pagehide = () => { latest.current() }
    const beforeunload = (event: BeforeUnloadEvent) => {
      if (latest.current()) { event.preventDefault(); event.returnValue = '' }
    }
    document.addEventListener('visibilitychange', hidden)
    window.addEventListener('pagehide', pagehide)
    window.addEventListener('beforeunload', beforeunload)
    return () => {
      document.removeEventListener('visibilitychange', hidden)
      window.removeEventListener('pagehide', pagehide)
      window.removeEventListener('beforeunload', beforeunload)
    }
  }, [])
}
