import { useEffect, useMemo, useState } from 'react'
import type { AppState } from './domain'
import { reconcileLegacyUi } from './migration'
import { buildMorningDigest, localDateKey } from './morningDigest'
import { DIGEST_DELIVERY_KEY, digestIsDue, disabledDelivery, readDelivery, setDeliveryEnabled } from './digestDelivery'

export function MorningDigest({ state, visible, onShow, inline = false }: { state: AppState; visible: boolean; onShow: () => void; inline?: boolean }) {
  const [now, setNow] = useState(() => new Date())
  const [error, setError] = useState('')
  const [settings, setSettings] = useState(disabledDelivery)
  const [readyDay, setReadyDay] = useState<string>()
  const [expanded, setExpanded] = useState(false)
  const model = useMemo(() => reconcileLegacyUi(state), [state])
  const digest = useMemo(() => buildMorningDigest(model, now), [model, now])
  useEffect(() => {
    const tick = () => setNow(new Date())
    const sync = () => {
      try { setSettings(readDelivery(localStorage)); setError('') }
      catch { setError('Digest settings could not be read. Delivery is paused.'); setSettings(disabledDelivery) }
      tick()
    }
    sync()
    const timer = window.setInterval(tick, 15000)
    window.addEventListener('focus', sync)
    window.addEventListener('storage', sync)
    document.addEventListener('visibilitychange', sync)
    return () => {
      clearInterval(timer)
      window.removeEventListener('focus', sync)
      window.removeEventListener('storage', sync)
      document.removeEventListener('visibilitychange', sync)
    }
  }, [])
  useEffect(() => {
    if (!digestIsDue(settings, now, document.visibilityState === 'visible')) return
    try {
      // Re-read to respect another tab's delivery/disable before publishing this notice.
      const latest = readDelivery(localStorage)
      if (!digestIsDue(latest, now, true)) { setSettings(latest); return }
      const delivered = { ...latest, deliveredDay: localDateKey(now) }
      localStorage.setItem(DIGEST_DELIVERY_KEY, JSON.stringify(delivered))
      setSettings(delivered)
      setReadyDay(delivered.deliveredDay)
    } catch { setError('Digest delivery could not be saved. Delivery is paused until settings can be saved.'); setSettings(disabledDelivery) }
  }, [settings, now])
  const toggle = () => {
    try {
      const next = setDeliveryEnabled(settings, !settings.enabled, new Date())
      localStorage.setItem(DIGEST_DELIVERY_KEY, JSON.stringify(next))
      setSettings(next); setError(''); setNow(new Date()); setReadyDay(undefined)
    } catch { setError('Digest settings could not be saved. Your delivery preference has not changed.') }
  }
  return <section className={inline ? "digest-panel digest-inline" : "digest-panel"} aria-label="Morning digest">
    {!inline && readyDay === digest.day && <div role="status"><strong>Your morning digest is ready.</strong> <button className="secondary" onClick={() => { onShow(); setExpanded(true); setReadyDay(undefined) }}>Read digest</button></div>}
    {visible && <>
      {!inline && <><h2>Morning digest</h2>
      <p>7 AM in your device’s local time. Appears here while Threadline is open, or when you return after 7 AM. No notification is sent while the app is closed.</p>
      <button className="secondary" onClick={toggle}>{settings.enabled ? 'Disable 7 AM in-app digest' : 'Enable 7 AM in-app digest'}</button>
      <button className="secondary" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>{expanded ? 'Hide digest' : 'View digest'}</button></>}
      {(inline || expanded) && <div>
        <p>{digest.day} · Live summary</p>
        <h3>Confirmed events today</h3>
        <ul>{digest.fixedToday.map(({ event, commitments }) => <li key={event.id}>{event.title} — {new Date(event.startsAt).toLocaleTimeString()} (device time) · {event.temporalContext}{commitments.map(o => <span key={o.id}> · Obligation: {o.summary}</span>)}</li>)}</ul>
        {!digest.fixedToday.length && <p>No separately confirmed events today.</p>}
        <h3>Fixed deadlines</h3>
        <p>Up to three confirmed deadlines, earliest first, including overdue dates. Date-only constraints do not reserve calendar time.</p>
        <ul>{digest.upcoming.map(o => <li key={o.id}>{o.summary} — {o.metadata.deadline}</li>)}</ul>
        {!digest.upcoming.length && <p>No separately confirmed deadlines to surface.</p>}
        <h3>Confirmed obligations — schedule unverified</h3><ul>{digest.unscheduledCommitments.map(o => <li key={o.id}>{o.summary}</li>)}</ul>
        {!digest.unscheduledCommitments.length && <p>No confirmed obligations to surface.</p>}
        <h3>Recommended execution</h3><p>Up to three confirmed actions, ordered by recorded strategic importance. Known unfinished dependencies are excluded.</p><ul>{digest.recommended.map(o => <li key={o.id}>{o.summary}</li>)}</ul>
        {!digest.recommended.length && <p>No eligible confirmed actions.</p>}
        <h3>Decisions needed</h3><ul>{digest.needsReview.map(i => <li key={i.id}>{i.summary}{i.proposedReminder && ' — reminder timing or target needs review'}</li>)}</ul>
        {!digest.needsReview.length && <p>No decisions waiting.</p>}
        <h3>Project and objective status</h3><ul>{digest.projectSignals.map(o => <li key={o.id}>{o.summary} — {o.status}</li>)}</ul>
        {!digest.projectSignals.length && <p>No project or objective signals.</p>}
      </div>}
    </>}
    {!inline && error && <p role="alert">{error}</p>}
  </section>
}
