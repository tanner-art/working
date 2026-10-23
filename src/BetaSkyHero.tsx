import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { observeJourney } from './betaJourney'
import './betaSkyHero.css'

const informationHash = () => typeof window !== 'undefined' && ['#info', '#join'].includes(window.location.hash)

/** A visual entrance; the existing account forms remain behind an explicit link. */
export function BetaSkyHero({ children, informationRequested = false }: { preview?: boolean; children: ReactNode; informationRequested?: boolean }) {
  const [infoOpen, setInfoOpen] = useState(() => informationRequested || informationHash())
  const lastProgress = useRef(0)
  const heading = useRef<HTMLHeadingElement>(null)
  const showingInfo = infoOpen
  useEffect(() => { if (informationRequested) setInfoOpen(true) }, [informationRequested])
  useEffect(() => {
    const update = () => setInfoOpen(informationHash())
    window.addEventListener('hashchange', update)
    window.addEventListener('popstate', update)
    return () => { window.removeEventListener('hashchange', update); window.removeEventListener('popstate', update) }
  }, [])
  useEffect(() => { if (showingInfo) heading.current?.focus() }, [showingInfo])
  return <div className="beta-entrance">
    {!showingInfo && <AscentScene initialProgress={lastProgress.current} onProgress={value => { lastProgress.current = value }} onOpen={() => setInfoOpen(true)} />}
    <section className="beta-information" id="info" hidden={!showingInfo} aria-labelledby="beta-info-title">
      <a className="beta-information-back" href="#ascent" aria-label="Return to the landscape" onClick={() => setInfoOpen(false)}>←</a>
      <div className="beta-information-card">
        <div className="beta-arrival-heading"><span aria-hidden="true">⊹</span><h1 id="beta-info-title" ref={heading} tabIndex={-1}>threadline</h1><p>Your thoughts, with somewhere to grow.</p></div>
        {children}
      </div>
    </section>
  </div>
}

function AscentScene({ initialProgress, onProgress, onOpen }: { initialProgress: number; onProgress: (value: number) => void; onOpen: () => void }) {
  const root = useRef<HTMLDivElement>(null)
  const [paused, setPaused] = useState(false)
  const progressCallback = useRef(onProgress)
  progressCallback.current = onProgress
  // Place the native scroll area at its bottom before first paint, without input interception.
  useLayoutEffect(() => root.current ? observeJourney(root.current, window, initialProgress, value => progressCallback.current(value)) : undefined, [initialProgress])
  return <div className="beta-ascent" ref={root} tabIndex={0} role="region" aria-label="Landscape ascent. Scroll upward from the river and tree, past mountains and clouds, into the stars." data-paused={paused}>
    <div className="beta-ascent-world">
      <div className="beta-ascent-art" aria-hidden="true">
        <img className="beta-ascent-panorama" src="/images/beta-continuous-world.jpg" alt="" width="724" height="2172" fetchPriority="high" />
        <img className="beta-ascent-tree" src="/images/beta-continuous-tree.png" alt="" width="800" height="1200" decoding="async" />
      </div>
      <a className="beta-ascent-skip" href="#info" onClick={onOpen}>Skip to Threadline information</a>
      <div className="beta-ascent-prize">
        <a className="beta-star-wordmark" href="#info" onClick={onOpen} aria-label="Threadline — open information and signup"><span className="beta-star-symbol" aria-hidden="true">⊹</span><span>threadline</span></a>
        <button className="beta-motion-control" aria-label={paused ? 'Resume wordmark motion' : 'Pause wordmark motion'} aria-pressed={paused} onClick={() => setPaused(value => !value)}>{paused ? '▷' : 'Ⅱ'}</button>
      </div>
    </div>
  </div>
}
