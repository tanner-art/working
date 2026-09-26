import { buildMorningDigest } from './morningDigest'
import { providerStatus, readProviderConfig } from './aiInterpretation'
import { reconcileLegacyUi } from './migration'
import { accountData, createAccountAdapter, createAccountSession, guardAccountMergePreview, type AccountData, type AccountMergeChoices, type AccountMergePlan, type AccountSession } from './accountStorage'
import { readDelivery, setDeliveryEnabled } from './digestDelivery'
import { supabase, auth, accountLabel, dataOwnershipLabel, type AuthState } from './auth'
import { clearLocalData, dismissMobileInstall, shouldShowMobileInstall, MOBILE_INSTALL_KEY, defaultSettings, readSettings, resetSettings, writeSettings, SETTINGS_KEY, type LocalSettings } from './settings'
import { DIGEST_DELIVERY_KEY } from './digestDelivery'
import { Canvas } from './Canvas'
import { CanvasBank } from './CanvasBankView'
import { useCanvasWorkspace } from './useCanvasWorkspace'
import { createCanvasTextSaveQueue } from './canvasTextSaveQueue'
import { DEFAULT_CANVAS_VIEWPORT } from './canvasDocument'
import { addCanvas, canvasBankForState, createCanvasRecord, renameCanvas } from './canvasBank'
import { useWorkspaceExitGuard } from './useWorkspaceExitGuard'
import { TemporalReview } from './TemporalReview'
import { MorningDigest } from './DigestPanel'
import { CalendarView } from './CalendarView'
import { BetaHome } from './BetaHome'
import { previewStartView } from './betaHomeState'
import { useEffect, useRef, useState } from 'react'
import type { AppState, CanvasElement, ObjectKind, SemanticRelationship, ThoughtObject } from './domain'
import { objectLabels } from './domain'
import { createInterpretedObject } from './captureInterpretation'
import { bankFolders, bankObjects, reviewObjects, resolvedIdeas, canvasObjectDraft, hasConfirmation, reverseObject, fixedCommitments, recentObjects, confirmedActions, setObjectStatus, updateObject } from './objectWorkflow'
import { loadStateResult, makeObject, saveState, serializeState } from './store'
import { correctOriginal, hasUnsavedReviewDrafts, reviseInterpretation, revisionNeedsReconfirmation, revisionReviewNotice, reviewTextSnapshot } from './reviewRevision'
import { BETA_LANDING_DISMISSED_KEY, betaLandingVisibility, readBetaLandingInput } from './betaLanding'
import { appSurfaceDefinitionForPath } from './surfaces'
import { OnboardingTutorial } from './OnboardingTutorial'
import { initialTutorialState, startTutorial, type TutorialState } from './onboarding'
import { ReviewResolution } from './ReviewResolutionControl'

type View = 'today' | 'capture' | 'review' | 'commitments' | 'calendar' | 'canvas' | 'settings' | 'digest' | 'beta-home'
const nav: { id: View; label: string; icon: string }[] = [
  { id: 'today', label: 'Today', icon: '◉' }, { id: 'capture', label: 'Capture', icon: '＋' }, { id: 'review', label: 'Organize', icon: '◇' }, { id: 'calendar', label: 'Calendar', icon: '▦' }, { id: 'canvas', label: 'Bank', icon: '⌁' }, { id: 'settings', label: 'Settings', icon: '⚙' }
]

/** Single shared account subscription; several Settings cards read the same state. */
function useAuthState() {
  const [state, setState] = useState<AuthState>(auth.getState)
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    const unsubscribe = auth.subscribe(() => setState(auth.getState()))
    const disconnect = auth.connect()
    setState(auth.getState())
    return () => { unsubscribe(); disconnect() }
  }, [attempt])
  return { state, retry: () => setAttempt(value => value + 1) }
}

const accountAdapter = createAccountAdapter(supabase, import.meta.env.VITE_SUPABASE_DATA_TABLE)
const aiProviderStatus = providerStatus(readProviderConfig({ VITE_AI_INTERPRETATION_PROVIDER: import.meta.env.VITE_AI_INTERPRETATION_PROVIDER }))
type CloudWorkspace = { session: AccountSession; state: AppState; data: AccountData }
type PreparedMerge = { session: AccountSession; plan: AccountMergePlan }
export function App() {
  const account = useAuthState()
  const surface = appSurfaceDefinitionForPath(window.location.pathname)
  const [landingDismissed, setLandingDismissed] = useState(() => {
    try { return localStorage.getItem(BETA_LANDING_DISMISSED_KEY) === 'dismissed' } catch { return false }
  })
  const [cloud, setCloud] = useState<CloudWorkspace>()
  const [preparedMerge, setPreparedMerge] = useState<PreparedMerge>()
  const [generation, setGeneration] = useState(0)
  const open = async (local?: AccountData) => {
    if (!accountAdapter || account.state.status !== 'signed-in') throw Error('Account storage is unconfigured. Set VITE_SUPABASE_DATA_TABLE and configure the account table with RLS.')
    const session = createAccountSession(accountAdapter, account.state.session.user.id, () => {
      const current = auth.getState()
      return current.status === 'signed-in' ? current.session.user.id : undefined
    })
    const result = await session.open(local)
    setCloud({ session, ...result }); setGeneration(value => value + 1)
  }
  const previewMerge = async (local: AccountData, choices: AccountMergeChoices) => {
    if (!accountAdapter || account.state.status !== 'signed-in') throw Error('Account storage is unconfigured. Set VITE_SUPABASE_DATA_TABLE and configure the account table with RLS.')
    const session = createAccountSession(accountAdapter, account.state.session.user.id, () => {
      const current = auth.getState()
      return current.status === 'signed-in' ? current.session.user.id : undefined
    })
    const plan = await session.previewMerge(local, choices)
    setPreparedMerge({ session, plan })
    return plan
  }
  const confirmMerge = async (currentLocal: AccountData) => {
    if (!preparedMerge) throw Error('Preview the merge again before confirming.')
    const result = await preparedMerge.session.confirmMerge(preparedMerge.plan, currentLocal)
    setPreparedMerge(undefined); setCloud({ session: preparedMerge.session, ...result }); setGeneration(value => value + 1)
  }
  const landingInput = readBetaLandingInput(localStorage, account.state)
  const landingVisibility = betaLandingVisibility({ ...landingInput, dismissed: landingDismissed || landingInput.dismissed })
  if (surface.id === 'tutorial-preview') return <TutorialPreview />
  if (surface.id === 'landing-preview') return <BetaLanding preview state={account.state} onContinue={() => window.location.assign('/preview/tutorial')} />
  if (landingVisibility === 'loading') return <main className="beta-loading" role="status"><p>Checking your account…</p></main>
  if (landingVisibility === 'landing') return <BetaLanding state={account.state} onContinue={() => {
    try { localStorage.setItem(BETA_LANDING_DISMISSED_KEY, 'dismissed') } catch { /* Continue remains available for this visit. */ }
    setLandingDismissed(true)
  }} />
  return <ThreadlineApp key={generation} account={account} cloud={cloud} onOpenAccount={open}
    mergePlan={preparedMerge?.plan} onPreviewMerge={previewMerge} onConfirmMerge={confirmMerge} onCancelMerge={() => setPreparedMerge(undefined)} />
}

function BetaLanding({ state, onContinue, preview = false }: { state: AuthState; onContinue: () => void; preview?: boolean }) {
  const [email, setEmail] = useState('')
  const [code, setCode] = useState('')
  const codeRef = useRef<HTMLInputElement>(null)
  const codeSent = state.status === 'signed-out' && state.emailCodeSent
  useEffect(() => { if (codeSent) codeRef.current?.focus() }, [codeSent])
  return <main className="beta-landing"><div className="beta-landing-inner">
    <header className="beta-landing-header"><p className="eyebrow">Friends &amp; family beta</p><p className="beta-brand"><span className="brand-mark">⊹</span> threadline</p>{preview && <a className="beta-preview-return" href="/settings">Back to Settings</a>}</header>
    <section className="beta-landing-hero" aria-labelledby="beta-landing-title"><div><p className="beta-kicker">Capture less. Understand more.</p><h1 id="beta-landing-title">A calm path from thought to action.</h1><p className="beta-intro">Threadline keeps your raw thoughts close, helps you organize their meaning, and gives you a clear place to act on them.</p></div><div className="beta-loop" aria-label="Threadline loop"><div><strong>Capture</strong><span>Get it out quickly.</span></div><span className="beta-arrow" aria-hidden="true">→</span><div><strong>Organize</strong><span>Shape the meaning.</span></div><span className="beta-arrow" aria-hidden="true">→</span><div><strong>Calendar / Canvas</strong><span>Plan or see the bigger picture.</span></div></div></section>
    <section className="beta-landing-card" aria-labelledby="beta-sign-in-title"><h2 id="beta-sign-in-title">Sign in to Threadline</h2><p className="beta-copy">Use your email to receive a sign-in link and a one-time code. The code lets you sign in on this device even when the email was requested elsewhere.</p>
      {state.status === 'unconfigured' && <p className="beta-alert" role="alert">Sign-in is not available in this deployment yet. You can continue on this device.</p>}{state.status === 'error' && <p className="beta-alert" role="alert">{state.message}</p>}{state.status === 'signed-out' && state.message && <p className="beta-message" role={codeSent ? 'status' : 'alert'}>{state.message}</p>}
      {state.status === 'signed-out' && <form className="beta-form" onSubmit={event => { event.preventDefault(); setEmail(email.trim()); setCode(''); void auth.act('login', email) }}><label htmlFor="beta-email">Email address</label><input id="beta-email" type="email" autoComplete="email" required value={email} onChange={event => setEmail(event.target.value)} /><button className="primary" type="submit">Email me a sign-in link and code</button></form>}
      {state.status === 'signed-out' && <form className="beta-form beta-code-form" onSubmit={event => { event.preventDefault(); void auth.act('verify-code', email, code) }}><label htmlFor="beta-code">6–10 digit email code</label><input ref={codeRef} id="beta-code" type="text" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6,10}" maxLength={10} required value={code} onChange={event => setCode(event.target.value.replace(/\D/g, '').slice(0, 10))} /><button className="primary" type="submit">Continue with code</button></form>}
      {state.status === 'loading' && <p className="beta-message" role="status">Checking your account…</p>}<button className="beta-device-button" type="button" onClick={onContinue}>Continue on this device</button><p className="beta-note"><strong>Your data stays yours.</strong> Existing local captures remain on this device. Account data is only loaded or copied when you explicitly choose that in Settings. AI suggestions always require your review.</p>
    </section><p className="beta-footer">Private by default · Local-first · Built for thinking in motion</p>
  </div></main>
}

function TutorialPreview() {
  const [tutorial, setTutorial] = useState<TutorialState>(() => startTutorial(initialTutorialState()))
  const restart = () => setTutorial(startTutorial(initialTutorialState()))
  return <main className="tutorial-preview-shell"><div className="tutorial-preview-inner">
    <header className="tutorial-preview-header"><div><p className="eyebrow">Beta preview</p><h1>First-run tutorial</h1></div><a className="secondary" href="/settings">Back to Settings</a></header>
    <p className="tutorial-preview-note">This replay does not change your saved onboarding status, thoughts, or account data.</p>
    <OnboardingTutorial state={tutorial} onStateChange={setTutorial} />
    {tutorial.status !== 'active' && <section className="tutorial-preview-complete"><h2>{tutorial.status === 'completed' ? 'Tutorial complete' : 'Tutorial skipped'}</h2><p>You can restart the walkthrough or return to Settings.</p><button className="primary" type="button" onClick={restart}>Restart tutorial</button></section>}
  </div></main>
}

function ThreadlineApp({ account, cloud, onOpenAccount, mergePlan, onPreviewMerge, onConfirmMerge, onCancelMerge }: {
  account: ReturnType<typeof useAuthState>; cloud?: CloudWorkspace; onOpenAccount: (local?: AccountData) => Promise<void>
  mergePlan?: AccountMergePlan; onPreviewMerge: (local: AccountData, choices: AccountMergeChoices) => Promise<AccountMergePlan>
  onConfirmMerge: (currentLocal: AccountData) => Promise<void>; onCancelMerge: () => void
}) {
  const [initial] = useState(() => cloud ? { state: cloud.state, error: undefined } : loadStateResult())
  const [state, setState] = useState<AppState>(initial.state)
  const latestState = useRef(state)
  latestState.current = state
  const [saveError, setSaveError] = useState<string | undefined>()
  const [preferences, setPreferences] = useState(() => {
    try { return { value: cloud?.data.settings ?? readSettings(localStorage), error: '' } }
    catch { return { value: { ...defaultSettings }, error: 'Local settings could not be read. Editing settings is paused; stored settings are untouched.' } }
  })
  const latestPreferences = useRef(preferences)
  latestPreferences.current = preferences
  const [digest, setDigest] = useState(() => cloud?.data.digest)
  const latestDigest = useRef(digest)
  latestDigest.current = digest
  const [accountBusy, setAccountBusy] = useState(false)
  const [accountMessage, setAccountMessage] = useState('')
  const [cloudStatus, setCloudStatus] = useState(cloud ? 'Account storage active.' : '')
  const [mergeChoices, setMergeChoices] = useState<AccountMergeChoices>({ settings: 'account', digest: 'account' })
  const accountValid = !cloud || (account.state.status === 'signed-in' && account.state.session.user.id === cloud.session.userId)
  const [installHelp, setInstallHelp] = useState(() => shouldShowMobileInstall(
    { getItem: key => localStorage.getItem(key) },
    window.matchMedia('(max-width: 720px)').matches,
    window.matchMedia('(display-mode: standalone)').matches || (navigator as Navigator & { standalone?: boolean }).standalone === true,
  ))
  const [installMessage, setInstallMessage] = useState('')
  const installHeading = useRef<HTMLHeadingElement>(null)
  const installOpener = useRef<HTMLButtonElement>(null)
  const [focusInstallHelp, setFocusInstallHelp] = useState(false)
  useEffect(() => {
    if (installHelp && focusInstallHelp) installHeading.current?.focus()
  }, [installHelp, focusInstallHelp])
  const closeInstallHelp = () => {
    try { dismissMobileInstall(localStorage); setInstallMessage('') }
    catch { setInstallMessage('Install help closed for this visit. Browser storage could not remember your choice; it may appear again next time.') }
    setInstallHelp(false)
    if (focusInstallHelp) installOpener.current?.focus()
    setFocusInstallHelp(false)
  }
// The secondary home is reviewable by URL without changing anyone's saved/default start page.
  const [view, setView] = useState<View>(() => previewStartView(window.location.search,
    appSurfaceDefinitionForPath(window.location.pathname).id === 'settings' ? 'settings' : preferences.value.startPage))
  const [clearRequested, setClearRequested] = useState(false)
  const clearing = useRef(false)
  const capturePending = useRef(false)
  const [captureError, setCaptureError] = useState<string | undefined>()
  const [draft, setDraft] = useState('')
  const [captureBusy, setCaptureBusy] = useState(false)
  const [captureSuccess, setCaptureSuccess] = useState(0)
  const [selectedObjectId, setSelectedObjectId] = useState<string | null>(null)
  const [openCanvasId, setOpenCanvasId] = useState<string | null>(null)
  const [focusCanvasTitle, setFocusCanvasTitle] = useState(false)
  const [bankFocusTarget, setBankFocusTarget] = useState<'create' | string | null>(null)
  const update = (fn: (current: AppState) => AppState) => {
    if (mergePlan) onCancelMerge()
    const next = fn(latestState.current)
    latestState.current = next
    setState(next)
  }
  const canvas = useCanvasWorkspace(state, update, view === 'canvas' ? openCanvasId : null)
  const saveSequence = useRef(0)
  const firstAccountSave = useRef(!!cloud)
  const persistRef = useRef<(retry: boolean) => Promise<boolean>>(async () => false)
  const [canvasTextSaveQueue] = useState(() => createCanvasTextSaveQueue(retry => persistRef.current(retry)))
  const persist = async (retry = false): Promise<boolean> => {
    if (initial.error || clearing.current) return false
    if (!cloud) { const error = saveState(latestState.current); setSaveError(error); return !error }
    const sequence = ++saveSequence.current
    setCloudStatus('Saving account changes…')
    try {
      await cloud.session.save(cloud.session.snapshot(latestState.current, latestPreferences.current.value, latestDigest.current!), retry)
      if (sequence === saveSequence.current) {
        setSaveError(undefined)
        setCloudStatus(canvasTextSaveQueue.hasUnsent() ? 'Account changes waiting to save…' : 'Saved to account. Load account data on your other device to see this version.')
      }
      return true
    } catch (error) {
      if (sequence === saveSequence.current) { setSaveError((error as Error).message); setCloudStatus('Account changes are not saved.') }
      return false
    }
  }
  persistRef.current = persist
  useEffect(() => { if (!cloud) void persist() }, [state, initial.error])
  useEffect(() => {
    if (!cloud) return
    if (firstAccountSave.current) { firstAccountSave.current = false; return }
    if (canvasTextSaveQueue.consumeStateUpdate()) return
    void persist()
  }, [state, preferences.value, digest, initial.error])
  useEffect(() => { if (view !== 'canvas' || openCanvasId === null) canvasTextSaveQueue.flush() }, [view, openCanvasId, canvasTextSaveQueue])
  useEffect(() => () => canvasTextSaveQueue.dispose(), [canvasTextSaveQueue])
  useWorkspaceExitGuard(() => {
    if (initial.error || clearing.current) return false
    if (cloud) {
      canvasTextSaveQueue.flush()
      return canvasTextSaveQueue.hasPending() || !!saveError || cloudStatus === 'Saving account changes…'
    }
    const error = saveState(latestState.current)
    setSaveError(error)
    return !!error
  })
  const openAccount = async (copy: boolean) => {
    if (cloud && canvasTextSaveQueue.hasPending()) {
      canvasTextSaveQueue.flush()
      setAccountMessage('Wait for account changes to finish saving before loading account data.')
      return
    }
    if (capturePending.current || accountBusy || cloudStatus === 'Saving account changes…') return
    if (!copy && !window.confirm('Load the latest account data into this open tab? Local saved data stays untouched. Download an export first if this tab has unsaved account edits.')) return
    setAccountBusy(true); setAccountMessage('')
    try {
      if (copy && (cloud || preferences.error || saveError)) throw Error('Resolve local save/settings errors before copying data.')
      await onOpenAccount(copy ? accountData(state, preferences.value, readDelivery(localStorage)) : undefined)
    } catch (error) { setAccountMessage((error as Error).message) }
    finally { setAccountBusy(false) }
  }
  const previewMerge = async () => {
    if (capturePending.current || accountBusy || cloudStatus === 'Saving account changes…') return
    setAccountBusy(true); setAccountMessage('')
    try {
      if (cloud || preferences.error || saveError) throw Error('Resolve local save/settings errors before merging data.')
      const local = accountData(state, preferences.value, readDelivery(localStorage))
      await guardAccountMergePreview(local,
        snapshot => onPreviewMerge(snapshot, mergeChoices),
        () => accountData(latestState.current, latestPreferences.current.value, readDelivery(localStorage)))
    } catch (error) { onCancelMerge(); setAccountMessage((error as Error).message) }
    finally { setAccountBusy(false) }
  }
  const confirmMerge = async () => {
    if (!mergePlan || accountBusy || !window.confirm('Combine the previewed account and device data? Both device-local copies remain untouched.')) return
    setAccountBusy(true); setAccountMessage('')
    try { await onConfirmMerge(accountData(state, preferences.value, readDelivery(localStorage))) }
    catch (error) { setAccountMessage((error as Error).message) }
    finally { setAccountBusy(false) }
  }
  const dataControls = <section className="settings-card"><h2>Data</h2>
    <p>{dataOwnershipLabel(account.state, !!cloud)}</p>
    <p role="status">{cloudStatus}</p>
    {account.state.status === 'signed-in' && <>
      {!accountAdapter && <p role="alert">Account storage is unconfigured. A public table name and a table with account access policies are required.</p>}
      <p>Copying creates account data only if the account is empty. Loading opens account data in this tab and preserves the device’s local copy. Updates on other devices appear when you load again; concurrent saves are rejected.</p>
      {!cloud && <button className="secondary" disabled={!accountAdapter || accountBusy || captureBusy || cloudStatus === 'Saving account changes…'} onClick={() => void openAccount(true)}>Copy this device’s local data into my account</button>}
      <button className="secondary" disabled={!accountAdapter || accountBusy || captureBusy || cloudStatus === 'Saving account changes…'} onClick={() => void openAccount(false)}>Load account data on this device</button>
      {!cloud && <div className="merge-account"><h3>Combine this device with my account</h3>
        <p>Preview a safe union before saving. Exact duplicates are kept once; conflicting identities stop without changing either copy.</p>
        <label>Profile settings after merge<select value={mergeChoices.settings} onChange={event => { onCancelMerge(); setMergeChoices(value => ({ ...value, settings: event.target.value as AccountMergeChoices['settings'] })) }}><option value="account">Keep account settings</option><option value="device">Use this device’s settings</option></select></label>
        <label>Digest preference after merge<select value={mergeChoices.digest} onChange={event => { onCancelMerge(); setMergeChoices(value => ({ ...value, digest: event.target.value as AccountMergeChoices['digest'] })) }}><option value="account">Keep account preference</option><option value="device">Use this device’s preference</option></select></label>
        <button className="secondary" disabled={!accountAdapter || accountBusy || captureBusy} onClick={() => void previewMerge()}>Preview combined data</button>
        {mergePlan && <div className="merge-preview" role="status"><p><strong>Ready to add from this device:</strong> {mergePlan.preview.added.thoughts} thoughts, {mergePlan.preview.added.canvases} canvases, {mergePlan.preview.added.events} calendar events.</p><p>{mergePlan.preview.duplicates} identical records will stay single. Nothing has been written yet.</p><div className="settings-actions"><button className="secondary" onClick={onCancelMerge}>Cancel preview</button><button className="primary" disabled={accountBusy || captureBusy} onClick={() => void confirmMerge()}>Confirm and save combined data</button></div></div>}
      </div>}
    </>}
    {cloud && <><p>Digest preference is saved with your account. Account mode currently offers the digest on demand; scheduled notices remain local-mode only.</p><label><input type="checkbox" checked={digest!.enabled} onChange={event => setDigest(setDeliveryEnabled(digest!, event.target.checked, new Date()))} />Enable 7 AM in-app digest preference</label><button className="secondary" onClick={() => { if (window.confirm('Return to local data? Export any unsaved account edits first.')) window.location.reload() }}>Return to this device’s local data</button></>}
    {accountMessage && <p role="alert">{accountMessage}</p>}
  </section>
  const downloadBackup = () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify({ ...state, model: cloud ? cloud.session.snapshot(state, preferences.value, digest!).model : serializeState(state) }, null, 2)], { type: 'application/json' }))
    const link = document.createElement('a')
    link.href = url; link.download = 'threadline-backup.json'; link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  const downloadExport = () => {
    try {
      const backup = { ...state, model: cloud ? cloud.session.snapshot(state, preferences.value, digest!).model : serializeState(state), localSettings: cloud ? JSON.stringify(preferences.value) : localStorage.getItem(SETTINGS_KEY), digestDelivery: cloud ? JSON.stringify(digest) : localStorage.getItem(DIGEST_DELIVERY_KEY), mobileInstall: cloud ? undefined : localStorage.getItem(MOBILE_INSTALL_KEY) }
      const url = URL.createObjectURL(new Blob([JSON.stringify(backup, null, 2)], { type: 'application/json' }))
      const link = document.createElement('a')
      link.href = url; link.download = 'threadline-export.json'; link.click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch { throw new Error('Export could not read browser storage. Use Download thoughts backup to preserve the work in this tab.') }
  }
  const reviewCount = reviewObjects(state.objects).length
  const capture = async (details?: CaptureDetails) => {
    const content = draft.trim()
    if (!content || capturePending.current) return
    capturePending.current = true
    setCaptureBusy(true)
    setCaptureSuccess(0)
    setCaptureError(undefined)
    try {
      const interpreted = await createInterpretedObject(content)
      const item = applyCaptureDetails(interpreted, details)
      if (clearing.current) return
      update(current => ({ ...current, objects: [item, ...current.objects] }))
      // Preserve any new typing while an asynchronous interpreter is running.
      setDraft(current => current === draft ? '' : current)
      setCaptureSuccess(value => value + 1)
    } catch {
      setCaptureError('Unable to capture this thought. Your draft is preserved; retry capturing it.')
    } finally {
      capturePending.current = false
      setCaptureBusy(false)
    }
  }
  const resolveReviewObject = (resolved: ThoughtObject) => update(current => ({
    ...current,
    objects: current.objects.map(item => item.id === resolved.id ? resolved : item),
  }))
  const withdraw = (id: string, decision: 'rejected' | 'reversed') => update(current => ({ ...current, objects: current.objects.map(item => item.id === id ? reverseObject(item, decision) : item) }))
  const saveObject = (updated: ThoughtObject) => update(current => ({ ...current, objects: current.objects.map(item => item.id === updated.id ? updateObject(item, updated) : item) }))
  const captureCanvasObject = (element: CanvasElement) => {
    const draft = canvasObjectDraft(element)
    if (!draft) return
    const item = makeObject(draft)
    update(current => ({ ...current, objects: [item, ...current.objects] }))
    setSelectedObjectId(item.id)
  }
  const selectedObject = state.objects.find(item => item.id === selectedObjectId)
  const canvasBank = canvasBankForState(state)
  const openCanvas = openCanvasId ? canvasBank.canvases.find(item => item.id === openCanvasId) : undefined
  const createCanvas = () => {
    const record = createCanvasRecord()
    update(current => addCanvas(current, record))
    setBankFocusTarget('create')
    setFocusCanvasTitle(true)
    setOpenCanvasId(record.id)
  }
  const openSavedCanvas = (id: string) => {
    setBankFocusTarget(id)
    setFocusCanvasTitle(false)
    setOpenCanvasId(id)
  }
  const exitCanvas = () => {
    canvas?.finishText()
    canvasTextSaveQueue.flush()
    setOpenCanvasId(null)
  }
  const navigate = (next: View) => {
    if (openCanvasId) { canvas?.finishText(); canvasTextSaveQueue.flush(); setOpenCanvasId(null) }
    if (next === 'canvas') setBankFocusTarget(null)
    setView(next)
  }
  if (!accountValid) return <main className="page"><h1>Account session changed</h1><p>Editing is paused. Export unsaved account work before returning to this device’s local data.</p><button onClick={downloadExport}>Download full export</button><button onClick={account.retry}>Retry checking account</button><button onClick={() => window.location.reload()}>Return to local data</button></main>
  if (clearRequested) return <ClearLocalData onBackup={downloadBackup} />
  if (initial.error) return <main className="page"><h1>Unable to load your thoughts</h1><p role="alert">{initial.error}</p><p>Editing is paused to protect your saved work. Retry after browser storage is available, or recover the saved data before continuing.</p><button className="primary" onClick={() => window.location.reload()}>Retry loading</button></main>
  return <><div role="status">{accountBusy ? 'Opening account data…' : ''}</div><main className="app-shell" inert={accountBusy || !!selectedObject}>
    <aside className="sidebar"><div className="brand"><span className="brand-mark">⊹</span><span>threadline</span></div><nav>{nav.map(item => <button className={view === item.id ? 'nav-item active' : 'nav-item'} key={item.id} aria-label={item.label} aria-current={view === item.id ? 'page' : undefined} onClick={() => navigate(item.id)}><span>{item.icon}</span>{item.label}{item.id === 'review' && reviewCount > 0 && <b>{reviewCount}</b>}</button>)}</nav><button className="sidebar-bottom" aria-label="Account settings" onClick={() => navigate('settings')}><span className="avatar">{preferences.value.displayName.slice(0, 1).toUpperCase() || '○'}</span><span>{preferences.value.displayName || 'Personal space'}</span></button></aside>
    <section className="content">
      {installHelp && <section className="install-help" aria-labelledby="install-help-title">
        <h2 id="install-help-title" ref={installHeading} tabIndex={-1}>Keep Threadline close</h2>
        <p>Capture a thought, then open Organize to review its meaning. You can use Threadline in this browser or add it to your home screen.</p>
        <details><summary>How to add Threadline to your iPhone home screen</summary>
          <ol><li>Open this hosted Threadline page in Safari.</li><li>Tap Share (the square with an upward arrow). It may be inside the More menu.</li><li>Choose Add to Home Screen. If shown, leave Open as Web App on, then tap Add.</li><li>Launch Threadline from its home screen icon.</li></ol>
          <p>Already using the home screen icon? You can keep using it. On Android or desktop, look for Install app in your browser menu, if available.</p>
        </details>
        <p>Installation does not enable mobile push notifications. Use Settings → Data to explicitly copy or load account data across devices.</p>
        <button className="secondary" onClick={closeInstallHelp}>Dismiss install help</button>
        <p className="install-help-hint">Reopen anytime in Settings → Mobile install.</p>
      </section>}
      {installMessage && <p className="storage-alert" role="status">{installMessage}</p>}
      {captureError && <div className="storage-alert" role="alert">{captureError}</div>}
      {saveError && <div className="storage-alert" role="alert"><p>{saveError}</p><button className="secondary" onClick={() => canvasTextSaveQueue.hasPending() ? canvasTextSaveQueue.retry() : void persist(true)}>Retry saving</button><button className="secondary" onClick={downloadBackup}>Download backup</button></div>}
      <>
        {cloud ? <AccountDigest state={state} visible={view === 'today' || view === 'digest'} /> : view === 'today' ? <details className="digest-entry compact-disclosure">
          <summary>Morning Digest<span className="disclosure-caret" aria-hidden="true" /></summary>
          <MorningDigest state={state} visible inline onShow={() => setView('digest')} />
        </details> : <MorningDigest state={state} visible={view === 'digest'} onShow={() => setView('digest')} />}
      </>
      {view === 'settings' && <SettingsPage accountActive={!!cloud} dataControls={dataControls} installOpener={installOpener} onInstallHelp={() => { setInstallHelp(true); setFocusInstallHelp(true); installHeading.current?.focus() }} settings={preferences.value} error={preferences.error} authState={account.state} onRetryAccount={account.retry} onSave={value => {
        onCancelMerge()
        if (!cloud) writeSettings(localStorage, value)
        setPreferences({ value, error: '' })
      }} onResetSettings={() => { onCancelMerge(); setPreferences({ value: cloud ? { ...defaultSettings } : resetSettings(localStorage), error: '' }) }} onExport={downloadExport} onBackup={downloadBackup} onClear={() => { clearing.current = true; setClearRequested(true) }} onOpenDigest={() => setView('digest')} />}
      {view === 'today' && <Today objects={state.objects} relationships={state.model?.relationships ?? []} onCapture={() => setView('capture')} onOpen={setSelectedObjectId} />}
      {view === 'beta-home' && <BetaHome state={state} displayName={preferences.value.displayName} onNavigate={setView} />}
      {view === 'capture' && <Capture draft={draft} busy={captureBusy} success={saveError ? 0 : captureSuccess} onDraft={value => { setDraft(value); setCaptureSuccess(0) }} onCapture={capture} />}
      {view === 'review' && <Review objects={state.objects} onResolve={resolveReviewObject} onReject={id => withdraw(id, 'rejected')} onOpen={setSelectedObjectId} />}
      {view === 'review' && <details className="timing-details"><summary>Timing</summary><TemporalReview state={state} onUpdate={update} /></details>}
      {view === 'commitments' && <Commitments objects={state.objects} onAdd={() => { setDraft(''); setView('capture') }} onOpen={setSelectedObjectId} />}
      {view === 'calendar' && <CalendarView state={state} onOpen={setSelectedObjectId} onUpdate={update} />}
      {view === 'canvas' && (!openCanvas || !canvas ? <CanvasBank bank={canvasBank} focusTarget={bankFocusTarget} onCreate={createCanvas} onOpen={openSavedCanvas} /> : <Canvas key={openCanvas.id} title={openCanvas.title} autoFocusTitle={focusCanvasTitle} elements={openCanvas.elements} viewport={openCanvas.viewport ?? DEFAULT_CANVAS_VIEWPORT} onTitle={title => { update(current => renameCanvas(current, openCanvas.id, title)); setFocusCanvasTitle(false) }} onViewport={canvas.setViewport} onCommit={canvas.commit} onText={(id, text) => { canvas.editText(id, text); if (cloud) { canvasTextSaveQueue.edited(); setCloudStatus('Account changes waiting to save…') } }} onFinishText={() => { canvas.finishText(); canvasTextSaveQueue.flush() }} canUndo={canvas.canUndo} canRedo={canvas.canRedo} onUndo={canvas.undo} onRedo={canvas.redo} onCaptureObject={captureCanvasObject} onExit={exitCanvas} saveStatus={saveError ? 'Not saved — use Retry saving or Download backup above.' : cloud ? cloudStatus : 'Saved on this device'} />)}
    </section>
  </main>{selectedObject && <ObjectPanel object={selectedObject} history={reviewTextSnapshot(state, selectedObject.id)} onClose={() => setSelectedObjectId(null)} onSave={saveObject}
      onRevise={summary => update(current => reviseInterpretation(current, selectedObject.id, summary))}
      onCorrect={content => update(current => correctOriginal(current, selectedObject.id, content, true))}
      onReverse={() => withdraw(selectedObject.id, 'reversed')} />}
  </>
}

function AccountSection({ state, onRetry, active }: { state: AuthState; onRetry: () => void; active: boolean }) {
  const [email, setEmail] = useState('')
  const [code, setCode] = useState('')
  return <section className="settings-card"><h2>Account</h2>
    <p role="status" className={state.status === 'signed-in' ? 'status-pill positive' : 'status-pill'}>{accountLabel(state)}</p>
    <p>{dataOwnershipLabel(state, active)}</p>
    {'message' in state && state.message && <p role={state.status === 'error' ? 'alert' : 'status'}>{state.message}</p>}
    {state.status === 'unconfigured' && <button className="secondary" disabled>Log in with email — unavailable</button>}
    {state.status === 'signed-out' && <form className="account-login" onSubmit={event => { event.preventDefault(); setEmail(email.trim()); setCode(''); void auth.act('login', email) }}>
      <label>Email address<input type="email" autoComplete="email" required value={email} onChange={event => setEmail(event.target.value)} /></label>
      <button className="primary">Email me a sign-in code and link</button>
    </form>}
    {state.status === 'signed-out' && <form className="account-code" onSubmit={event => { event.preventDefault(); void auth.act('verify-code', email, code) }}>
      <p>Already have a code? Enter the email address above and the code from your email here to sign in to this app, even if you requested it in a browser.</p>
      <label>Email sign-in code<input type="text" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6,10}" maxLength={10} required value={code} onChange={event => setCode(event.target.value.replace(/\D/g, '').slice(0, 10))} /></label>
      <button className="primary">Sign in with code</button>
    </form>}
    {state.status === 'loading' && <button className="secondary" disabled>Please wait…</button>}
    {state.status === 'signed-in' && <button className="secondary" onClick={() => { void auth.act('logout') }}>Log out</button>}
    {state.status === 'error' && <button className="secondary" onClick={onRetry}>Retry checking account</button>}
  </section>
}

function AiInterpretationSection() {
  return <section className="settings-card"><h2>AI interpretation</h2>
    <p className={aiProviderStatus.enabled ? 'status-pill positive' : 'status-pill muted'}>{aiProviderStatus.label}</p>
    <p>{aiProviderStatus.description}</p>
    <p>AI proposals remain review-only. Threadline cannot confirm actions, commitments, calendar events or notifications without your explicit confirmation.</p>
    <button className="secondary" disabled>{aiProviderStatus.enabled ? 'Provider configured by feature flag' : 'Provider not enabled'}</button>
  </section>
}

function MobileInstallSection({ installOpener, onInstallHelp }: { installOpener: React.RefObject<HTMLButtonElement | null>; onInstallHelp: () => void }) {
  const [installed] = useState(() => typeof window !== 'undefined' && Boolean(
    window.matchMedia?.('(display-mode: standalone)').matches ||
    (window.navigator as unknown as { standalone?: boolean }).standalone,
  ))
  return <section className="settings-card"><h2>Mobile install</h2>
    <p className={installed ? 'status-pill positive' : 'status-pill'}>{installed ? 'Installed' : 'Installable now'}</p>
    {installed ? <p>Threadline is running from your home screen right now.</p> : <>
      <p>Threadline can be added to your phone's home screen straight from your browser. Mobile push notifications are not available.</p>
      <button ref={installOpener} className="secondary" onClick={onInstallHelp}>Show home screen install help</button>
    </>}
  </section>
}

function DigestSection({ onOpen }: { onOpen: () => void }) {
  return <section className="settings-card"><h2>Digest</h2>
    <p className="status-pill positive">Available</p>
    <p>The Morning Digest view already works and is reachable from Today. Scheduled delivery and notifications are not built yet — opening it here shows today's digest on demand.</p>
    <button className="secondary" onClick={onOpen}>Open Morning Digest</button>
  </section>
}

function SettingsPage({ accountActive, dataControls, installOpener, onInstallHelp, settings, error, authState, onRetryAccount, onSave, onResetSettings, onExport, onBackup, onClear, onOpenDigest }: {
  accountActive: boolean; dataControls: React.ReactNode
  installOpener: React.RefObject<HTMLButtonElement | null>; onInstallHelp: () => void
  settings: LocalSettings; error: string; authState: AuthState; onRetryAccount: () => void
  onSave: (value: LocalSettings) => void; onResetSettings: () => void
  onExport: () => void; onBackup: () => void; onClear: () => void; onOpenDigest: () => void
}) {
  const [draft, setDraft] = useState(settings)
  const [message, setMessage] = useState('')
  const [failure, setFailure] = useState('')
  const [confirming, setConfirming] = useState(false)
  const [confirmation, setConfirmation] = useState('')
  return <div className="page settings-page"><Header eyebrow="Your space" title="Settings / Account" />
    <AccountSection active={accountActive} state={authState} onRetry={onRetryAccount} />
    <section className="settings-card"><h2>Profile</h2><p>{dataOwnershipLabel(authState, accountActive)}</p>
      {error && <p role="alert">{error}</p>}
      {error && <div className="settings-recovery"><p>Resetting affects only your display name and start page — it does not touch your thoughts, canvas or digest settings.</p><button className="secondary" onClick={() => { setFailure(''); setMessage(''); try { onResetSettings(); setDraft(defaultSettings); setMessage('Settings reset to defaults on this device.') } catch { setFailure('Settings could not be reset. Check browser storage and retry.') } }}>Reset settings to defaults</button></div>}
      <form onSubmit={event => { event.preventDefault(); setFailure(''); setMessage(''); try { onSave({ ...draft, displayName: draft.displayName.trim() }); setDraft({ ...draft, displayName: draft.displayName.trim() }); setMessage(accountActive ? 'Settings updated. Account save status is shown in Data.' : 'Settings saved on this device.') } catch { setFailure('Settings could not be saved. Your edits are still here; check browser storage and retry.') } }}>
        <fieldset disabled={!!error}><label>Display name / profile label<input maxLength={80} autoComplete="nickname" value={draft.displayName} onChange={event => setDraft({ ...draft, displayName: event.target.value })} placeholder="Personal space" /></label>
          <label>Open Threadline to<select value={draft.startPage} onChange={event => setDraft({ ...draft, startPage: event.target.value as LocalSettings['startPage'] })}><option value="today">Today</option><option value="capture">Capture</option><option value="canvas">Canvas Bank</option></select></label>
          <button className="primary" type="submit">Save settings</button></fieldset>
      </form><p role="status">{message}</p>
    </section>
    {dataControls}
    <AiInterpretationSection />
    <section className="settings-card"><h2>Beta previews and build room</h2><p>Replay the landing page and first-run tutorial without changing your saved onboarding progress, or open the hosted build dashboard and task queue.</p><div className="settings-actions"><a className="secondary" href="/preview/landing">Test landing page and tutorial</a><a className="secondary" href="/dashboard">Open agent dashboard</a></div></section>
    <MobileInstallSection installOpener={installOpener} onInstallHelp={onInstallHelp} />
    <DigestSection onOpen={onOpenDigest} />
    <section className="settings-card"><h2>Recovery</h2><p>Export thoughts, canvas, local profile and digest preferences as JSON. Backup import is not available yet.</p><div className="settings-actions"><button className="secondary" onClick={() => { setFailure(''); try { onExport() } catch (error) { setFailure((error as Error).message) } }}>Download full export</button><button className="secondary" onClick={onBackup}>Download thoughts backup</button></div>
      <p>Clearing removes all Threadline thoughts, canvas and preferences from this browser, including drafts and session undo history. This cannot be undone. Download a backup first and close other Threadline tabs.</p>
      {accountActive ? <p>Return to local mode before clearing this device’s local data.</p> : !confirming ? <button className="secondary danger-button" onClick={() => setConfirming(true)}>Clear local data…</button> : <form className="clear-confirmation" onSubmit={event => { event.preventDefault(); if (confirmation === 'CLEAR') onClear() }}><label>Type CLEAR to permanently clear local data<input autoFocus autoComplete="off" value={confirmation} onChange={event => setConfirmation(event.target.value)} /></label><div className="settings-actions"><button type="button" className="secondary" onClick={() => { setConfirming(false); setConfirmation('') }}>Cancel</button><button className="primary danger-button" disabled={confirmation !== 'CLEAR'}>Permanently clear local data</button></div></form>}
    </section>{failure && <p role="alert">{failure}</p>}
  </div>
}

function ClearLocalData({ onBackup }: { onBackup: () => void }) {
  const [error, setError] = useState('')
  const [done, setDone] = useState(false)
  const clear = () => {
    try { clearLocalData(localStorage, 'CLEAR'); setError(''); setDone(true) }
    catch { setError('Clearing could not finish. Some local data may already be cleared. Editing is paused; retry to finish.') }
  }
  // Mounted only after confirmation, with the digest and other writers unmounted.
  useEffect(clear, [])
  return <main className="page"><h1>{done ? 'Local data cleared' : 'Clearing local data'}</h1>{error && <p role="alert">{error}</p>}{done ? <button className="primary" onClick={() => window.location.reload()}>Start fresh</button> : <div className="settings-actions"><button className="secondary" onClick={clear}>Retry clearing</button><button className="secondary" onClick={onBackup}>Download thoughts backup</button></div>}</main>
}

function Header({ eyebrow, title, action }: { eyebrow: string; title: string; action?: React.ReactNode }) { return <header className="page-header"><div><p className="eyebrow">{eyebrow}</p><h1>{title}</h1></div>{action}</header> }
function Today({ objects, relationships, onCapture, onOpen }: { objects: ThoughtObject[]; relationships: SemanticRelationship[]; onCapture: () => void; onOpen: (id: string) => void }) {
  const commitments = fixedCommitments(objects)
  const actions = confirmedActions(objects, relationships)
  const focus = actions[0]
  const recent = recentObjects(objects)
  const date = new Intl.DateTimeFormat('en-US', { weekday: 'long', month: 'long', day: 'numeric' }).format(new Date())
  return <div className="page"><Header eyebrow={date} title="Make space for the work that matters." action={<button className="primary" onClick={onCapture}>Capture a thought <span>↵</span></button>} />
    <section className="today-grid"><div className="focus-card"><p className="section-label">Recommended focus</p><h2>{focus?.originalContent ?? 'Start with a clean capture'}</h2><p>One meaningful action, selected from confirmed work—not an overflowing task list.</p><div className="focus-meta"><span>◒ {focus?.metadata.effort ?? 'small'} effort</span><span>◌ {focus?.metadata.attentionLoad ?? 'low'} attention</span></div><button className="quiet-button" disabled={!focus} onClick={() => focus && onOpen(focus.id)}>{focus ? `Open ${objectLabels[focus.kind].toLowerCase()}` : 'Capture first'} →</button></div>
      <div className="day-summary"><p className="section-label">Attention budget</p><div className="orb"><b>{Math.max(2, 5 - actions.length)}</b><span>open hours</span></div><p>Keep the plan spacious. It can move as your day changes.</p></div></section>
    <section className="list-section"><div className="section-heading"><div><p className="section-label">Fixed commitments</p><h2>Today</h2></div><span>{commitments.length} scheduled</span></div>{commitments.length ? commitments.map(item => <ObjectRow item={item} key={item.id} onOpen={onOpen} accent="commitment" />) : <Empty text="No fixed commitments today. Your execution plan is free to adapt." />}</section>
    <section className="list-section"><div className="section-heading"><div><p className="section-label">Object workbench</p><h2>Recent captures</h2></div><span>{recent.length} visible</span></div>{recent.length ? recent.map(item => <ObjectRow item={item} key={item.id} onOpen={onOpen} />) : <Empty text="Capture something and it will appear here for shaping." />}</section>
  </div>
}
type CaptureDetails = { folder: '' | 'Personal' | 'Business'; date: string; time: string }
const emptyCaptureDetails: CaptureDetails = { folder: '', date: '', time: '' }
function applyCaptureDetails(item: ThoughtObject, details = emptyCaptureDetails): ThoughtObject {
  const context = details.folder || item.context
  const suggestedDate = details.date ? [details.date, details.time].filter(Boolean).join(' ') : item.interpretation.suggestedDate
  return { ...item, context, metadata: { ...item.metadata, deadline: details.date || item.metadata.deadline }, interpretation: { ...item.interpretation, suggestedDate } }
}
function Capture({ draft, busy, success, onDraft, onCapture }: { draft: string; busy: boolean; success: number; onDraft: (v: string) => void; onCapture: (details?: CaptureDetails) => void }) {
  const input = useRef<HTMLTextAreaElement>(null)
  const [detailsOpen, setDetailsOpen] = useState(false)
  const [details, setDetails] = useState<CaptureDetails>(emptyCaptureDetails)
  useEffect(() => { if (success) { input.current?.focus(); setDetails(emptyCaptureDetails); setDetailsOpen(false) } }, [success])
  return <div className="page capture-page"><Header eyebrow="Raw capture" title="What’s on your mind?" />
    <div className="capture-box"><textarea ref={input} autoFocus aria-label="Raw thought" value={draft} onChange={event => onDraft(event.target.value)} placeholder="A thought, a loose end, an idea…" onKeyDown={event => { if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') { event.preventDefault(); onCapture(details) } }} />
      {detailsOpen && <div className="capture-details"><label>Folder<select value={details.folder} onChange={event => setDetails(current => ({ ...current, folder: event.target.value as CaptureDetails['folder'] }))}><option value="">Choose later</option><option value="Personal">Personal</option><option value="Business">Business</option></select></label><label>Date<input type="date" value={details.date} onChange={event => setDetails(current => ({ ...current, date: event.target.value }))} /></label><label>Time<input type="time" value={details.time} onChange={event => setDetails(current => ({ ...current, time: event.target.value }))} /></label></div>}
      <div className="capture-footer"><span role="status">{success > 0 && <span className="capture-success">✓ Captured</span>}</span><button className="secondary" type="button" aria-expanded={detailsOpen} onClick={() => setDetailsOpen(open => !open)}>Details</button><button className="primary" disabled={busy || !draft.trim()} onClick={() => onCapture(details)}>{busy ? 'Capturing…' : 'Capture'}</button></div>
    </div>
  </div>
}
export function Review({ objects, onResolve, onReject, onOpen }: { objects: ThoughtObject[]; onResolve: (object: ThoughtObject) => void; onReject: (id: string) => void; onOpen: (id: string) => void }) {
  const [rejecting, setRejecting] = useState<string | null>(null)
  const pending = reviewObjects(objects)
  const ideas = resolvedIdeas(objects)
  const folders = bankObjects(objects)
  return <div className="page organize-page"><Header eyebrow="Your thoughts" title="Organize" /><details className="compact-disclosure review-disclosure"><summary>Review {pending.length}<span className="disclosure-caret" aria-hidden="true" /></summary>{pending.length === 0 ? <Empty text="All caught up." /> : <div className="review-list">{pending.map(item => <article className="review-card" key={item.id}>
    <button className="review-dismiss" aria-label={`Dismiss ${item.interpretation.summary}`} onClick={() => setRejecting(item.id)}>×</button>
    <div className="source-line"><span>{item.currentContent ? 'Current thought · original preserved' : 'Current thought'}</span><time>{new Date(item.createdAt).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}</time></div><blockquote>{item.currentContent ?? item.originalContent}</blockquote>
    <div className="proposal"><div><p>Proposed {objectLabels[item.kind]}</p><p>{item.interpretation.summary}</p>{item.kind === 'commitment' && <small>Commitment setup remains in Review until its continuation is available.</small>}{item.kind === 'reminder' && <small>Reminder setup remains in Review until its continuation is available.</small>}</div></div>
    {rejecting === item.id ? <div className="reject-confirmation" role="group" aria-label="Confirm dismissal"><p>Dismiss this proposal from Review? Your original capture and history are kept.</p><button className="secondary" autoFocus onClick={() => setRejecting(null)}>Cancel</button><button className="secondary danger-button" onClick={() => { onReject(item.id); setRejecting(null) }}>Dismiss from Review</button></div> : <ReviewResolution object={item} onComplete={onResolve} onEdit={() => onOpen(item.id)} />}
  </article>)}</div>}</details>
    <section className="bank-section" aria-labelledby="ideas-heading"><h2 id="ideas-heading">Ideas</h2>
      {ideas.length ? ideas.map(item => <ObjectRow key={item.id} item={item} onOpen={onOpen} />) : <Empty text="No resolved ideas yet." />}
    </section>
    <section className="bank-section" aria-labelledby="bank-heading"><h2 id="bank-heading">Thought folders</h2>
      <p>Filed thoughts grouped by context: Personal or Home, Business or Work. Other contexts stay Unfiled. Use Edit → Context or project to change the grouping.</p>
      {bankFolders.map(folder => <details className="compact-disclosure bank-folder" key={folder}>
        <summary>{folder} <span>{folders[folder].length}</span><span className="disclosure-caret" aria-hidden="true" /></summary>
        {folders[folder].length ? folders[folder].map(item => <ObjectRow key={item.id} item={item} onOpen={onOpen} />) : <Empty text="No filed thoughts here yet." />}
      </details>)}
    </section>
  </div>
}
function ObjectRow({ item, onOpen, accent }: { item: ThoughtObject; onOpen: (id: string) => void; accent?: 'commitment' }) {
  const detail = item.interpretation.suggestedDate ?? item.context ?? item.interpretation.rationale
  return <button className={`commitment-row clickable-row ${accent === 'commitment' ? 'commitment-accent' : ''}`} onClick={() => onOpen(item.id)}><span className="time-dot"/><div><strong>{item.originalContent}</strong><small>{detail}</small></div><span className="status-chip">{item.status}</span><span className="kind-chip">{objectLabels[item.kind]}</span></button>
}
function Commitments({ objects, onAdd, onOpen }: { objects: ThoughtObject[]; onAdd: () => void; onOpen: (id: string) => void }) { const items = fixedCommitments(objects); const now = new Date(); return <div className="page"><Header eyebrow="External time" title="Commitments stay put." action={<button className="primary" onClick={onAdd}>Add commitment</button>} /><p className="lede">Meetings, appointments, deadlines, and events. This is separate from the flexible execution plan.</p><div className="calendar-grid"><div className="calendar-day"><p className="section-label">Today</p><b>{now.getDate()}</b><span>{new Intl.DateTimeFormat('en-US', { weekday: 'long' }).format(now)}</span></div><div className="calendar-list">{items.length ? items.map(item => <ObjectRow item={item} key={item.id} onOpen={onOpen} accent="commitment" />) : <Empty text="No commitments captured yet." />}</div></div></div> }
function ObjectPanel({ object, history, onClose, onSave, onRevise, onCorrect, onReverse }: { object: ThoughtObject; history: ReturnType<typeof reviewTextSnapshot>; onClose: () => void; onSave: (object: ThoughtObject) => void; onRevise: (summary: string) => void; onCorrect: (content: string) => void; onReverse: () => void }) {
  const [draft, setDraft] = useState(object)
  const [revision, setRevision] = useState(object.interpretation.summary)
  const [correction, setCorrection] = useState(history.currentText)
  const closeButton = useRef<HTMLButtonElement>(null)
  const returnFocus = useRef<HTMLElement | null>(document.activeElement instanceof HTMLElement ? document.activeElement : null)
  useEffect(() => setDraft(object), [object])
  useEffect(() => setRevision(object.interpretation.summary), [object.id, object.interpretation.summary])
  useEffect(() => setCorrection(history.currentText), [object.id, history.currentText])
  const awaitingConfirmation = draft.kind !== object.kind || object.status === 'review' || object.status === 'inbox' || ((object.kind === 'action' || object.kind === 'commitment') && !hasConfirmation(object))
  const hasUnsavedFieldEdits = JSON.stringify(draft) !== JSON.stringify(object)
  const hasUnsavedThoughtDrafts = hasUnsavedReviewDrafts(object, history.currentText, correction, revision)
  const confirmDiscard = (includeFields: boolean) => {
    if (!(hasUnsavedThoughtDrafts || (includeFields && hasUnsavedFieldEdits))) return true
    return window.confirm('Discard the unsaved changes in this panel? Saved versions and the original capture will stay available.')
  }
  const closePanel = () => { if (confirmDiscard(true)) onClose() }
  const saveAndClose = (updated: ThoughtObject) => {
    if (!confirmDiscard(false)) return
    onSave(updated)
    onClose()
  }
  const reverseAndClose = () => {
    if (!confirmDiscard(true)) return
    onReverse()
    onClose()
  }
  useEffect(() => {
    closeButton.current?.focus()
    const opener = returnFocus.current
    return () => opener?.focus()
  }, [])
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      event.preventDefault()
      closePanel()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  })
  const field = (key: keyof ThoughtObject, value: unknown) => setDraft(current => ({ ...current, [key]: value }))
  const metadata = (key: keyof ThoughtObject['metadata'], value: unknown) => setDraft(current => ({ ...current, metadata: { ...current.metadata, [key]: value || undefined } as ThoughtObject['metadata'] }))
  const scoreSelect = (key: 'urgency' | 'strategicImportance' | 'roi') => <select value={draft.metadata[key] ?? ''} onChange={event => metadata(key, event.target.value ? Number(event.target.value) as 1 | 2 | 3 | 4 | 5 : undefined)}>
    <option value="">Unspecified</option>{[1, 2, 3, 4, 5].map(value => <option key={value} value={value}>{value}</option>)}
  </select>
  const folderValue = draft.context === 'Personal' || draft.context === 'Business' ? draft.context : ''
  const proposedTime = draft.interpretation.suggestedDate?.match(/(?:^| )(\d{2}:\d{2})(?:$| )/)?.[1] ?? ''
  const setProposedTime = (time: string) => setDraft(current => ({ ...current, interpretation: { ...current.interpretation, suggestedDate: [current.metadata.deadline, time].filter(Boolean).join(' ') || undefined } }))
  const sourceEditNote = object.source === 'voice'
    ? 'The recorded voice source stays unchanged. You can revise its organized meaning below.'
    : 'The captured canvas expression stays unchanged. You can revise its organized meaning below.'
  return <div className="panel-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) closePanel() }}>
    <aside className="object-panel" role="dialog" aria-modal="true" aria-labelledby="object-panel-title">
      <header><div><p className="eyebrow">Object workbench</p><h2 id="object-panel-title">Shape this thought</h2></div><button ref={closeButton} className="close-button" onClick={closePanel} aria-label="Close object details">×</button></header>
      <div className="panel-scroll">
        <section className="raw-thought"><p className="section-label">Current thought</p><p>{history.currentText}</p><small>{object.source} · first captured {new Date(object.createdAt).toLocaleString()}</small>{history.currentText !== history.immutableSource && <p className="preserved-note">The first capture is preserved in version history.</p>}</section>
        <section className="interpretation"><p className="section-label">AI proposal</p><strong>{object.interpretation.summary}</strong><small>{Math.round(object.confidence * 100)}% confident · {object.interpretation.rationale}</small></section>
        <section className="thought-editors" aria-labelledby="thought-editing-heading"><div><p className="section-label">Edit without losing history</p><h3 id="thought-editing-heading">Revise this thought</h3><p>Each save adds a version. The original capture always stays available below.</p></div>
          {hasUnsavedFieldEdits && <p role="status">Save your object field changes before revising the thought text or organized meaning.</p>}
          {object.source === 'text' ? <><label>Thought text<textarea value={correction} onChange={event => setCorrection(event.target.value)} /></label>
          <button className="secondary" disabled={hasUnsavedFieldEdits || !correction.trim() || correction.trim() === history.currentText} onClick={() => { if (window.confirm('Save this as the current thought text while keeping the original capture?')) onCorrect(correction) }}>Save text version</button></> : <p className="source-edit-note" role="note">{sourceEditNote}</p>}
          <label>Organized meaning<textarea value={revision} onChange={event => setRevision(event.target.value)} /></label>
          {revisionNeedsReconfirmation(object) && <p role="note">{revisionReviewNotice(object)}</p>}
          <button className="secondary" disabled={hasUnsavedFieldEdits || !revision.trim() || revision.trim() === object.interpretation.summary} onClick={() => onRevise(revision)}>Save meaning version</button>
        </section>
        {awaitingConfirmation && <p>Complete and Archive require confirmation in Organize.</p>}
        <div className="form-grid">
          <label>Type<select value={draft.kind} onChange={event => field('kind', event.target.value as ObjectKind)}>{(Object.keys(objectLabels) as ObjectKind[]).map(kind => <option key={kind} value={kind}>{objectLabels[kind]}</option>)}</select></label>
          <label>Folder<select value={folderValue} onChange={event => field('context', event.target.value || undefined)}><option value="">Unfiled</option><option value="Personal">Personal</option><option value="Business">Business</option></select></label>
          <label>Proposed date<input type="date" value={draft.metadata.deadline ?? ''} onChange={event => metadata('deadline', event.target.value)} /></label>
          <label>Time<input type="time" value={proposedTime} onChange={event => setProposedTime(event.target.value)} /></label>
          <label>Effort<select value={draft.metadata.effort ?? ''} onChange={event => metadata('effort', event.target.value)}><option value="">Unspecified</option><option value="small">Small</option><option value="medium">Medium</option><option value="large">Large</option></select></label>
          <details className="wide advanced-object-details"><summary>Advanced</summary><div className="form-grid"><label>Status<select disabled={awaitingConfirmation} value={awaitingConfirmation ? 'review' : draft.status} onChange={event => field('status', event.target.value as ThoughtObject['status'])}>{['inbox', 'review', 'confirmed', 'complete', 'archived'].map(status => <option key={status} value={status}>{status}</option>)}</select></label><label>Urgency{scoreSelect('urgency')}</label></div></details>
        </div>
        <details className="thought-progression" open><summary>Version history ({history.progression.length})</summary><ol>{history.progression.slice().reverse().map(entry => <li key={entry.id}><div><strong>{entry.label}</strong><time>{new Date(entry.at).toLocaleString()}</time></div><p>{entry.text}</p>{entry.previousText && <details><summary>Previous version</summary><p>{entry.previousText}</p></details>}</li>)}</ol></details>
        <details><summary>Decision history ({object.history.length})</summary><ol>{object.history.slice().reverse().map((entry, index) => <li key={`${entry.at}-${index}`}><p>{entry.event}</p><time>{entry.at}</time>{entry.confirmation && <small>{entry.confirmation.transition}: {entry.confirmation.summary}</small>}</li>)}</ol></details>
        {hasConfirmation(object) && <><p>Return this item to Organize.</p><button className="secondary" onClick={reverseAndClose}>Reverse confirmation</button></>}
      </div>
      <footer><button disabled={awaitingConfirmation} className="secondary" onClick={() => saveAndClose(setObjectStatus(draft, 'archived'))}>Archive</button><button disabled={awaitingConfirmation} className="secondary" onClick={() => saveAndClose(setObjectStatus(draft, 'complete'))}>Complete</button><button className="primary" onClick={() => saveAndClose(draft)}>Save changes</button></footer>
    </aside>
  </div>
}
function Empty({ text }: { text: string }) { return <div className="empty">{text}</div> }

function AccountDigest({ state, visible }: { state: AppState; visible: boolean }) {
  if (!visible) return null
  const digest = buildMorningDigest(reconcileLegacyUi(state), new Date())
  return <details className="digest-entry compact-disclosure"><summary>Morning Digest</summary>
    <p>{digest.day} · Account data · On demand</p>
    <h3>Confirmed events today</h3><ul>{digest.fixedToday.map(({ event }) => <li key={event.id}>{event.title} — {event.startsAt}</li>)}</ul>
    <h3>Fixed deadlines</h3><ul>{digest.upcoming.map(item => <li key={item.id}>{item.summary} — {item.metadata.deadline}</li>)}</ul>
    <h3>Confirmed obligations — schedule unverified</h3><ul>{digest.unscheduledCommitments.map(item => <li key={item.id}>{item.summary}</li>)}</ul>
    <h3>Recommended execution</h3><ul>{digest.recommended.map(item => <li key={item.id}>{item.summary}</li>)}</ul>
    <h3>Decisions needed</h3><ul>{digest.needsReview.map(item => <li key={item.id}>{item.summary}</li>)}</ul>
    <h3>Project and objective status</h3><ul>{digest.projectSignals.map(item => <li key={item.id}>{item.summary} — {item.status}</li>)}</ul>
  </details>
}
