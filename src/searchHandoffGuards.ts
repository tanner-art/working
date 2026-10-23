export type RegisterSearchHandoffGuard = (id: string, canLeave: () => boolean) => () => void

/** Child editors own their drafts; Search only asks whether each mounted editor can leave. */
export function createSearchHandoffGuards(): { register: RegisterSearchHandoffGuard; canLeave: () => boolean } {
  const guards = new Map<string, () => boolean>()
  return {
    register: (id, guard) => {
      guards.set(id, guard)
      return () => { if (guards.get(id) === guard) guards.delete(id) }
    },
    canLeave: () => [...guards.values()].every(guard => guard()),
  }
}
