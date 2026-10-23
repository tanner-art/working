import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { BetaWelcome } from './BetaWelcomeView'
import { BetaSkyHero } from './BetaSkyHero'

const render = (signedIn = false, preview = false) => renderToStaticMarkup(<BetaWelcome
  state={signedIn ? { status: 'signed-in', session: { user: { id: 'synthetic' } } } : { status: 'signed-out' }}
  preview={preview} onLogin={() => {}} onVerify={() => {}} onRetry={() => {}} onLocal={() => {}} onOpen={async () => {}} />)

describe('visual ascent entrance', () => {
  it('keeps product copy behind information, with a reachable wordmark and keyboard shortcut', () => {
    const html = render()
    expect(html).toContain('class="beta-ascent-art" aria-hidden="true"')
    expect(html).toContain('id="info" hidden=""')
    expect(html).toContain('href="#info"')
    expect(html).toContain('Threadline — open information and signup')
    expect(html).toContain('Skip to Threadline information')
    expect(html).toContain('Continue upward')
    expect(html).toContain('Pause wordmark motion')
    const scene = html.slice(html.indexOf('class="beta-ascent"'), html.indexOf('class="beta-information"'))
    expect(scene).not.toContain('Head in the clouds')
    expect(scene).not.toContain('Join Threadline')
    expect(scene).not.toContain('EARLY ACCESS')
    expect(scene).not.toContain('<video')
    expect(scene).not.toContain('<canvas')
    expect(html).toContain('beta-ascent-ground-mobile.jpg')
  })
  it('removes the ascent from signed-in installation instructions', () => {
    const html = render(true)
    expect(html).not.toContain('beta-ascent-art')
    expect(html).toContain('id="beta-setup-title"')
    expect(html).toContain('Open Threadline')
  })
  it('retains safe preview information behind the visual entrance', () => {
    const html = render(false, true)
    expect(html).toContain('no emails are sent and no account data is changed')
    expect(html).toContain('Preview home-screen setup')
  })
  it('makes an existing email-code handoff immediately usable without the ascent', () => {
    const html = renderToStaticMarkup(<BetaSkyHero informationRequested><input aria-label="Email code" /></BetaSkyHero>)
    expect(html).not.toContain('beta-ascent-art')
    expect(html).not.toContain('hidden=""')
    expect(html).toContain('Email code')
  })
})
