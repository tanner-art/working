import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { auth, supabase, type AuthState } from './auth'
import { capacitySummary, effectiveWorkerHealth, emptyQueueFilters, failureClassification, filterFactoryFeatures, packageIndex, readinessReason, recommendedFailureAction, visibleAttention, visibleReviews, workerConstraintDetails, type QueueFilters } from './buildDashboard'
import { formatDuration, formatFactoryState, formatRelativeTime, parseFactoryControlSnapshot, safeExternalUrl, type CapacitySource, type FactoryCapacityScope, type FactoryControlSnapshot, type FactoryEvidence, type FactoryPackage, type FactoryState, type FactoryUsageInvocation, type FactoryWorker } from './factoryControl'

export type View = 'overview' | 'queue' | 'workers' | 'reviews' | 'capacity' | 'history' | 'failures'
type DashboardTarget = { view: View; queueState?: FactoryState }
type LoadState = { status: 'idle' | 'loading' } | { status: 'error'; message: string } | { status: 'ready'; snapshot: FactoryControlSnapshot; refreshing: boolean }

const views: Array<{ id: View; label: string }> = [
  { id: 'overview', label: 'Overview' }, { id: 'queue', label: 'Queue' }, { id: 'workers', label: 'Workers' },
  { id: 'reviews', label: 'Reviews' }, { id: 'capacity', label: 'Capacity' }, { id: 'history', label: 'History / provenance' },
  { id: 'failures', label: 'Failures / attention' },
]

function useFactoryAuth() {
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

function useFactorySnapshot(account: AuthState) {
  const [load, setLoad] = useState<LoadState>({ status: 'idle' })
  const refresh = useCallback(async () => {
    if (account.status !== 'signed-in' || !supabase) return
    setLoad(current => current.status === 'ready' ? { ...current, refreshing: true } : { status: 'loading' })
    try {
      const { data, error } = await supabase.auth.getSession()
      const token = data.session?.access_token
      if (error || !token) throw new Error('Your account session could not be verified. Sign in again.')
      const result = await fetch('/api/factory-control', { method: 'GET', headers: { authorization: `Bearer ${token}` }, cache: 'no-store' })
      const body = await result.json() as { message?: unknown }
      if (!result.ok) throw new Error(typeof body.message === 'string' ? body.message : 'Factory visibility is temporarily unavailable.')
      setLoad({ status: 'ready', snapshot: parseFactoryControlSnapshot(body), refreshing: false })
    } catch (error) {
      setLoad({ status: 'error', message: error instanceof Error ? error.message : 'Factory visibility is temporarily unavailable.' })
    }
  }, [account])
  useEffect(() => {
    if (account.status !== 'signed-in') { setLoad({ status: 'idle' }); return }
    void refresh()
    const interval = window.setInterval(() => { void refresh() }, 60_000)
    return () => window.clearInterval(interval)
  }, [account.status, account.status === 'signed-in' ? account.session.user.id : '', refresh])
  return { load, refresh }
}

export function BuildDashboard() {
  const account = useFactoryAuth()
  const projection = useFactorySnapshot(account.state)
  const [target, setTarget] = useState<DashboardTarget>({ view: 'overview' })
  useEffect(() => { const previous = document.title; document.title = 'Factory Control Center · Threadline'; return () => { document.title = previous } }, [])
  if (account.state.status !== 'signed-in') return <FactorySignIn state={account.state} onRetry={account.retry} />
  return <main className="factory-shell">
    <aside className="factory-sidebar">
      <div className="factory-brand"><span aria-hidden="true">TF</span><div><strong>Threadline</strong><small>Factory Control Center</small></div></div>
      <nav aria-label="Control Center views">{views.map(item => <button type="button" className={target.view === item.id ? 'active' : ''} aria-current={target.view === item.id ? 'page' : undefined} onClick={() => setTarget({ view: item.id })} key={item.id}>{item.label}</button>)}</nav>
      <div className="factory-sidebar-foot"><span className="readonly-pill">Read-only</span><a href="/">Return to Threadline</a></div>
    </aside>
    <section className="factory-workspace">
      <header className="factory-topbar"><div><p className="factory-eyebrow">Live Factory visibility</p><h1>{views.find(item => item.id === target.view)?.label}</h1></div><div className="factory-account"><span>{account.state.session.user.email ?? 'Authenticated owner'}</span><button type="button" className="factory-button secondary" onClick={() => void auth.act('logout')}>Sign out</button></div></header>
      {projection.load.status === 'loading' && <LoadingPanel />}
      {projection.load.status === 'idle' && <LoadingPanel />}
      {projection.load.status === 'error' && <ErrorPanel message={projection.load.message} onRetry={() => void projection.refresh()} />}
      {projection.load.status === 'ready' && <DashboardView view={target.view} queueState={target.queueState} snapshot={projection.load.snapshot} refreshing={projection.load.refreshing} onRefresh={() => void projection.refresh()} onNavigate={setTarget} />}
    </section>
  </main>
}

function FactorySignIn({ state, onRetry }: { state: AuthState; onRetry: () => void }) {
  const [email, setEmail] = useState('')
  const [code, setCode] = useState('')
  return <main className="factory-auth"><section className="factory-auth-card" aria-labelledby="factory-sign-in-title">
    <p className="factory-eyebrow">Threadline Factory</p><h1 id="factory-sign-in-title">Control Center</h1><p>Sign in with your Threadline account to view verified Registry state.</p>
    {state.status === 'unconfigured' && <p className="factory-alert" role="alert">{state.message}</p>}
    {state.status === 'error' && <><p className="factory-alert" role="alert">{state.message}</p><button type="button" className="factory-button" onClick={onRetry}>Retry account check</button></>}
    {state.status === 'loading' && <p role="status">Checking your account…</p>}
    {state.status === 'signed-out' && <>
      {state.message && <p className="factory-notice" role={state.emailCodeSent ? 'status' : 'alert'}>{state.message}</p>}
      <form onSubmit={event => { event.preventDefault(); setEmail(email.trim()); setCode(''); void auth.act('login', email) }}><label htmlFor="factory-email">Email address</label><input id="factory-email" type="email" autoComplete="email" required value={email} onChange={event => setEmail(event.target.value)} /><button className="factory-button" type="submit">Send sign-in email</button></form>
      <form onSubmit={event => { event.preventDefault(); void auth.act('verify-code', email, code) }}><label htmlFor="factory-code">Email code</label><input id="factory-code" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6,10}" maxLength={10} required value={code} onChange={event => setCode(event.target.value.replace(/\D/g, '').slice(0, 10))} /><button className="factory-button" type="submit">Open Control Center</button></form>
    </>}
  </section></main>
}

export function DashboardView({ view, queueState, snapshot, refreshing, onRefresh, onNavigate }: { view: View; queueState?: FactoryState; snapshot: FactoryControlSnapshot; refreshing: boolean; onRefresh: () => void; onNavigate?: (target: DashboardTarget) => void }) {
  return <>
    <div className="factory-snapshot-bar"><div><StatusDot state={snapshot.factory.health} /><strong>Registry revision {snapshot.registryRevision}</strong><span>Generated {formatRelativeTime(snapshot.generatedAt)}</span><span>Signature verified {formatRelativeTime(snapshot.verification.verifiedAt)}</span></div><button type="button" className="factory-button secondary" onClick={onRefresh} disabled={refreshing}>{refreshing ? 'Refreshing…' : 'Refresh'}</button></div>
    {view === 'overview' && <Overview snapshot={snapshot} onNavigate={onNavigate} />}
    {view === 'queue' && <Queue snapshot={snapshot} initialState={queueState} />}
    {view === 'workers' && <Workers snapshot={snapshot} />}
    {view === 'reviews' && <Reviews snapshot={snapshot} />}
    {view === 'capacity' && <Capacity snapshot={snapshot} />}
    {view === 'history' && <History snapshot={snapshot} />}
    {view === 'failures' && <Failures snapshot={snapshot} />}
  </>
}

function Overview({ snapshot, onNavigate }: { snapshot: FactoryControlSnapshot; onNavigate?: (target: DashboardTarget) => void }) {
  const packages = packageIndex(snapshot.features)
  const attentionCount = visibleAttention(snapshot).length
  const constrainedCount = snapshot.workers.filter(worker => effectiveWorkerHealth(worker, snapshot.generatedAt).state !== 'healthy').length
  return <div className="factory-view">
    <section className="factory-metrics" aria-label="Factory summary">
      <Metric label="Active parent packages" value={`${snapshot.factory.activeParentCount} / ${snapshot.factory.activeParentLimit}`} tone={snapshot.factory.activeParentCount >= snapshot.factory.activeParentLimit ? 'warning' : 'calm'} />
      <Metric label="Orchestra reserve" value={snapshot.factory.orchestraReservePercent === null ? 'Unknown' : `${snapshot.factory.orchestraReservePercent}%`} tone={(snapshot.factory.orchestraReservePercent ?? 0) < 20 ? 'danger' : 'calm'} />
      <Metric label="Ready" value={snapshot.factory.readyCount} onSelect={onNavigate ? () => onNavigate({ view: 'queue', queueState: 'READY' }) : undefined} />
      <Metric label="Verify / review" value={snapshot.factory.verifyReviewCount} tone={snapshot.factory.verifyReviewCount ? 'warning' : 'calm'} onSelect={onNavigate ? () => onNavigate({ view: 'queue', queueState: 'VERIFY_REVIEW' }) : undefined} />
      <Metric label="Blocked" value={snapshot.factory.blockedCount} tone={snapshot.factory.blockedCount ? 'danger' : 'calm'} onSelect={onNavigate ? () => onNavigate({ view: 'queue', queueState: 'BLOCKED' }) : undefined} />
      <Metric label="Needs attention" value={attentionCount} tone={attentionCount ? 'danger' : 'calm'} onSelect={onNavigate ? () => onNavigate({ view: 'failures' }) : undefined} />
      <Metric label="Constrained workers" value={constrainedCount} tone={constrainedCount ? 'warning' : 'calm'} onSelect={onNavigate ? () => onNavigate({ view: 'workers' }) : undefined} />
    </section>
    <section className="factory-section"><SectionHeading title="Everyone at a glance" note="Assignment, heartbeat, lane, runtime and capacity" /><div className="factory-worker-grid">{snapshot.workers.map(worker => <WorkerSummary worker={worker} item={worker.currentPackageId ? packages.get(worker.currentPackageId) : undefined} scopes={snapshot.capacity.filter(scope => scope.workerId === worker.id)} generatedAt={snapshot.generatedAt} key={worker.id} />)}</div></section>
    <section className="factory-section"><SectionHeading title="Preservation reconciliation" note={`Observed ${formatRelativeTime(snapshot.reconciliation.observedAt)}`} /><div className={`factory-reconciliation ${snapshot.reconciliation.status}`}><StatusChip label={snapshot.reconciliation.status === 'clean' ? 'Clean' : snapshot.reconciliation.status} tone={snapshot.reconciliation.status === 'clean' ? 'healthy' : 'danger'} /><span>{value(snapshot.reconciliation.worktreeCount)} worktrees</span><span>{value(snapshot.reconciliation.dirtyWorktreeCount)} dirty</span><span>{value(snapshot.reconciliation.unmergedBranchCount)} unmerged branches</span><span>{value(snapshot.reconciliation.unexplainedRecordCount)} unexplained records</span><span>{value(snapshot.reconciliation.activeStaleLeaseCount)} stale leases</span></div></section>
  </div>
}

function WorkerSummary({ worker, item, scopes, generatedAt }: { worker: FactoryWorker; item?: FactoryPackage; scopes: FactoryCapacityScope[]; generatedAt: string }) {
  const health = effectiveWorkerHealth(worker, generatedAt)
  const constraints = workerConstraintDetails(worker, generatedAt, scopes)
  return <details className="factory-card worker-summary factory-inspection" open={health.state !== 'healthy'}><summary className="factory-card-heading"><div className="factory-avatar" aria-hidden="true">{worker.displayName.slice(0, 2).toUpperCase()}</div><div><h3>{worker.displayName}</h3><p>{worker.role === 'ORCHESTRA' ? 'Coordinator' : worker.provider && worker.model ? `${worker.provider} · ${worker.model}` : worker.role}</p></div><StatusChip label={health.state} tone={health.state} /></summary>
    <p className="factory-assignment"><strong>{item?.title ?? 'No current assignment'}</strong><span>{item ? `${item.id} · ${item.lane ?? 'Lane unassigned'}` : 'Available work is shown in Queue'}</span></p>
    <dl className="factory-definition"><div><dt>Task elapsed</dt><dd>{item ? formatDuration(item.elapsedRuntimeSeconds) : '—'}</dd></div><div><dt>Heartbeat</dt><dd>{formatRelativeTime(worker.heartbeatAt, new Date(generatedAt))}</dd></div><div><dt>Attempt</dt><dd>{worker.currentAttempt ?? '—'}</dd></div><div><dt>Capacity</dt><dd>{worker.capacityState.replace('_', ' ')}</dd></div></dl>
    <p className="factory-scope-line">{health.reason}</p>{scopes.length > 0 && <p className="factory-scope-line">{scopes.map(capacitySummary).join(' · ')}</p>}
    {constraints.length > 0 && <div className="factory-constraint-list">{constraints.map(detail => <div key={detail.code}><strong>{detail.code}</strong><span>{detail.reason}</span><span>Next action: {detail.nextAction}</span></div>)}</div>}
  </details>
}

function Queue({ snapshot, initialState }: { snapshot: FactoryControlSnapshot; initialState?: FactoryState }) {
  const [filters, setFilters] = useState<QueueFilters>({ ...emptyQueueFilters, state: initialState ?? '' })
  const packages = snapshot.features.flatMap(feature => feature.packages)
  const packagesById = packageIndex(snapshot.features)
  const filtered = useMemo(() => filterFactoryFeatures(snapshot.features, filters), [snapshot.features, filters])
  const lanes = unique(packages.map(item => item.lane).filter((lane): lane is string => !!lane))
  const priorities = unique(packages.map(item => String(item.priority)))
  const set = (key: keyof QueueFilters, next: string) => setFilters(current => ({ ...current, [key]: next }))
  useEffect(() => setFilters(current => ({ ...current, state: initialState ?? '' })), [initialState])
  const stateCounts = (['ON_DECK', 'READY', 'ACTIVE', 'VERIFY_REVIEW', 'BLOCKED', 'DONE'] as FactoryState[]).map(state => ({ state, count: packages.filter(item => item.state === state).length }))
  return <div className="factory-view"><section className="factory-section"><SectionHeading title="Feature queue" note={`${filtered.reduce((total, feature) => total + feature.packages.length, 0)} of ${packages.length} Registry packages shown across ${filtered.length} features`} />
    <div className="factory-queue-states" aria-label="Registry queue state totals">{stateCounts.map(({ state, count }) => <button type="button" className={filters.state === state ? 'active' : ''} onClick={() => set('state', filters.state === state ? '' : state)} key={state}><span>{state === 'ON_DECK' ? 'Proposed / on deck' : formatFactoryState(state)}</span><strong>{count}</strong></button>)}</div>
    <div className="factory-filters" aria-label="Queue filters">
      <Filter label="State" value={filters.state} onChange={value => set('state', value)} options={['ON_DECK', 'READY', 'ACTIVE', 'VERIFY_REVIEW', 'BLOCKED', 'DONE'].map(item => [item, formatFactoryState(item as FactoryState)])} />
      <Filter label="Lane" value={filters.lane} onChange={value => set('lane', value)} options={lanes.map(item => [item, item])} />
      <Filter label="Worker" value={filters.worker} onChange={value => set('worker', value)} options={snapshot.workers.map(item => [item.id, item.displayName])} />
      <Filter label="Priority" value={filters.priority} onChange={value => set('priority', value)} options={priorities.map(item => [item, item])} />
      <Filter label="Feature" value={filters.feature} onChange={value => set('feature', value)} options={snapshot.features.map(item => [item.id, `${item.id} · ${item.title}`])} />
      <label>Blocked reason<input value={filters.blockedReason} onChange={event => set('blockedReason', event.target.value)} placeholder="Search reason" /></label>
      <button type="button" className="factory-button secondary" onClick={() => setFilters(emptyQueueFilters)}>Clear filters</button>
    </div>
    <div className="factory-feature-list">{filtered.length ? filtered.map(feature => <details className="factory-feature" open={feature.state === 'ACTIVE' || feature.state === 'VERIFY_REVIEW'} key={feature.id}><summary><div><span className="factory-id">{feature.id}</span><strong>{feature.title}</strong><small>{feature.description}</small></div><div><StatusChip label={formatFactoryState(feature.state)} tone={stateTone(feature.state)} /><span>{feature.packages.length} package{feature.packages.length === 1 ? '' : 's'}</span></div></summary><div className="factory-package-list">{feature.packages.map(item => <PackageCard item={item} feature={`${feature.id} · ${feature.title}`} packages={packagesById} workers={snapshot.workers} key={item.id} />)}</div></details>) : <Empty title="No queue items match these filters" text="Clear one or more filters to widen the view." />}</div>
  </section></div>
}

function PackageCard({ item, feature, packages, workers }: { item: FactoryPackage; feature: string; packages: Map<string, FactoryPackage>; workers: FactoryWorker[] }) {
  const owner = workers.find(worker => worker.id === item.ownerWorkerId)?.displayName
  return <article className="factory-package"><div className="factory-package-head"><div><span className="factory-id">{item.id}</span><h3>{item.title}</h3></div><StatusChip label={formatFactoryState(item.state)} tone={stateTone(item.state)} /></div>
    <div className="factory-package-facts"><Fact label="Feature / parent" value={feature} /><Fact label="Priority" value={item.priority} /><Fact label="Lane" value={item.lane ?? 'Unassigned'} /><Fact label="Assigned worker" value={owner ?? 'Unassigned'} /><Fact label="Lease" value={item.currentLease?.id ?? 'None'} /><Fact label="Attempt" value={item.attemptNumber || 'Not started'} /></div>
    <p className="factory-readiness"><strong>{item.state === 'ON_DECK' ? 'Why not READY' : 'Current state detail'}</strong><span>{readinessReason(item, packages)}</span></p>
    <div className="factory-package-columns"><InfoList title="Dependencies" items={item.dependencies.map(id => `${id} · ${packages.get(id)?.state ?? 'missing'}`)} empty="None" /><InfoList title="Required capabilities" items={item.requiredCapabilities} empty="None declared" /><InfoList title="Acceptance criteria" items={item.acceptanceCriteria} empty="None recorded" /></div>
    {(item.blockReason || item.failureCode || item.state === 'BLOCKED') && <details className="factory-block factory-inspection" open><summary><strong>{item.failureCode ?? 'BLOCKED'}</strong> · {failureClassification(item.failureCode ?? 'BLOCKED')}</summary><span>{item.blockReason ?? 'No human-readable block reason is recorded.'}</span><span>Unblock action: {recommendedFailureAction(item.failureCode ?? 'BLOCKED')}</span></details>}
    <div className="factory-provenance"><Fact label="Branch" value={item.branch ?? 'Not created'} /><Fact label="Pull request" value={item.pullRequestUrl ? <SafeLink href={item.pullRequestUrl}>Open PR</SafeLink> : 'Not created'} /></div>
    <EvidenceList evidence={item.evidence} />
  </article>
}

function Workers({ snapshot }: { snapshot: FactoryControlSnapshot }) {
  const packages = packageIndex(snapshot.features)
  return <div className="factory-view"><section className="factory-section"><SectionHeading title="Worker diagnostics" note="Open any worker to inspect exact service, authentication, heartbeat, capacity and eligibility evidence" /><div className="factory-worker-list">{snapshot.workers.map(worker => {
    const current = worker.currentPackageId ? packages.get(worker.currentPackageId) : undefined
    const invocations = snapshot.usageInvocations.filter(item => item.workerId === worker.id)
    const scopes = snapshot.capacity.filter(scope => scope.workerId === worker.id)
    const health = effectiveWorkerHealth(worker, snapshot.generatedAt)
    const constraints = workerConstraintDetails(worker, snapshot.generatedAt, scopes)
    return <details className="factory-card worker-detail factory-inspection" open={health.state !== 'healthy'} key={worker.id}><summary className="factory-card-heading"><div><span className="factory-id">{worker.id}</span><h2>{worker.displayName}</h2><p>{worker.provider ?? 'Provider unknown'} · {worker.model ?? 'Model unknown'}</p></div><StatusChip label={health.state} tone={health.state} /></summary><p className="factory-scope-line">{health.reason}</p><div className="factory-worker-state"><Fact label="Service" value={worker.serviceState} /><Fact label="Authentication" value={worker.authenticationState} /><Fact label="Last successful heartbeat" value={formatRelativeTime(worker.heartbeatAt, new Date(snapshot.generatedAt))} /><Fact label="Current package" value={current ? `${current.id} · ${current.title}` : 'None'} /><Fact label="Active lease" value={worker.activeLease?.id ?? 'None'} /><Fact label="Attempt" value={worker.currentAttempt ?? '—'} /></div><div className="factory-worker-state"><Fact label="Productive runtime" value={formatDuration(worker.productiveRuntimeSeconds)} /><Fact label="Idle time" value={formatDuration(worker.idleSeconds)} /><Fact label="Blocked time" value={formatDuration(worker.blockedSeconds)} /><Fact label="Capacity state" value={worker.capacityState.replace('_', ' ')} /><Fact label="Last capacity observation" value={scopes.map(scope => scope.observedAt).filter((value): value is string => value !== null).sort().at(-1) ? formatRelativeTime(scopes.map(scope => scope.observedAt).filter((value): value is string => value !== null).sort().at(-1)!, new Date(snapshot.generatedAt)) : 'Not recorded'} /><Fact label="Eligible lanes" value={worker.approvedLanes.join(', ') || 'None'} /></div>{constraints.length > 0 && <div className="factory-constraint-list">{constraints.map(detail => <div key={detail.code}><strong>{detail.code}</strong><span>{detail.reason}</span><span>Next action: {detail.nextAction}</span></div>)}</div>}<div className="factory-package-columns"><InfoList title="Approved capabilities" items={worker.approvedCapabilities} empty="None" /><InfoList title="Approved lanes" items={worker.approvedLanes} empty="None" /><InfoList title="Recent tasks" items={worker.recentTaskIds} empty="None" /><InfoList title="Recent failures" items={worker.recentFailureIds} empty="None" /></div>{invocations.length > 0 && <UsageLedger invocations={invocations} title={`${worker.displayName} invocation history`} />}</details>
  })}</div></section></div>
}

function Reviews({ snapshot }: { snapshot: FactoryControlSnapshot }) {
  const packages = packageIndex(snapshot.features)
  const reviews = visibleReviews(snapshot)
  const workerName = (id: string | null) => snapshot.workers.find(worker => worker.id === id)?.displayName ?? (id ?? 'Unassigned')
  return <div className="factory-view"><section className="factory-section"><SectionHeading title="Independent review queue" note={`${reviews.filter(review => review.state !== 'approved').length} requiring review or reconciliation`} />
    <div className="factory-review-list">{reviews.length ? reviews.map(review => <details className={`factory-card factory-review factory-inspection ${review.state}`} open={review.state !== 'approved'} key={review.id}><summary className="factory-card-heading"><div><span className="factory-id">{review.packageId}</span><h2>{packages.get(review.packageId)?.title ?? 'Unknown package'}</h2></div><StatusChip label={review.state === 'unrecorded' ? 'Outcome unrecorded' : review.state.replace('_', ' ')} tone={review.state === 'approved' ? 'healthy' : review.state === 'changes_requested' ? 'danger' : review.state === 'unrecorded' ? 'neutral' : 'warning'} /></summary>{review.source === 'package_state' && <p className="factory-scope-line">Derived from this package’s Registry state; the review outcome, assignment, and timing are not recorded.</p>}<div className="factory-worker-state"><Fact label="Implementer" value={workerName(review.implementerWorkerId)} /><Fact label="Assigned reviewer" value={workerName(review.assignedReviewerId)} /><Fact label="Eligible reviewers" value={review.eligibleReviewerIds.map(workerName).join(', ') || 'Not recorded' } /><Fact label="Review age" value={review.requestedAt ? formatRelativeTime(review.requestedAt) : 'Not recorded'} /></div><div className="factory-package-columns"><InfoList title="Findings" items={review.findings} empty="No findings recorded" /><InfoList title="Changes requested" items={review.changesRequested} empty="None recorded" /></div><EvidenceList evidence={review.approvalEvidence} title="Review evidence" /></details>) : <Empty title="Review queue is clear" text="No packages are waiting for independent review." />}</div>
  </section></div>
}

function Capacity({ snapshot }: { snapshot: FactoryControlSnapshot }) {
  const workerName = (id: string) => snapshot.workers.find(worker => worker.id === id)?.displayName ?? id
  const claudeWorkerIds = new Set(snapshot.workers.filter(worker => worker.provider?.toLowerCase() === 'anthropic').map(worker => worker.id))
  const claudeInvocations = snapshot.usageInvocations.filter(item => claudeWorkerIds.has(item.workerId))
  return <div className="factory-view"><section className="factory-section"><SectionHeading title="Capacity scopes" note="Provider reports, Factory measurements and inference stay visibly separate" /><div className="factory-capacity-grid">{snapshot.capacity.map(scope => <article className="factory-card capacity-card" key={scope.id}><div className="factory-card-heading"><div><p className="factory-eyebrow">{workerName(scope.workerId)}</p><h2>{scope.label}</h2></div><StatusChip label={scope.state.replace('_', ' ')} tone={capacityTone(scope.state)} /></div><p className={`capacity-source ${scope.source}`}>{sourceLabel(scope.source)}</p><div className="capacity-primary">{scope.usedPercent === null ? <><strong>{formatNumber(scope.rolling24Hours.outputTokens)}</strong><span>output tokens / 24h</span></> : <><strong>{scope.usedPercent}%</strong><span>{scope.source === 'provider_reported' ? 'provider-reported usage' : 'inferred usage'}</span></>}</div>{scope.usedPercent !== null && <div className="capacity-meter" role="meter" aria-label={`${scope.label} usage`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={scope.usedPercent}><span style={{ width: `${Math.min(100, scope.usedPercent)}%` }} /></div>}<dl className="factory-definition"><div><dt>Observed</dt><dd>{formatRelativeTime(scope.observedAt)}</dd></div><div><dt>Reset</dt><dd>{scope.resetAt ? new Date(scope.resetAt).toLocaleString() : 'Not provided'}</dd></div><div><dt>Output / hour</dt><dd>{formatNumber(scope.outputTokensPerHour)}</dd></div><div><dt>Average / task</dt><dd>{formatNumber(scope.averageTokensPerTask)}</dd></div><div><dt>7-day tasks</dt><dd>{scope.rolling7Days.completedTasks}</dd></div><div><dt>Review throughput</dt><dd>{scope.reviewThroughput}</dd></div><div><dt>Limit hits</dt><dd>{scope.limitHitCount}</dd></div><div><dt>Inferred ceiling</dt><dd>{formatNumber(scope.inferredCeilingTokens)}</dd></div></dl>{scope.source === 'factory_measured' && <p className="factory-scope-line">No provider percentage is available. Eligibility follows live service, authentication and actual limit signals.</p>}</article>)}</div></section><section className="factory-section"><SectionHeading title="Claude invocation ledger" note="Factory-measured history; this is not a provider quota percentage" /><UsageLedger invocations={claudeInvocations} title="Claude rolling invocation history" /></section></div>
}

function History({ snapshot }: { snapshot: FactoryControlSnapshot }) {
  const historicalFailures = snapshot.failures.filter(failure => !failure.requiresHuman)
  return <div className="factory-view"><section className="factory-section"><SectionHeading title="History and provenance" note="Drill from a Feature to its evidence, then inspect the Registry event timeline" /><ProvenanceTree snapshot={snapshot} /></section><section className="factory-section"><SectionHeading title="Registry event timeline" note={`${snapshot.events.length} Registry events in this projection`} /><ol className="factory-timeline">{snapshot.events.map(event => <li key={event.id}><span className="timeline-mark" aria-hidden="true" /><div><div className="factory-card-heading"><div><StatusChip label={event.kind.replace('_', ' ')} tone={event.kind === 'FAILURE' ? 'danger' : event.kind === 'DONE' ? 'healthy' : 'neutral'} /><time dateTime={event.occurredAt}>{new Date(event.occurredAt).toLocaleString()}</time></div><span className="factory-id">{event.packageId ?? event.featureId ?? 'Factory'}</span></div><p>{event.summary}</p><div className="factory-event-path"><span>Attempt {event.attemptNumber ?? '—'}</span><span>Worker {event.workerId ?? '—'}</span><span>Branch {event.branch ?? '—'}</span><span>Commit {event.commitSha ?? '—'}</span>{event.pullRequestUrl && <SafeLink href={event.pullRequestUrl}>Pull request</SafeLink>}<span>{event.evidenceIds.length} evidence item{event.evidenceIds.length === 1 ? '' : 's'}</span></div></div></li>)}</ol></section>{historicalFailures.length > 0 && <section className="factory-section"><SectionHeading title="Historical failures" note="Resolved observations retained for provenance; they do not require current attention" /><div className="factory-failure-list">{historicalFailures.map(failure => <article className="factory-card factory-failure" key={failure.id}><div className="factory-card-heading"><div><span className="factory-id">{failure.code}</span><h2>{failure.title}</h2></div><StatusChip label="Historical" tone="neutral" /></div><p>{failure.detail}</p><div className="factory-event-path"><span>{failure.workerId ?? 'Factory'}</span><span>{failure.packageId ?? 'No package'}</span><span>{formatRelativeTime(failure.occurredAt)}</span></div></article>)}</div></section>}</div>
}

function ProvenanceTree({ snapshot }: { snapshot: FactoryControlSnapshot }) {
  return <div className="factory-provenance-tree">{snapshot.features.map(feature => <details key={feature.id}><summary><span className="factory-id">Feature {feature.id}</span><strong>{feature.title}</strong></summary><div>{feature.packages.map(item => <details key={item.id}><summary><span className="factory-id">Package {item.id}</span><strong>{item.title}</strong></summary><div>{item.attempts.length ? item.attempts.map(attempt => <details key={attempt.id}><summary><span className="factory-id">Attempt {attempt.number}</span><strong>{attempt.id}</strong><StatusChip label={attempt.outcome} tone={attempt.outcome === 'succeeded' ? 'healthy' : attempt.outcome === 'failed' || attempt.outcome === 'blocked' ? 'danger' : 'warning'} /></summary><ol className="factory-provenance-steps" aria-label={`Provenance for ${attempt.id}`}><li><strong>Branch</strong><span>{attempt.branch ?? 'Not recorded'}</span></li><li><strong>Commit</strong><span>{attempt.commitSha ?? 'Not recorded'}</span></li><li><strong>Pull request</strong>{attempt.pullRequestUrl ? <SafeLink href={attempt.pullRequestUrl}>{attempt.pullRequestUrl}</SafeLink> : <span>Not recorded</span>}</li><li><strong>Evidence</strong>{attempt.evidence.length ? <ul>{attempt.evidence.map(evidence => <li key={evidence.id}>{evidence.url ? <SafeLink href={evidence.url}>{evidence.label}</SafeLink> : <span>{evidence.label}</span>}</li>)}</ul> : <span>None recorded</span>}</li></ol></details>) : <p className="factory-empty-copy">No attempts recorded.</p>}</div></details>)}</div></details>)}</div>
}

function UsageLedger({ invocations, title }: { invocations: FactoryUsageInvocation[]; title: string }) {
  const ordered = [...invocations].sort((left, right) => right.observedAt.localeCompare(left.observedAt))
  if (!ordered.length) return <Empty title="No invocation telemetry" text="No Registry usage observations are present for this scope." />
  return <div className="factory-usage-ledger"><div className="factory-table-scroll"><table><caption>{title}</caption><thead><tr><th scope="col">Observed</th><th scope="col">Task / attempt</th><th scope="col">Session / account</th><th scope="col">Input</th><th scope="col">Output</th><th scope="col">Cache read</th><th scope="col">Cache write</th><th scope="col">Duration</th><th scope="col">Outcome</th><th scope="col">Source history</th></tr></thead><tbody>{ordered.map(item => <tr key={item.id}><td><time dateTime={item.observedAt}>{new Date(item.observedAt).toLocaleString()}</time></td><td>{usageProvenanceLabel(item)}</td><td><span>{item.sessionId}</span><small>{item.accountLabel}</small><small>{item.modelDiagnostic ?? 'Model unknown'}</small></td><td>{formatNumber(item.inputTokens)}</td><td>{formatNumber(item.outputTokens)}</td><td>{formatNumber(item.cacheReadTokens)}</td><td>{formatNumber(item.cacheWriteTokens)}</td><td>{item.durationSeconds === null ? 'Unknown' : formatDuration(item.durationSeconds)}</td><td><StatusChip label={item.limitSignal ? `${item.outcome} · ${item.limitSignal}` : item.outcome} tone={item.outcome === 'SUCCEEDED' ? 'healthy' : 'danger'} /></td><td>{item.sources.map(source => `${source.sourceType.replaceAll('_', ' ')} · ${formatRelativeTime(source.observedAt)}`).join(' → ')}</td></tr>)}</tbody></table></div></div>
}

function usageProvenanceLabel(item: FactoryUsageInvocation): string {
  if (item.observationClass === 'DIAGNOSTIC') return 'Diagnostic probe'
  if (item.observationClass === 'LEGACY_UNCLASSIFIED') return `Legacy unclassified · ${item.packageId ?? 'package unknown'} / ${item.attemptId ?? 'attempt unknown'}`
  return `${item.packageId} / ${item.attemptId}`
}

function Failures({ snapshot }: { snapshot: FactoryControlSnapshot }) {
  const failures = visibleAttention(snapshot)
  const packages = packageIndex(snapshot.features)
  const workerName = (id: string | null) => snapshot.workers.find(worker => worker.id === id)?.displayName ?? (id ?? 'Factory')
  return <div className="factory-view"><section className="factory-section"><SectionHeading title="Failures requiring attention" note="Open any state to inspect its cause, owner action, unblock step and same-revision evidence" />{failures.length ? <div className="factory-failure-list">{failures.map(failure => {
    const item = failure.packageId ? packages.get(failure.packageId) : undefined
    const worker = failure.workerId ? snapshot.workers.find(candidate => candidate.id === failure.workerId) : undefined
    const event = [...snapshot.events].reverse().find(candidate => (failure.packageId && candidate.packageId === failure.packageId) || (failure.workerId && candidate.workerId === failure.workerId))
    const attempt = item?.attempts.find(candidate => candidate.number === item.attemptNumber) ?? item?.attempts.at(-1)
    const evidence = [...(item?.evidence ?? []), ...(attempt?.evidence ?? [])].filter((candidate, index, all) => all.findIndex(other => other.id === candidate.id) === index)
    return <details className={`factory-card factory-failure factory-inspection ${failure.severity}`} open key={failure.id}><summary className="factory-card-heading"><div><span className="factory-id">{failure.code}</span><h2>{failure.title}</h2></div><StatusChip label={failure.requiresHuman ? 'Owner action needed' : failure.source === 'package_state' ? 'Remediation needed' : failure.severity} tone={failure.severity === 'critical' ? 'danger' : 'warning'} /></summary>{failure.source === 'package_state' && <p className="factory-scope-line">Derived from this package’s Registry state because no matching structured failure row is present.</p>}<p>{failure.detail}</p><div className="factory-worker-state"><Fact label="Classification" value={failureClassification(failure.code)} /><Fact label="Affected worker" value={workerName(failure.workerId)} /><Fact label="Affected package" value={failure.packageId ?? 'Factory-wide'} /><Fact label="Occurred" value={failure.occurredAt ? formatRelativeTime(failure.occurredAt, new Date(snapshot.generatedAt)) : 'Time not recorded'} /><Fact label="Last heartbeat" value={worker?.heartbeatAt ? formatRelativeTime(worker.heartbeatAt, new Date(snapshot.generatedAt)) : 'Not recorded'} /><Fact label="Owner action required" value={failure.requiresHuman ? 'Yes' : 'No'} /></div><div className="factory-package-columns"><InfoList title="Dependencies / prerequisites" items={item?.dependencies.map(id => `${id} · ${packages.get(id)?.state ?? 'missing'}`) ?? []} empty="None recorded" /><InfoList title="Triggering event" items={event ? [`${event.id} · ${event.kind} · ${event.summary}`] : []} empty="No matching event recorded" /></div><p className="factory-next-action"><strong>Recommended next action</strong><span>{recommendedFailureAction(failure.code)}</span></p><div className="factory-provenance"><Fact label="Attempt" value={attempt?.id ?? 'Not recorded'} /><Fact label="Pull request" value={attempt?.pullRequestUrl || item?.pullRequestUrl ? <SafeLink href={(attempt?.pullRequestUrl ?? item?.pullRequestUrl)!}>Open PR</SafeLink> : 'Not recorded'} /></div><EvidenceList evidence={evidence} title="Relevant evidence" /></details>
  })}</div> : <Empty title="No failures need attention" text="The current Registry projection contains no active intervention items." />}</section></div>
}

function LoadingPanel() { return <div className="factory-state-panel" role="status"><span className="factory-spinner" aria-hidden="true" /><h2>Loading verified Registry state</h2><p>The Control Center will remain closed if authentication or projection verification fails.</p></div> }
function ErrorPanel({ message, onRetry }: { message: string; onRetry: () => void }) { return <div className="factory-state-panel error" role="alert"><h2>Factory visibility is unavailable</h2><p>{message}</p><button type="button" className="factory-button" onClick={onRetry}>Try again</button></div> }
function Metric({ label, value: metricValue, tone = 'neutral', onSelect }: { label: string; value: ReactNode; tone?: string; onSelect?: () => void }) {
  const content = <><span>{label}</span><strong>{metricValue}</strong>{onSelect && <small>View matching records</small>}</>
  return onSelect ? <button type="button" className={`factory-metric ${tone}`} onClick={onSelect}>{content}</button> : <article className={`factory-metric ${tone}`}>{content}</article>
}
function SectionHeading({ title, note }: { title: string; note: string }) { return <div className="factory-section-heading"><div><h2>{title}</h2><p>{note}</p></div></div> }
function Fact({ label, value: factValue }: { label: string; value: ReactNode }) { return <div className="factory-fact"><span>{label}</span><strong>{factValue}</strong></div> }
function InfoList({ title, items, empty }: { title: string; items: string[]; empty: string }) { return <div className="factory-info-list"><h4>{title}</h4>{items.length ? <ul>{items.map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}</ul> : <p>{empty}</p>}</div> }
function EvidenceList({ evidence, title = 'Evidence' }: { evidence: FactoryEvidence[]; title?: string }) { return <div className="factory-evidence"><h4>{title}</h4>{evidence.length ? <ul>{evidence.map(item => <li key={item.id}>{item.url ? <SafeLink href={item.url}>{item.label}</SafeLink> : <span>{item.label}</span>}<small>{item.kind} · {formatRelativeTime(item.recordedAt)}</small></li>)}</ul> : <p>No evidence recorded.</p>}</div> }
function SafeLink({ href, children }: { href: string; children: ReactNode }) {
  const safeHref = safeExternalUrl(href)
  return safeHref ? <a href={safeHref} target="_blank" rel="noreferrer">{children}</a> : <span>{children}</span>
}
function Empty({ title, text }: { title: string; text: string }) { return <div className="factory-empty"><h3>{title}</h3><p>{text}</p></div> }
function Filter({ label, value: filterValue, onChange, options }: { label: string; value: string; onChange: (value: string) => void; options: string[][] }) { return <label>{label}<select value={filterValue} onChange={event => onChange(event.target.value)}><option value="">All</option>{options.map(([optionValue, label]) => <option value={optionValue} key={optionValue}>{label}</option>)}</select></label> }
function StatusDot({ state }: { state: string }) { return <span className={`factory-status-dot ${state}`} aria-label={state} /> }
function StatusChip({ label, tone }: { label: string; tone: string }) { return <span className={`factory-chip ${tone}`}>{label}</span> }
function stateTone(state: FactoryState) { return state === 'DONE' ? 'healthy' : state === 'BLOCKED' ? 'danger' : state === 'ACTIVE' || state === 'VERIFY_REVIEW' ? 'warning' : 'neutral' }
function capacityTone(state: FactoryCapacityScope['state']) { return state === 'normal' ? 'healthy' : state === 'hard_stop' || state === 'limited' ? 'danger' : state === 'unknown' ? 'neutral' : 'warning' }
function sourceLabel(source: CapacitySource) { return ({ provider_reported: 'Provider reported', factory_measured: 'Factory measured', inferred: 'Factory inference', unknown: 'Unknown source' })[source] }
function unique(values: string[]) { return [...new Set(values)].sort() }
function value(item: number | null) { return item === null ? 'Unknown' : item }
function formatNumber(item: number | null) { return item === null ? 'Unknown' : new Intl.NumberFormat().format(Math.round(item)) }
