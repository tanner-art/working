import { useEffect, useMemo, useState } from 'react'
import type { AppState } from './domain'
import { buildBetaHomeSnapshot, type BetaHomeDestination } from './betaHomeState'

type BetaHomeProps = {
  state: AppState
  displayName: string
  onNavigate: (destination: BetaHomeDestination) => void
  /** Deterministic rendering hook for tests and static previews. */
  now?: Date
}

const featureLinks: { destination: BetaHomeDestination; eyebrow: string; title: string; description: string; icon: string }[] = [
  { destination: 'capture', eyebrow: 'Start here', title: 'Capture', description: 'Put down a thought before deciding what it is.', icon: '＋' },
  { destination: 'review', eyebrow: 'Decide', title: 'Review', description: 'Confirm proposed meaning and keep uncertain work visible.', icon: '◇' },
  { destination: 'calendar', eyebrow: 'See time', title: 'Calendar', description: 'View confirmed events and proposed timing separately.', icon: '▦' },
  { destination: 'canvas', eyebrow: 'Think spatially', title: 'Bank', description: 'Open saved canvases or start a new visual workspace.', icon: '⌁' },
  { destination: 'settings', eyebrow: 'Make it yours', title: 'Settings', description: 'Manage your account, data, install, and recovery controls.', icon: '⚙' },
]

function EmptyDigestLine({ children }: { children: React.ReactNode }) {
  return <p className="beta-digest-empty">{children}</p>
}

export function BetaHome({ state, displayName, onNavigate, now: fixedNow }: BetaHomeProps) {
  const [now, setNow] = useState(() => fixedNow ?? new Date())
  useEffect(() => {
    if (fixedNow) { setNow(fixedNow); return }
    const refresh = () => setNow(new Date())
    const timer = window.setInterval(refresh, 60_000)
    window.addEventListener('focus', refresh)
    const visible = () => { if (document.visibilityState === 'visible') refresh() }
    document.addEventListener('visibilitychange', visible)
    return () => { window.clearInterval(timer); window.removeEventListener('focus', refresh); document.removeEventListener('visibilitychange', visible) }
  }, [fixedNow])
  const snapshot = useMemo(() => buildBetaHomeSnapshot(state, now), [state, now])
  const { digest } = snapshot
  const date = new Intl.DateTimeFormat(undefined, { weekday: 'long', month: 'long', day: 'numeric' }).format(now)
  const greeting = displayName.trim() ? `Welcome back, ${displayName.trim()}.` : 'Welcome to your workspace.'

  return <div className="beta-home">
    <header className="beta-home-hero">
      <div>
        <p className="beta-preview-label">Secondary home · Preview</p>
        <p className="beta-home-date">{date}</p>
        <h1>{greeting}</h1>
        <p className="beta-home-lede">A calmer place to capture what is present, review what needs a decision, and return to ideas when they are useful.</p>
      </div>
      <div className="beta-home-actions">
        <button className="beta-primary-action" onClick={() => onNavigate('capture')}>Capture a thought <span aria-hidden="true">↗</span></button>
        <button className="beta-secondary-action" onClick={() => onNavigate('today')}>Return to Today</button>
      </div>
    </header>

    <section className="beta-snapshot" aria-labelledby="workspace-snapshot-title">
      <div className="beta-section-heading">
        <div><p className="beta-kicker">From your workspace</p><h2 id="workspace-snapshot-title">What is here now</h2></div>
        <p>Counts reflect saved items in this open workspace.</p>
      </div>
      <div className="beta-stat-grid">
        <button onClick={() => onNavigate('review')}><strong>{snapshot.reviewCount}</strong><span>waiting for review</span></button>
        <button onClick={() => onNavigate('review')}><strong>{snapshot.bankCount}</strong><span>organized thoughts</span></button>
        <button onClick={() => onNavigate('canvas')}><strong>{snapshot.canvasBlockCount}</strong><span>canvas blocks</span></button>
        <button onClick={() => onNavigate('capture')}><strong>{snapshot.capturedCount}</strong><span>captured thoughts</span></button>
      </div>
    </section>

    <section className="beta-digest" aria-labelledby="daily-digest-title">
      <div className="beta-digest-intro">
        <p className="beta-kicker">Daily digest · {digest.day}</p>
        <h2 id="daily-digest-title">A clear view of today.</h2>
        <p>This view only surfaces confirmed work, confirmed timing, and decisions already present in your workspace.</p>
        <div className="beta-digest-actions">
          <button className="beta-primary-action" onClick={() => onNavigate('review')}>{snapshot.reviewCount ? `Review ${snapshot.reviewCount} ${snapshot.reviewCount === 1 ? 'decision' : 'decisions'}` : 'Open Organize'}</button>
          <button className="beta-secondary-action" onClick={() => onNavigate('digest')}>Open classic digest</button>
        </div>
      </div>
      <div className="beta-digest-board">
        <article className="beta-digest-card beta-digest-card-featured">
          <p className="beta-kicker">Confirmed work available</p>
          {digest.recommended.length ? <ul>{digest.recommended.map(item => <li key={item.id}>{item.summary}</li>)}</ul> : <EmptyDigestLine>No confirmed action is ready to surface.</EmptyDigestLine>}
        </article>
        <article className="beta-digest-card">
          <div className="beta-card-heading"><h3>Calendar today</h3><button onClick={() => onNavigate('calendar')}>Open</button></div>
          {digest.fixedToday.length ? <ul>{digest.fixedToday.map(({ event, commitments }) => <li key={event.id}><time dateTime={event.startsAt}>{new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' }).format(new Date(event.startsAt))}</time><span>{event.title}</span>{commitments.map(item => <small key={item.id}>Obligation: {item.summary}</small>)}</li>)}</ul> : <EmptyDigestLine>No separately confirmed events today.</EmptyDigestLine>}
        </article>
        <article className="beta-digest-card">
          <div className="beta-card-heading"><h3>Decisions waiting</h3><button onClick={() => onNavigate('review')}>Review</button></div>
          {digest.needsReview.length ? <ul>{digest.needsReview.map(item => <li key={item.id}>{item.summary}</li>)}</ul> : <EmptyDigestLine>No decisions are waiting.</EmptyDigestLine>}
        </article>
        <article className="beta-digest-card">
          <div className="beta-card-heading"><h3>Projects and objectives</h3><button onClick={() => onNavigate('review')}>Open</button></div>
          {digest.projectSignals.length ? <ul>{digest.projectSignals.map(item => <li key={item.id}><span>{item.summary}</span><small>Status: {item.status}</small></li>)}</ul> : <EmptyDigestLine>No confirmed project or objective signals.</EmptyDigestLine>}
        </article>
        <article className="beta-digest-card">
          <div className="beta-card-heading"><h3>Dates and obligations</h3><button onClick={() => onNavigate('calendar')}>Calendar</button></div>
          {digest.upcoming.length || digest.unscheduledCommitments.length ? <ul>
            {digest.upcoming.map(item => <li key={`deadline-${item.id}`}><span>{item.summary}</span><small>Deadline {item.metadata.deadline}</small></li>)}
            {digest.unscheduledCommitments.map(item => <li key={`commitment-${item.id}`}><span>{item.summary}</span><small>Confirmed obligation · time not verified</small></li>)}
          </ul> : <EmptyDigestLine>No confirmed deadlines or unscheduled obligations to surface.</EmptyDigestLine>}
        </article>
      </div>
    </section>

    <section className="beta-feature-section" aria-labelledby="workspace-tools-title">
      <div className="beta-section-heading"><div><p className="beta-kicker">Your workspace</p><h2 id="workspace-tools-title">Move through Threadline</h2></div><p>Each area works from the same captures and saved canvas.</p></div>
      <div className="beta-feature-grid">{featureLinks.map(feature => <button key={feature.title} onClick={() => onNavigate(feature.destination)}>
        <span className="beta-feature-icon" aria-hidden="true">{feature.icon}</span><span><small>{feature.eyebrow}</small><strong>{feature.title}</strong><span>{feature.description}</span></span><b aria-hidden="true">↗</b>
      </button>)}</div>
    </section>
  </div>
}
