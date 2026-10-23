import { useEffect, useRef, type ReactNode } from 'react'
import { observeJourney } from './betaJourney'
import './betaSkyHero.css'

/** The document scrolls normally; only decorative landscape layers follow its progress. */
export function BetaSkyHero({ preview = false, children }: { preview?: boolean; children: ReactNode }) {
  const root = useRef<HTMLDivElement>(null)
  useEffect(() => root.current ? observeJourney(root.current) : undefined, [])
  return <div className="beta-journey" ref={root}>
    <div className="beta-journey-stage">
      <div className="beta-journey-art" aria-hidden="true">
        <img className="beta-journey-sky" src="/images/beta-alpine-sky.jpg" alt="" width="1536" height="1024" fetchPriority="high" />
        <img className="beta-journey-ground" src="/images/beta-grounded-meadow.jpg" alt="" width="1536" height="1024" decoding="async" />
        <img className="beta-journey-clouds" src="/images/beta-cloud-layer.png" alt="" width="960" height="640" decoding="async" />
        <div className="beta-glass-wordmark">threadline</div>
      </div>
    <header className="beta-sky-nav">
      <a className="beta-sky-brand" href="/beta" aria-label="Threadline beta"><span aria-hidden="true">⊹</span> threadline</a>
      <span className="beta-sky-badge">{preview ? 'DESIGN PREVIEW' : 'EARLY ACCESS'}</span>
      <a className="beta-sky-signin" href="#join">{preview ? 'Try the preview' : 'Sign in'} <span aria-hidden="true">↗</span></a>
    </header>
    </div>
    <div className="beta-journey-chapters">
      <section className="beta-journey-chapter beta-journey-dream" aria-labelledby="beta-title">
        <div className="beta-journey-copy">
          <p className="beta-sky-eyebrow">A LITTLE SPACE FOR YOUR MIND</p>
          <h1 id="beta-title">Head in the clouds.</h1>
          <p>Every good thing starts with a thought.</p>
          <a className="beta-sky-explore" href="#beta-horizon">Scroll to find your footing <span aria-hidden="true">↓</span></a>
        </div>
      </section>
      <section className="beta-journey-chapter beta-journey-horizon" id="beta-horizon" aria-labelledby="beta-horizon-title">
        <div className="beta-journey-copy">
          <p className="beta-sky-eyebrow">LET IT TAKE SHAPE</p>
          <h2 id="beta-horizon-title">A little clarity.<br />A new perspective.</h2>
          <p>Capture the thought. Connect the pieces.<br />Find your next step.</p>
          <a className="beta-sky-explore" href="#join">Keep going <span aria-hidden="true">↓</span></a>
        </div>
      </section>
      <section className="beta-journey-arrival" id="join" data-journey-ground aria-labelledby="beta-join-title">
        <div className="beta-arrival-heading"><p className="beta-sky-eyebrow">BRING IT INTO YOUR WORLD</p><h2 id="beta-join-title">Feet on the ground.</h2><p>Your thoughts, with somewhere to grow.</p></div>
        {children}
      </section>
    </div>
  </div>
}
