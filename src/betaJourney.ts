const clamp = (value: number) => Math.min(1, Math.max(0, Number.isFinite(value) ? value : 0))
const easeBetween = (start: number, end: number, value: number) => {
  const t = clamp((value - start) / (end - start))
  return t * t * (3 - 2 * t)
}

export function journeyFrame(progress: number) {
  const p = clamp(progress)
  return {
    '--journey-sky-opacity': String(1 - easeBetween(.18, .72, p)),
    '--journey-ground-opacity': String(easeBetween(.14, .62, p)),
    '--journey-cloud-opacity': String(1 - easeBetween(.25, .82, p)),
    '--journey-sky-y': `${-14 * p}svh`,
    '--journey-cloud-y': `${-36 * p}svh`,
    '--journey-ground-y': `${18 * (1 - easeBetween(.12, 1, p))}svh`,
    '--journey-wordmark-opacity': String(1 - easeBetween(.05, .3, p)),
    '--journey-wordmark-y': `${-18 * p}svh`,
  }
}

/** One passive listener and at most one pending paint; no React renders or perpetual RAF loop. */
export function observeJourney(root: HTMLElement, view: Window = window) {
  const preference = view.matchMedia('(prefers-reduced-motion: reduce)')
  let frame = 0
  let disposed = false
  const paint = () => {
    frame = 0
    if (disposed) return
    root.dataset.motion = preference.matches ? 'still' : 'scroll'
    if (preference.matches) return
    const start = root.getBoundingClientRect().top
    const destination = root.querySelector<HTMLElement>('[data-journey-ground]')
    if (!destination) return
    const distance = destination.getBoundingClientRect().top - start
    const values = journeyFrame(distance > 0 ? -start / distance : 0)
    for (const [key, value] of Object.entries(values)) root.style.setProperty(key, value)
  }
  const schedule = () => {
    if (!disposed && !frame) frame = view.requestAnimationFrame(paint)
  }
  const preferenceChanged = () => {
    if (frame) view.cancelAnimationFrame(frame)
    frame = 0
    paint()
  }
  view.addEventListener('scroll', schedule, { passive: true })
  view.addEventListener('resize', schedule, { passive: true })
  preference.addEventListener('change', preferenceChanged)
  paint() // Includes restored scroll positions and direct #join visits.
  return () => {
    disposed = true
    if (frame) view.cancelAnimationFrame(frame)
    view.removeEventListener('scroll', schedule)
    view.removeEventListener('resize', schedule)
    preference.removeEventListener('change', preferenceChanged)
  }
}
