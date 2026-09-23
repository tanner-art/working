import type { AppState } from './domain'
import { reconcileLegacyUi } from './migration'
import { buildMorningDigest } from './morningDigest'
import { bankObjects, reviewObjects } from './objectWorkflow'

export type BetaHomeDestination = 'today' | 'capture' | 'review' | 'calendar' | 'canvas' | 'settings' | 'digest'

export function previewStartView(search: string, fallback: BetaHomeDestination | 'commitments'): BetaHomeDestination | 'commitments' | 'beta-home' {
  return new URLSearchParams(search).get('preview') === 'home' ? 'beta-home' : fallback
}

export function buildBetaHomeSnapshot(state: AppState, now = new Date()) {
  const folders = bankObjects(state.objects)
  const digest = buildMorningDigest(reconcileLegacyUi(state), now)
  return {
    digest,
    capturedCount: state.objects.length,
    reviewCount: reviewObjects(state.objects).length,
    bankCount: folders.Personal.length + folders.Business.length + folders.Unfiled.length,
    canvasBlockCount: state.canvas.filter(item => item.type !== 'arrow').length,
  }
}
