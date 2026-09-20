/** Coalesce account writes while canvas text changes, retaining only the latest snapshot. */
export function createCanvasTextSaveQueue(save: (retry: boolean) => Promise<boolean>, delayMs = 600) {
  let timer: ReturnType<typeof setTimeout> | undefined
  let dirty = false
  let editingUpdate = false
  let inFlight = false
  let stopped = false

  const clearTimer = () => { if (timer !== undefined) clearTimeout(timer); timer = undefined }
  const drain = async (retry = false): Promise<void> => {
    clearTimer()
    if (stopped || !dirty || inFlight) return
    dirty = false
    inFlight = true
    let saved = false
    try { saved = await save(retry) } catch { /* Keep the latest edit for retry/export. */ }
    inFlight = false
    if (!saved) { dirty = true; return } // preserve work for an explicit retry/export
    if (dirty) void drain()
  }
  const schedule = () => {
    clearTimer()
    timer = setTimeout(() => { void drain() }, delayMs)
  }
  return {
    edited() { dirty = true; editingUpdate = true; schedule() },
    /** A related state update is covered by the pending latest-snapshot save. */
    consumeStateUpdate(): boolean {
      if (editingUpdate) { editingUpdate = false; return true }
      if (dirty || inFlight) { dirty = true; if (!inFlight) schedule(); return true }
      return false
    },
    flush() { void drain() },
    retry() { void drain(true) },
    hasUnsent() { return dirty || timer !== undefined },
    hasPending() { return dirty || inFlight || timer !== undefined },
    dispose() { stopped = true; clearTimer() },
  }
}
