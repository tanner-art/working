import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { auth, supabase, type AuthState } from './auth'
import { capacitySummary, emptyQueueFilters, filterFactoryFeatures, packageIndex, type QueueFilters } from './buildDashboard'
import { formatDuration, formatFactoryState, formatRelativeTime, parseFactoryControlSnapshot, type CapacitySource, type FactoryCapacityScope, type FactoryControlSnapshot, type FactoryEvidence, type FactoryPackage, type FactoryState, type FactoryWorker } from './factoryControl'

type View = 'overview' | 'queue' | 'workers' | 'reviews' | 'capacity' | 'history' | 'failures'
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
  const [view, setView] = useState<View>('overview')
  useEffect(() => { const previous = document.title; document.title = 'Factory Control Center · Threadline'; return () => { document.title = previous } }, [])
  if (account.state.status !== 'signed-in') return <FactorySignIn state={account.state} onRetry={account.retry} />
  return <main className="factory-shell">
    <aside className="factory-sidebar">
      <div className="factory-brand"><span aria-hidden="true">TF</span><div><strong>Threadline</strong><small>Factory Control Center</small></div></div>
      <nav aria-label="Control Center views">{views.map(item => <button type="button" className={view === item.id ? 'active' : ''} aria-current={view === item.id ? 'page' : undefined} onClick={() => setView(item.id)} key={item.id}>{item.label}</button>)}</nav>
      <div className="factory-sidebar-foot"><span className="readonly-pill">Read-only</span><a href="/">Return to Threadline</a></div>
    </aside>
    <section className="factory-workspace">
      <header className="factory-topbar"><div><p className="factory-eyebrow">Live Factory visibility</p><h1>{views.find(item => item.id === view)?.label}</h1></div><div className="factory-account"><span>{account.state.session.user.email ?? 'Authenticated owner'}</span><button type="button" className="factory-button secondary" onClick={() => void auth.act('logout')}>Sign out</button></div></header>
      {projection.load.status === 'loading' && <LoadingPanel />}
      {projection.load.status === 'idle' && <LoadingPanel />}
      {projection.load.status === 'error' && <ErrorPanel message={projection.load.message} onRetry={() => void projection.refresh()} />}
      {projection.load.status === 'ready' && <DashboardView view={view} snapshot={projection.load.snapshot} refreshing={projection.load.refreshing} onRefresh={() => void projection.refresh()} />}
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

function DashboardView({ view, snapshot, refreshing, onRefresh }: { view: View; snapshot: FactoryControlSnapshot; refreshing: boolean; onRefresh: () => void }) {
  return <>
    <div className="factory-snapshot-bar"><div><StatusDot state={snapshot.factory.health} /><strong>Registry revision {snapshot.registryRevision}</strong><span>Generated {formatRelativeTime(snapshot.generatedAt)}</span><span>Signature verified {formatRelativeTime(snapshot.verification.verifiedAt)}</span></div><button type="button" className="factory-button secondary" onClick={onRefresh} disabled={refreshing}>{refreshing ? 'Refreshing…' : 'Refresh'}</button></div>
    {view === 'overview' && <Overview snapshot={snapshot} />}
    {view === 'queue' && <Queue snapshot={snapshot} />}
    {view === 'workers' && <Workers snapshot={snapshot} />}
    {view === 'reviews' && <Reviews snapshot={snapshot} />}
    {view === 'capacity' && <Capacity snapshot={snapshot} />}
    {view === 'history' && <History snapshot={snapshot} />}
    {view === 'failures' && <Failures snapshot={snapshot} />}
  </>
}

function Overview({ snapshot }: { snapshot: FactoryControlSnapshot }) {
  const packages = packageIndex(snapshot.features)
  return <div className="factory-view">
    <section className="factory-metrics" aria-label="Factory summary">
      <Metric label="Active parent packages" value={`${snapshot.factory.activeParentCount} / ${snapshot.factory.activeParentLimit}`} tone={snapshot.factory.activeParentCount >= snapshot.factory.activeParentLimit ? 'warning' : 'calm'} />
      <Metric label="Orchestra reserve" value={snapshot.factory.orchestraReservePercent === null ? 'Unknown' : `${snapshot.factory.orchestraReservePercent}%`} tone={(snapshot.factory.orchestraReservePercent ?? 0) < 20 ? 'danger' : 'calm'} />
      <Metric label="Ready" value={snapshot.factory.readyCount} />
      <Metric label="Verify / review" value={snapshot.factory.verifyReviewCount} tone={snapshot.factory.verifyReviewCount ? 'warning' : 'calm'} />
      <Metric label="Blocked" value={snapshot.factory.blockedCount} tone={snapshot.factory.blockedCount ? 'danger' : 'calm'} />
      <Metric label="Needs attention" value={snapshot.factory.attentionCount} tone={snapshot.factory.attentionCount ? 'danger' : 'calm'} />
    </section>
    <section className="factory-section"><SectionHeading title="Everyone at a glance" note="Assignment, heartbeat, lane, runtime and capacity" /><div className="factory-worker-grid">{snapshot.workers.map(worker => <WorkerSummary worker={worker} item={worker.currentPackageId ? packages.get(worker.currentPackageId) : undefined} scopes={snapshot.capacity.filter(scope => scope.workerId === worker.id)} key={worker.id} />)}</div></section>
    <section className="factory-section"><SectionHeading title="Preservation reconciliation" note={`Observed ${formatRelativeTime(snapshot.reconciliation.observedAt)}`} /><div className={`factory-reconciliation ${snapshot.reconciliation.status}`}><StatusChip label={snapshot.reconciliation.status === 'clean' ? 'Clean' : snapshot.reconciliation.status} tone={snapshot.reconciliation.status === 'clean' ? 'healthy' : 'danger'} /><span>{value(snapshot.reconciliation.worktreeCount)} worktrees</span><span>{value(snapshot.reconciliation.dirtyWorktreeCount)} dirty</span><span>{value(snapshot.reconciliation.unmergedBranchCount)} unmerged branches</span><span>{value(snapshot.reconciliation.unexplainedRecordCount)} unexplained records</span><span>{value(snapshot.reconciliation.activeStaleLeaseCount)} stale leases</span></div></section>
  </div>
}

function WorkerSummary({ worker, item, scopes }: { worker: FactoryWorker; item?: FactoryPackage; scopes: FactoryCapacityScope[] }) {
  return <article className="factory-card worker-summary"><div className="factory-card-heading"><div className="factory-avatar" aria-hidden="true">{worker.displayName.slice(0, 2).toUpperCase()}</div><div><h3>{worker.displayName}</h3><p>{worker.role === 'ORCHESTRA' ? 'Coordinator' : worker.provider && worker.model ? `${worker.provider} · ${worker.model}` : worker.role}</p></div><StatusChip label={worker.health} tone={worker.health} /></div>
    <p className="factory-assignment"><strong>{item?.title ?? 'No current assignment'}</strong><span>{item ? `${item.id} · ${item.lane ?? 'Lane unassigned'}` : 'Available work is shown in Queue'}</span></p>
    <dl className="factory-definition"><div><dt>Task elapsed</dt><dd>{item ? formatDuration(item.elapsedRuntimeSeconds) : '—'}</dd></div><div><dt>Heartbeat</dt><dd>{formatRelativeTime(worker.heartbeatAt)}</dd></div><div><dt>Attempt</dt><dd>{worker.currentAttempt ?? '—'}</dd></div><div><dt>Capacity</dt><dd>{worker.capacityState.replace('_', ' ')}</dd></div></dl>
    {scopes.length > 0 && <p className="factory-scope-line">{scopes.map(capacitySummary).join(' · ')}</p>}
  </article>
}

function Queue({ snapshot }: { snapshot: FactoryControlSnapshot }) {
  const [filters, setFilters] = useState<QueueFilters>(emptyQueueFilters)
  const packages = snapshot.features.flatMap(feature => feature.packages)
  const filtered = useMemo(() => filterFactoryFeatures(snapshot.features, filters), [snapshot.features, filters])
  const lanes = unique(packages.map(item => item.lane).filter((lane): lane is string => !!lane))
  const priorities = unique(packages.map(item => String(item.priority)))
  const set = (key: keyof QueueFilters, next: string) => setFilters(current => ({ ...current, [key]: next }))
  return <div className="factory-view"><section className="factory-section"><SectionHeading title="Feature queue" note={`${filtered.length} of ${snapshot.features.length} features shown`} />
    <div className="factory-filters" aria-label="Queue filters">
      <Filter label="State" value={filters.state} onChange={value => set('state', value)} options={['ON_DECK', 'READY', 'ACTIVE', 'VERIFY_REVIEW', 'BLOCKED', 'DONE'].map(item => [item, formatFactoryState(item as FactoryState)])} />
      <Filter label="Lane" value={filters.lane} onChange={value => set('lane', value)} options={lanes.map(item => [item, item])} />
      <Filter label="Worker" value={filters.worker} onChange={value => set('worker', value)} options={snapshot.workers.map(item => [item.id, item.displayName])} />
      <Filter label="Priority" value={filters.priority} onChange={value => set('priority', value)} options={priorities.map(item => [item, item])} />
      <Filter label="Feature" value={filters.feature} onChange={value => set('feature', value)} options={snapshot.features.map(item => [item.id, `${item.id} · ${item.title}`])} />
      <label>Blocked reason<input value={filters.blockedReason} onChange={event => set('blockedReason', event.target.value)} placeholder="Search reason" /></label>
      <button type="button" className="factory-button secondary" onClick={() => setFilters(emptyQueueFilters)}>Clear filters</button>
    </div>
    <div className="factory-feature-list">{filtered.length ? filtered.map(feature => <details className="factory-feature" open={feature.state === 'ACTIVE' || feature.state === 'VERIFY_REVIEW'} key={feature.id}><summary><div><span className="factory-id">{feature.id}</span><strong>{feature.title}</strong><small>{feature.description}</small></div><div><StatusChip label={formatFactoryState(feature.state)} tone={stateTone(feature.state)} /><span>{feature.packages.length} package{feature.packages.length === 1 ? '' : 's'}</span></div></summary><div className="factory-package-list">{feature.packages.map(item => <PackageCard item={item} workers={snapshot.workers} key={item.id} />)}</div></details>) : <Empty title="No queue items match these filters" text="Clear one or more filters to widen the view." />}</div>
  </section></div>
}

function PackageCard({ item, workers }: { item: FactoryPackage; workers: FactoryWorker[] }) {
  const owner = workers.find(worker => worker.id === item.ownerWorkerId)?.displayName
  return <article className="factory-package"><div className="factory-package-head"><div><span className="factory-id">{item.id}</span><h3>{item.title}</h3></div><StatusChip label={formatFactoryState(item.state)} tone={stateTone(item.state)} /></div>
    <div className="factory-package-facts"><Fact label="Priority" value={item.priority} /><Fact label="Lane" value={item.lane ?? 'Unassigned'} /><Fact label="Owner / lease" value={owner ? `${owner}${item.currentLease ? ` · ${item.currentLease.id}` : ''}` : 'Unclaimed'} /><Fact label="Attempt" value={item.attemptNumber || 'Not started'} /><Fact label="Runtime" value={formatDuration(item.elapsedRuntimeSeconds)} /><Fact label="Review" value={item.reviewState?.replace('_', ' ') ?? 'Not requested'} /></div>
    <div className="factory-package-columns"><InfoList title="Dependencies" items={item.dependencies} empty="None" /><InfoList title="Required capabilities" items={item.requiredCapabilities} empty="None declared" /><InfoList title="Acceptance criteria" items={item.acceptanceCriteria} empty="None recorded" /></div>
    {(item.blockReason || item.failureCode) && <p className="factory-block"><strong>{item.failureCode ?? 'Blocked'}</strong>{item.blockReason}</p>}
    <div className="factory-provenance"><Fact label="Branch" value={item.branch ?? 'Not created'} /><Fact label="Pull request" value={item.pullRequestUrl ? <SafeLink href={item.pullRequestUrl}>Open PR</SafeLink> : 'Not created'} /></div>
    <EvidenceList evidence={item.evidence} />
  </article>
}

function Workers({ snapshot }: { snapshot: FactoryControlSnapshot }) {
  const packages = packageIndex(snapshot.features)
  return <div className="factory-view"><section className="factory-section"><SectionHeading title="Worker diagnostics" note="Identity is diagnostic; eligibility comes from capabilities, lanes and current health" /><div className="factory-worker-list">{snapshot.workers.map(worker => { const current = worker.currentPackageId ? packages.get(worker.currentPackageId) : undefined; return <article className="factory-card worker-detail" key={worker.id}><div className="factory-card-heading"><div><span className="factory-id">{worker.id}</span><h2>{worker.displayName}</h2><p>{worker.provider ?? 'Provider unknown'} · {worker.model ?? 'Model unknown'}</p></div><StatusChip label={worker.health} tone={worker.health} /></div><div className="factory-worker-state"><Fact label="Service" value={worker.serviceState} /><Fact label="Authentication" value={worker.authenticationState} /><Fact label="Heartbeat" value={formatRelativeTime(worker.heartbeatAt)} /><Fact label="Current package" value={current ? `${current.id} · ${current.title}` : 'None'} /><Fact label="Active lease" value={worker.activeLease?.id ?? 'None'} /><Fact label="Attempt" value={worker.currentAttempt ?? '—'} /></div><div className="factory-worker-state"><Fact label="Productive runtime" value={formatDuration(worker.productiveRuntimeSeconds)} /><Fact label="Idle time" value={formatDuration(worker.idleSeconds)} /><Fact label="Blocked time" value={formatDuration(worker.blockedSeconds)} /><Fact label="Capacity state" value={worker.capacityState.replace('_', ' ')} /></div><div className="factory-package-columns"><InfoList title="Approved capabilities" items={worker.approvedCapabilities} empty="None" /><InfoList title="Approved lanes" items={worker.approvedLanes} empty="None" /><InfoList title="Recent tasks" items={worker.recentTaskIds} empty="None" /><InfoList title="Recent failures" items={worker.recentFailureIds} empty="None" /></div></article>})}</div></section></div>
}

function Reviews({ snapshot }: { snapshot: FactoryControlSnapshot }) {
  const packages = packageIndex(snapshot.features)
  const workerName = (id: string | null) => snapshot.workers.find(worker => worker.id === id)?.displayName ?? (id ?? 'Unassigned')
  return <div className="factory-view"><section className="factory-section"><SectionHeading title="Independent review queue" note={`${snapshot.reviews.filter(review => review.state !== 'approved').length} waiting or in progress`} />
    <div className="factory-review-list">{snapshot.reviews.length ? snapshot.reviews.map(review => <article className={`factory-card factory-review ${review.state}`} key={review.id}><div className="factory-card-heading"><div><span className="factory-id">{review.packageId}</span><h2>{packages.get(review.packageId)?.title ?? 'Unknown package'}</h2></div><StatusChip label={review.state.replace('_', ' ')} tone={review.state === 'approved' ? 'healthy' : review.state === 'changes_requested' ? 'danger' : 'warning'} /></div><div className="factory-worker-state"><Fact label="Implementer" value={workerName(review.implementerWorkerId)} /><Fact label="Assigned reviewer" value={workerName(review.assignedReviewerId)} /><Fact label="Eligible reviewers" value={review.eligibleReviewerIds.map(workerName).join(', ') || 'None'} /><Fact label="Review age" value={formatRelativeTime(review.requestedAt)} /></div><div className="factory-package-columns"><InfoList title="Findings" items={review.findings} empty="No findings recorded" /><InfoList title="Changes requested" items={review.changesRequested} empty="None" /></div><EvidenceList evidence={review.approvalEvidence} title="Approval evidence" /></article>) : <Empty title="Review queue is clear" text="No packages are waiting for independent review." />}</div>
  </section></div>
}

function Capacity({ snapshot }: { snapshot: FactoryControlSnapshot }) {
  const workerName = (id: string) => snapshot.workers.find(worker => worker.id === id)?.displayName ?? id
  return <div className="factory-view"><section className="factory-section"><SectionHeading title="Capacity scopes" note="Provider reports, Factory measurements and inference stay visibly separate" /><div className="factory-capacity-grid">{snapshot.capacity.map(scope => <article className="factory-card capacity-card" key={scope.id}><div className="factory-card-heading"><div><p className="factory-eyebrow">{workerName(scope.workerId)}</p><h2>{scope.label}</h2></div><StatusChip label={scope.state.replace('_', ' ')} tone={capacityTone(scope.state)} /></div><p className={`capacity-source ${scope.source}`}>{sourceLabel(scope.source)}</p><div className="capacity-primary">{scope.usedPercent === null ? <><strong>{formatNumber(scope.rolling24Hours.outputTokens)}</strong><span>output tokens / 24h</span></> : <><strong>{scope.usedPercent}%</strong><span>{scope.source === 'provider_reported' ? 'provider-reported usage' : 'inferred usage'}</span></>}</div>{scope.usedPercent !== null && <div className="capacity-meter" role="meter" aria-label={`${scope.label} usage`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={scope.usedPercent}><span style={{ width: `${Math.min(100, scope.usedPercent)}%` }} /></div>}<dl className="factory-definition"><div><dt>Observed</dt><dd>{formatRelativeTime(scope.observedAt)}</dd></div><div><dt>Reset</dt><dd>{scope.resetAt ? new Date(scope.resetAt).toLocaleString() : 'Not provided'}</dd></div><div><dt>Output / hour</dt><dd>{formatNumber(scope.outputTokensPerHour)}</dd></div><div><dt>Average / task</dt><dd>{formatNumber(scope.averageTokensPerTask)}</dd></div><div><dt>7-day tasks</dt><dd>{scope.rolling7Days.completedTasks}</dd></div><div><dt>Review throughput</dt><dd>{scope.reviewThroughput}</dd></div><div><dt>Limit hits</dt><dd>{scope.limitHitCount}</dd></div><div><dt>Inferred ceiling</dt><dd>{formatNumber(scope.inferredCeilingTokens)}</dd></div></dl>{scope.source === 'factory_measured' && <p className="factory-scope-line">No provider percentage is available. Eligibility follows live service, authentication and actual limit signals.</p>}</article>)}</div></section></div>
}

function History({ snapshot }: { snapshot: FactoryControlSnapshot }) {
  return <div className="factory-view"><section className="factory-section"><SectionHeading title="History and provenance" note={`${snapshot.events.length} Registry events in this projection`} /><ol className="factory-timeline">{snapshot.events.map(event => <li key={event.id}><span className="timeline-mark" aria-hidden="true" /><div><div className="factory-card-heading"><div><StatusChip label={event.kind.replace('_', ' ')} tone={event.kind === 'FAILURE' ? 'danger' : event.kind === 'DONE' ? 'healthy' : 'neutral'} /><time dateTime={event.occurredAt}>{new Date(event.occurredAt).toLocaleString()}</time></div><span className="factory-id">{event.packageId ?? event.featureId ?? 'Factory'}</span></div><p>{event.summary}</p><div className="factory-event-path"><span>Attempt {event.attemptNumber ?? '—'}</span><span>Worker {event.workerId ?? '—'}</span><span>Branch {event.branch ?? '—'}</span><span>Commit {event.commitSha ?? '—'}</span>{event.pullRequestUrl && <SafeLink href={event.pullRequestUrl}>Pull request</SafeLink>}<span>{event.evidenceIds.length} evidence item{event.evidenceIds.length === 1 ? '' : 's'}</span></div></div></li>)}</ol></section></div>
}

function Failures({ snapshot }: { snapshot: FactoryControlSnapshot }) {
  const workerName = (id: string | null) => snapshot.workers.find(worker => worker.id === id)?.displayName ?? (id ?? 'Factory')
  return <div className="factory-view"><section className="factory-section"><SectionHeading title="Failures requiring attention" note="Authentication, heartbeat, capacity, scope, CI, review, dependency and provenance issues" />{snapshot.failures.length ? <div className="factory-failure-list">{snapshot.failures.map(failure => <article className={`factory-card factory-failure ${failure.severity}`} key={failure.id}><div className="factory-card-heading"><div><span className="factory-id">{failure.code}</span><h2>{failure.title}</h2></div><StatusChip label={failure.requiresHuman ? 'Human action needed' : failure.severity} tone={failure.severity === 'critical' ? 'danger' : 'warning'} /></div><p>{failure.detail}</p><div className="factory-event-path"><span>{workerName(failure.workerId)}</span><span>{failure.packageId ?? 'No package'}</span><span>{formatRelativeTime(failure.occurredAt)}</span></div></article>)}</div> : <Empty title="No failures need attention" text="The current Registry projection contains no active intervention items." />}</section></div>
}

function LoadingPanel() { return <div className="factory-state-panel" role="status"><span className="factory-spinner" aria-hidden="true" /><h2>Loading verified Registry state</h2><p>The Control Center will remain closed if authentication or projection verification fails.</p></div> }
function ErrorPanel({ message, onRetry }: { message: string; onRetry: () => void }) { return <div className="factory-state-panel error" role="alert"><h2>Factory visibility is unavailable</h2><p>{message}</p><button type="button" className="factory-button" onClick={onRetry}>Try again</button></div> }
function Metric({ label, value: metricValue, tone = 'neutral' }: { label: string; value: ReactNode; tone?: string }) { return <article className={`factory-metric ${tone}`}><span>{label}</span><strong>{metricValue}</strong></article> }
function SectionHeading({ title, note }: { title: string; note: string }) { return <div className="factory-section-heading"><div><h2>{title}</h2><p>{note}</p></div></div> }
function Fact({ label, value: factValue }: { label: string; value: ReactNode }) { return <div className="factory-fact"><span>{label}</span><strong>{factValue}</strong></div> }
function InfoList({ title, items, empty }: { title: string; items: string[]; empty: string }) { return <div className="factory-info-list"><h4>{title}</h4>{items.length ? <ul>{items.map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}</ul> : <p>{empty}</p>}</div> }
function EvidenceList({ evidence, title = 'Evidence' }: { evidence: FactoryEvidence[]; title?: string }) { return <div className="factory-evidence"><h4>{title}</h4>{evidence.length ? <ul>{evidence.map(item => <li key={item.id}>{item.url ? <SafeLink href={item.url}>{item.label}</SafeLink> : <span>{item.label}</span>}<small>{item.kind} · {formatRelativeTime(item.recordedAt)}</small></li>)}</ul> : <p>No evidence recorded.</p>}</div> }
function SafeLink({ href, children }: { href: string; children: ReactNode }) { return <a href={href} target="_blank" rel="noreferrer">{children}</a> }
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
