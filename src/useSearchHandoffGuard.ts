import { useLayoutEffect, useRef } from 'react'
import type { RegisterSearchHandoffGuard } from './searchHandoffGuards'

/** Keep child-owned drafts visible to the App's checked Search handoff. */
export function useSearchHandoffGuard(register: RegisterSearchHandoffGuard | undefined, id: string, canLeave: () => boolean): void {
  const latest = useRef(canLeave)
  latest.current = canLeave
  useLayoutEffect(() => register?.(id, () => latest.current()), [register, id])
}
