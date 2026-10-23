import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { BetaWelcome } from './BetaWelcomeView'

const render = (signedIn = false, preview = false) => renderToStaticMarkup(<BetaWelcome
  state={signedIn ? { status: 'signed-in', session: { user: { id: 'synthetic' } } } : { status: 'signed-out' }}
  preview={preview} onLogin={() => {}} onVerify={() => {}} onRetry={() => {}} onLocal={() => {}} onOpen={async () => {}} />)

describe('immersive beta entry', () => {
  it('keeps signup immediately reachable with one meaningful heading and decorative artwork', () => {
    const html = render()
    expect(html.match(/<h1\b/g)).toHaveLength(1)
    expect(html).toContain('id="beta-title"')
    expect(html).toContain('class="beta-glass-wordmark" aria-hidden="true"')
    expect(html).toContain('alt=""')
    expect(html).toContain('href="#join"')
    expect(html).toContain('id="join"')
    expect(html).toContain('href="#beta-story"')
    expect(html).toContain('id="beta-story"')
    expect(html).not.toContain('<video')
    expect(html).not.toContain('<canvas')
    expect(html).toContain('class="beta-welcome beta-welcome-immersive"')
    expect(html).not.toContain('class="beta-welcome beta-landing"')
  })
  it('removes the decorative scene from signed-in installation instructions', () => {
    const html = render(true)
    expect(html).not.toContain('beta-sky-image')
    expect(html).toContain('id="beta-setup-title"')
    expect(html).toContain('Open Threadline')
  })
  it('retains a clearly labeled safe preview', () => {
    const html = render(false, true)
    expect(html).toContain('Try the preview')
    expect(html).toContain('no emails are sent and no account data is changed')
    expect(html).toContain('Preview home-screen setup')
  })
})
