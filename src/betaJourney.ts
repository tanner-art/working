const clamp = (value: number) => Math.min(1, Math.max(0, Number.isFinite(value) ? value : 0))
const easeBetween = (start: number, end: number, value: number) => {
  const t = clamp((value - start) / (end - start))
  return t * t * (3 - 2 * t)
}

/** Progress increases as native scrollTop decreases: ground at bottom, stars at top. */
export function journeyFrame(progress: number, reduced = false) {
  const p = clamp(progress)
  return {
    '--ascent-ground-opacity': String(1 - easeBetween(.08, .24, p)),
    '--ascent-ground-scale': String(reduced ? 1 : 1 + .12 * easeBetween(0, .25, p)),
    '--ascent-mountain-opacity': String(easeBetween(.05, .24, p) * (1 - easeBetween(.42, .64, p))),
    '--ascent-mountain-y': `${reduced ? 0 : Math.min(8, (p - .27) * 35)}svh`,
    '--ascent-sky-opacity': String(easeBetween(.32, .5, p) * (1 - easeBetween(.66, .88, p))),
    '--ascent-cloud-opacity': String(easeBetween(.35, .53, p) * (1 - easeBetween(.7, .93, p))),
    '--ascent-cloud-y': `${reduced ? 0 : (p - .55) * 75}svh`,
    '--ascent-stars-opacity': String(easeBetween(.65, .94, p)),
    '--ascent-prize-opacity': String(easeBetween(.87, .98, p)),
  }
}

export function moveJourney(root: HTMLElement, direction: 'up' | 'ground', view: Window = window) {
  const max = Math.max(0, root.scrollHeight - root.clientHeight)
  root.scrollTo({ top: direction === 'ground' ? max : Math.max(0, root.scrollTop - max / 4), behavior: view.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' })
}

/** Passive native scrolling; one pending paint, no input interception or perpetual RAF. */
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
    root.dataset.summit = String(progress >= .9)
    for (const [key, value] of Object.entries(journeyFrame(progress, preference.matches))) root.style.setProperty(key, value)
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
