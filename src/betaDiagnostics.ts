export type StorageMode = 'local-only' | 'sync'
export type AuthState = 'signed-out' | 'authenticated'
export type ProviderKind = 'deterministic' | 'remote'
export type DisplayMode = 'installed' | 'browser'

export type DiagnosticCountName = 'captures' | 'interpretations' | 'semanticObjects' | 'canvasElements'

export interface BetaDiagnosticsInput {
  buildLabel?: string
  storageMode?: StorageMode
  authState?: AuthState
  provider?: {
    kind?: ProviderKind
    configured?: boolean
    verified?: boolean
  }
  displayMode?: DisplayMode
  recordCounts?: Partial<Record<DiagnosticCountName, number>>
}

export interface BetaDiagnosticsSnapshot {
  buildLabel: string
  storage: {
    mode: StorageMode | 'unknown'
    status: string
    nextStep: string
  }
  authentication: {
    state: AuthState | 'unknown'
    status: string
    nextStep: string
  }
  provider: {
    kind: ProviderKind | 'unknown'
    configured: boolean | 'unknown'
    verified: boolean | 'unknown'
    status: string
    nextStep: string
  }
  display: {
    mode: DisplayMode | 'unknown'
    status: string
    nextStep: string
  }
  recordCounts: Record<DiagnosticCountName, number>
}

const countNames: DiagnosticCountName[] = ['captures', 'interpretations', 'semanticObjects', 'canvasElements']
const MAX_COUNT = 999_999_999

function safeLabel(label: string | undefined): string {
  const trimmed = typeof label === 'string' ? label.trim() : ''
  return trimmed || 'Unknown build'
}

function safeCount(value: number | undefined): number {
  if (!Number.isFinite(value) || value === undefined) return 0
  return Math.min(MAX_COUNT, Math.max(0, Math.floor(value)))
}

function storageSummary(mode: StorageMode | undefined): BetaDiagnosticsSnapshot['storage'] {
  if (mode === 'local-only') return { mode, status: 'Local-only storage', nextStep: 'Keep using this device, or sign in to enable sync.' }
  if (mode === 'sync') return { mode, status: 'Account sync storage', nextStep: 'Continue testing sync and verify that the expected account is signed in.' }
  return { mode: 'unknown', status: 'Storage mode unavailable', nextStep: 'Provide the current storage mode to diagnose local data or sync.' }
}

function authenticationSummary(state: AuthState | undefined): BetaDiagnosticsSnapshot['authentication'] {
  if (state === 'signed-out') return { state, status: 'Signed out', nextStep: 'Sign in only when you want to test account sync.' }
  if (state === 'authenticated') return { state, status: 'Authenticated', nextStep: 'Continue testing account-scoped sync.' }
  return { state: 'unknown', status: 'Authentication state unavailable', nextStep: 'Provide the current authentication state.' }
}

function providerSummary(provider: BetaDiagnosticsInput['provider']): BetaDiagnosticsSnapshot['provider'] {
  const kind = provider?.kind === 'deterministic' || provider?.kind === 'remote' ? provider.kind : 'unknown'
  const configured = typeof provider?.configured === 'boolean' ? provider.configured : 'unknown'
  const verified = typeof provider?.verified === 'boolean' ? provider.verified : 'unknown'

  if (kind === 'deterministic') {
    return { kind, configured, verified, status: 'Deterministic provider ready', nextStep: 'Use the deterministic provider for privacy-safe beta testing.' }
  }
  if (kind === 'remote' && configured === true && verified === true) {
    return { kind, configured, verified, status: 'Remote provider verified', nextStep: 'Continue testing provider-backed interpretation.' }
  }
  if (kind === 'remote' && configured === true) {
    return { kind, configured, verified, status: 'Remote provider configured but unverified', nextStep: 'Run an explicit provider verification before treating it as available.' }
  }
  if (kind === 'remote' && configured === false) {
    return { kind, configured, verified, status: 'Remote provider not configured', nextStep: 'Use the deterministic provider or configure and explicitly verify a remote provider.' }
  }
  return { kind, configured, verified, status: 'Provider state unavailable', nextStep: 'Provide provider kind, configuration, and verification state.' }
}

function displaySummary(mode: DisplayMode | undefined): BetaDiagnosticsSnapshot['display'] {
  if (mode === 'installed') return { mode, status: 'Installed app display', nextStep: 'Continue testing the installed-app experience.' }
  if (mode === 'browser') return { mode, status: 'Browser display', nextStep: 'Install the app if you want to test the standalone display.' }
  return { mode: 'unknown', status: 'Display mode unavailable', nextStep: 'Provide whether this session is installed or running in a browser.' }
}

/** Builds a deterministic, privacy-safe snapshot from caller-owned values only. */
export function createBetaDiagnosticsSnapshot(input: BetaDiagnosticsInput = {}): BetaDiagnosticsSnapshot {
  const counts = {} as Record<DiagnosticCountName, number>
  for (const name of countNames) counts[name] = safeCount(input.recordCounts?.[name])

  return {
    buildLabel: safeLabel(input.buildLabel),
    storage: storageSummary(input.storageMode),
    authentication: authenticationSummary(input.authState),
    provider: providerSummary(input.provider),
    display: displaySummary(input.displayMode),
    recordCounts: counts,
  }
}

export const betaDiagnosticsSnapshot = createBetaDiagnosticsSnapshot
