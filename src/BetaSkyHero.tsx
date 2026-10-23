import './betaSkyHero.css'

/** A decorative intro, never a loading screen or a gate in front of signup. */
export function BetaSkyHero({ preview = false }: { preview?: boolean }) {
  return <section className="beta-sky" aria-labelledby="beta-title">
    <img className="beta-sky-image" src="/images/beta-alpine-sky.jpg" alt="" width="1536" height="1024" fetchPriority="high" />
    <header className="beta-sky-nav">
      <a className="beta-sky-brand" href="/beta" aria-label="Threadline beta"><span aria-hidden="true">⊹</span> threadline</a>
      <span className="beta-sky-badge">{preview ? 'DESIGN PREVIEW' : 'EARLY ACCESS'}</span>
      <a className="beta-sky-signin" href="#join">{preview ? 'Try the preview' : 'Sign in'} <span aria-hidden="true">↗</span></a>
    </header>
    <div className="beta-sky-stage">
      <div className="beta-glass-wordmark" aria-hidden="true">threadline</div>
      <div className="beta-sky-message">
        <p className="beta-sky-eyebrow">A LITTLE SPACE FOR YOUR MIND</p>
        <h1 id="beta-title">Life has threads.<br />Keep yours together.</h1>
        <p>Catch a thought. Make a connection.<br />Give your mind a little room.</p>
        <a className="beta-sky-join" href="#join">Join the beta <span aria-hidden="true">↗</span></a>
        <a className="beta-sky-explore" href="#beta-story">A little more about Threadline <span aria-hidden="true">↓</span></a>
      </div>
    </div>
  </section>
}
