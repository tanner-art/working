const clamp = (value: number) => Math.min(1, Math.max(0, Number.isFinite(value) ? value : 0))
/** Native scrolling moves the entire world. This only remembers position for navigation. */
export function observeJourney(root: HTMLElement, view: Window = window, initialProgress = 0, onProgress?: (value: number) => void) {
  const preference = view.matchMedia('(prefers-reduced-motion: reduce)')
  let frame = 0
  let disposed = false
  let progress = clamp(initialProgress)
  const paint = () => {
    frame = 0
    if (disposed) return
    const max = root.scrollHeight - root.clientHeight
    progress = max > 0 ? clamp(1 - root.scrollTop / max) : 0
    root.dataset.motion = preference.matches ? 'still' : 'scroll'
    onProgress?.(progress)
  }
  const schedule = () => { if (!disposed && !frame) frame = view.requestAnimationFrame(paint) }
  const resize = () => {
    root.scrollTop = Math.max(0, root.scrollHeight - root.clientHeight) * (1 - progress)
    schedule()
  }
  root.scrollTop = Math.max(0, root.scrollHeight - root.clientHeight) * (1 - progress)
  root.addEventListener('scroll', schedule, { passive: true })
  view.addEventListener('resize', resize, { passive: true })
  preference.addEventListener('change', schedule)
  paint()
  return () => {
    disposed = true
    if (frame) view.cancelAnimationFrame(frame)
    root.removeEventListener('scroll', schedule)
    view.removeEventListener('resize', resize)
    preference.removeEventListener('change', schedule)
  }
}
