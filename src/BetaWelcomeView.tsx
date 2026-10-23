import { useEffect, useRef, useState } from 'react'
import type { AuthState } from './auth'
import { installPlatform, type InstallPlatform } from './betaWelcome'
import './betaWelcome.css'

export interface BetaWelcomeProps {
  state: AuthState
  onLogin: (email: string) => void
  onVerify: (email: string, code: string) => void
  onRetry: () => void
  onLocal: () => void
  onOpen: () => Promise<void>
  preview?: boolean
}

export function BetaWelcome({ state, onLogin, onVerify, onRetry, onLocal, onOpen, preview = false }: BetaWelcomeProps) {
  const [email, setEmail] = useState('')
  const [code, setCode] = useState('')
  const [showCode, setShowCode] = useState(false)
  const [previewSetup, setPreviewSetup] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const codeRef = useRef<HTMLInputElement>(null)
  const heading = useRef<HTMLHeadingElement>(null)
  const codeSent = state.status === 'signed-out' && !!state.emailCodeSent
  const signedIn = state.status === 'signed-in'
  const waiting = state.status === 'loading'
  useEffect(() => { if (codeSent) { setShowCode(true); codeRef.current?.focus() } }, [codeSent])
  useEffect(() => { if (showCode) codeRef.current?.focus() }, [showCode])
  useEffect(() => { if (signedIn || previewSetup) heading.current?.focus() }, [signedIn, previewSetup])
  const openWorkspace = async () => {
    if (busy) return
    setBusy(true); setError('')
    try { await onOpen() }
    catch { setError('We couldn’t open your synced workspace. Check your connection and try again. Nothing on this device has been changed.') }
    finally { setBusy(false) }
  }
  return <main className="beta-welcome">
    <div className="beta-wrap">
      <header className="beta-nav"><a className="beta-wordmark" href="/beta" aria-label="Threadline beta"><span aria-hidden="true">⊹</span> threadline</a><span className="beta-badge">EARLY ACCESS</span>
        {preview ? <a className="beta-nav-link" href="/settings">Back to Settings</a> : !signedIn && <a className="beta-nav-link" href="#join">Sign in <span aria-hidden="true">↗</span></a>}
      </header>
      {preview && <p className="beta-preview-label">Design preview · no emails are sent and no account data is changed.</p>}
      {signedIn || previewSetup ? <section className="beta-setup" aria-labelledby="beta-setup-title">
        <div className="beta-setup-icon" aria-hidden="true">⊹</div><p className="beta-overline">{previewSetup ? 'SETUP PREVIEW' : 'YOU’RE SIGNED IN'}</p>
        <h1 id="beta-setup-title" ref={heading} tabIndex={-1}>Good thoughts.<br />Always within reach.</h1>
        <p className="beta-lead">Give Threadline a place on your home screen. Your next thought is only a tap away.</p>
        <InstallInstructions />
        <div className="beta-setup-action">
          {error && <p role="alert" className="beta-error">{error}</p>}
          <button className="beta-cta" disabled={busy} onClick={() => previewSetup ? setPreviewSetup(false) : void openWorkspace()}>{busy ? 'Opening your workspace…' : previewSetup ? 'Back to landing preview' : 'Open Threadline'} <span aria-hidden="true">↗</span></button>
          <p>You can also keep using your browser. Installation is optional.</p>
          {!previewSetup && <p className="beta-fine">This opens your existing account or creates an empty synced workspace. Any separate device copy stays preserved; you can combine it later in Settings → Data.</p>}
        </div>
      </section> : <>
        <section className="beta-hero" aria-labelledby="beta-title">
          <div className="beta-hero-copy"><p className="beta-overline"><span /> A LITTLE SPACE FOR YOUR MIND</p>
            <h1 id="beta-title">Life has threads.<br /><em>Keep yours together.</em></h1>
            <p className="beta-lead">Catch a thought before it disappears. Find it when you need it. Make room to see how it all connects.</p>
            <a className="beta-cta" href="#join">Join the beta <span aria-hidden="true">↗</span></a><p className="beta-small">On your phone. On your laptop. In your own rhythm.</p>
          </div>
          <figure className="beta-product" aria-label="Illustrative Threadline workspace: capture a thought, organize it, and connect ideas on a canvas">
            <div className="beta-product-bar"><span>⊹ threadline</span><span>YOUR SPACE</span></div>
            <div className="beta-demo-capture"><span className="beta-overline">CAPTURE</span><p>A little studio.<br />A place to make things.</p><span className="beta-demo-saved">✓ Thought captured</span></div>
            <div className="beta-demo-canvas"><svg viewBox="0 0 420 230" aria-hidden="true"><path d="M94 126 C180 126 130 48 245 48 M94 126 C175 126 150 181 275 181" /></svg><span className="beta-node beta-node-root">A little studio</span><span className="beta-node beta-node-one">Room to experiment</span><span className="beta-node beta-node-two">Something of my own</span><span className="beta-canvas-caption">A BIGGER PICTURE, ONE THOUGHT AT A TIME</span></div>
            <figcaption>Less to hold in your head. More to build on.</figcaption>
          </figure>
        </section>
        <section className="beta-principles" aria-label="What you can do with Threadline">
          <article><span className="beta-step-number">01 / CAPTURE</span><h2>Start with a thought.</h2><p>A note, an idea, a thing to do. Write it down without deciding where it belongs.</p></article>
          <article><span className="beta-step-number">02 / ORGANIZE</span><h2>Find your own order.</h2><p>Review when you’re ready. Use folders and search to keep good thoughts close.</p></article>
          <article><span className="beta-step-number">03 / CONNECT</span><h2>See beyond the list.</h2><p>Spread ideas across a canvas. Draw connections. Give your thinking room to grow.</p></article>
        </section>
        <section className="beta-join" id="join" aria-labelledby="beta-join-title">
          <div><p className="beta-overline">COME MAKE IT YOURS</p><h2 id="beta-join-title">Your next thought<br />starts here.</h2><p>We’re opening Threadline to early testers. Use it in everyday life, tell us what feels good, and help us make the rough edges better.</p><p className="beta-small">A web-app beta. No App Store download or TestFlight invitation needed.</p></div>
          <div className="beta-signup"><h3>{showCode ? 'Check your email' : 'Join Threadline'}</h3><p>{showCode ? 'Enter the code from your email here, or open its sign-in link. Use the same email on every device.' : 'One email. No password to remember. New here? We’ll create your account. Already here? We’ll sign you in.'}</p>
            {(state.status === 'error' || state.status === 'unconfigured') && <div className="beta-error" role="alert"><p>{state.status === 'unconfigured' ? 'Signup isn’t available in this preview. Please return to the shared beta link.' : state.message}</p>{state.status === 'error' && <button className="beta-text-button" onClick={onRetry}>Retry connection</button>}</div>}
            {state.status === 'signed-out' && state.message && <p className={codeSent ? 'beta-feedback' : 'beta-error'} role={codeSent ? 'status' : 'alert'}>{state.message}</p>}
            <form className="beta-signup-form" onSubmit={event => { event.preventDefault(); if (preview) { setPreviewSetup(true); return } if (waiting || state.status !== 'signed-out') return; onLogin(email.trim()); }}>
              <label htmlFor="beta-email">Email address</label><input id="beta-email" type="email" autoComplete="email" inputMode="email" autoCapitalize="none" spellCheck={false} placeholder="you@example.com" required value={email} onChange={event => setEmail(event.target.value)} disabled={waiting} />
              <button className="beta-cta" type="submit" disabled={!preview && state.status !== 'signed-out'}>{waiting ? 'Please wait…' : preview ? 'Preview home-screen setup' : showCode ? 'Send a new email' : 'Continue with email'} <span aria-hidden="true">↗</span></button>
            </form>
            {showCode ? <form className="beta-signup-form" onSubmit={event => { event.preventDefault(); if (!preview && state.status === 'signed-out') onVerify(email.trim(), code.trim()) }}>
              <label htmlFor="beta-code">Email code</label><input ref={codeRef} id="beta-code" type="text" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6,10}" maxLength={10} required value={code} disabled={waiting} onChange={event => setCode(event.target.value.replace(/\D/g, '').slice(0, 10))} aria-describedby="beta-code-help" />
              <small id="beta-code-help">6–10 digits. Enter it here to sign in on this device. If your email only contains a link, open that link instead.</small><button className="beta-cta" disabled={waiting || state.status !== 'signed-out'}>Verify &amp; continue</button>
            </form> : <button className="beta-text-button" onClick={() => setShowCode(true)}>Already have an email code?</button>}
            <p className="beta-fine">Your email is used for your account and sign-in. This does not subscribe you to a mailing list.</p>
            <details className="beta-local"><summary>Have captures saved only on this device?</summary><p>They stay here. Signing up won’t upload or replace them. You can combine them with your account in Settings → Data.</p><button className="beta-text-button" onClick={onLocal} disabled={waiting}>Continue with device data</button></details>
          </div>
        </section>
        <section className="beta-faq" aria-labelledby="beta-faq-title"><h2 id="beta-faq-title">A few things to know.</h2>
          <details><summary>Will my phone and laptop show the same things?</summary><p>Sign in with the same email to open your account workspace on each device. Account changes save online; other devices refresh when you’re not editing. Separate local-only work is preserved until you choose to combine it.</p></details>
          <details><summary>How do I put it on my home screen?</summary><p>After signing in, we’ll walk you through it. On iPhone, use Safari’s Share menu, then Add to Home Screen. On Android, look for Install app in Chrome’s menu. You can always use a browser instead.</p></details>
          <details><summary>What should I expect from the beta?</summary><p>This is an early product with rough edges. Avoid sensitive information, keep an export of important work, and share feedback with the person who invited you. Home-screen installation does not enable push notifications.</p></details>
          <details><summary>Where does my data live?</summary><p>Signed-in work is stored in your account using Supabase. Device-only work stays in that browser. You can export your work in Settings → Recovery. This beta does not yet offer self-service account deletion.</p></details>
        </section>
      </>}
      <footer className="beta-bottom"><span>⊹ threadline</span><span>A little more room to think.</span><span>Built with early feedback.</span></footer>
    </div>
  </main>
}

export function InstallInstructions() {
  const [platform, setPlatform] = useState<InstallPlatform>(() => typeof navigator === 'undefined' ? 'iphone' : installPlatform(navigator.userAgent, navigator.maxTouchPoints))
  const standalone = typeof window !== 'undefined' && (window.matchMedia?.('(display-mode: standalone)').matches || (navigator as Navigator & { standalone?: boolean }).standalone)
  return <div className="beta-install">
    {standalone ? <p className="beta-feedback">You’re already using the home-screen app. You’re all set to continue.</p> : <>
      <div className="beta-platforms" role="group" aria-label="Installation instructions for your device">{(['iphone', 'android', 'desktop'] as const).map(value => <button key={value} aria-pressed={platform === value} onClick={() => setPlatform(value)}>{value === 'iphone' ? 'iPhone / iPad' : value === 'android' ? 'Android' : 'Computer'}</button>)}</div>
      <ol className="beta-install-steps">{(platform === 'iphone' ? [
        ['Open in Safari', 'If you came from a message or another app, open this same page in Safari first.'],
        ['Share → Add to Home Screen', 'Tap the square with the upward arrow. Share may be inside the More menu. Scroll to Add to Home Screen.'],
        ['Add, then open Threadline', 'Keep Open as Web App on if shown, tap Add, then launch the new icon.'],
      ] : platform === 'android' ? [
        ['Open in Chrome', 'Open this same page in Chrome on your Android phone.'],
        ['Open the ⋮ menu', 'Choose Add to home screen, then Install, or Install app. The wording depends on your browser.'],
        ['Launch Threadline', 'Open the new Threadline icon from your home screen or app launcher.'],
      ] : [
        ['Keep this page close', 'Bookmark Threadline so you can come back quickly.'],
        ['Install if your browser offers it', 'Chrome or Edge may show an install icon in the address bar or an Install app option in the menu.'],
        ['Use the same account', 'Sign in with the same email on your phone to open the same workspace.'],
      ]).map(([title, description]) => <li key={title}><strong>{title}</strong><p>{description}</p></li>)}</ol>
    </>}
    <p className="beta-install-note">If the icon asks you to sign in again, use the same email, request a new code, and enter it <strong>inside the home-screen app</strong>. Your browser and installed app may have separate sign-in sessions.</p>
  </div>
}
