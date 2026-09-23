import { useEffect, useMemo, useState } from 'react'
import { buildTaskRows, formatAge, summarizeAgents, type DashboardTask, type GitHubIssue, type GitHubPull } from './buildDashboard'

type LoadState = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; tasks: DashboardTask[]; refreshedAt: string }

const repo = 'tanner-art/working'
const apiBase = `https://api.github.com/repos/${repo}`

const statusLabels: Record<string, string> = {
  running: 'Working now', review: 'Needs review', failed: 'Blocked', ready: 'Queued', open: 'Open', merged: 'Shipped',
}

export function BuildDashboard() {
  const [load, setLoad] = useState<LoadState>({ status: 'loading' })
  const refresh = async () => {
    try {
      setLoad(current => current.status === 'ready' ? current : { status: 'loading' })
      const [issuesResponse, pullsResponse] = await Promise.all([
        fetch(`${apiBase}/issues?state=all&per_page=100`, { headers: { Accept: 'application/vnd.github+json' } }),
        fetch(`${apiBase}/pulls?state=closed&per_page=30&sort=updated&direction=desc`, { headers: { Accept: 'application/vnd.github+json' } }),
      ])
      if (!issuesResponse.ok || !pullsResponse.ok) throw new Error('GitHub public API did not return the dashboard data.')
      const issues = await issuesResponse.json() as GitHubIssue[]
      const pulls = await pullsResponse.json() as GitHubPull[]
      setLoad({ status: 'ready', tasks: buildTaskRows(issues, pulls), refreshedAt: new Date().toISOString() })
    } catch (error) {
      setLoad({ status: 'error', message: error instanceof Error ? error.message : 'Unable to refresh dashboard.' })
    }
  }
  useEffect(() => { void refresh(); const id = window.setInterval(() => { void refresh() }, 120000); return () => window.clearInterval(id) }, [])
  const tasks = load.status === 'ready' ? load.tasks : []
  const visibleTasks = tasks.filter(task => task.status !== 'merged').slice(0, 12)
  const shipped = tasks.filter(task => task.status === 'merged').slice(0, 8)
  const summary = useMemo(() => summarizeAgents(tasks.filter(task => task.status !== 'merged')), [tasks])
  const shippedCount = shipped.length
  const activeCount = visibleTasks.filter(task => task.status === 'running').length
  const blockedCount = visibleTasks.filter(task => task.status === 'failed').length
  const reviewCount = visibleTasks.filter(task => task.status === 'review').length

  return <main className="public-dashboard">
    <section className="dashboard-hero">
      <div>
        <p className="eyebrow">Threadline build room</p>
        <h1>Live agent dashboard</h1>
        <p>Watch the public build pulse: what shipped, what is being worked, what needs review, and where Claude, Agent A, and Agent B are spending time.</p>
      </div>
      <div className="dashboard-actions">
        <a className="secondary" href="/">Open app</a>
        <a className="secondary" href="https://github.com/tanner-art/working/issues" target="_blank" rel="noreferrer">Open task queue</a>
        <a className="secondary" href="https://github.com/tanner-art/working/issues/new" target="_blank" rel="noreferrer">Add task</a>
        <button className="primary" onClick={() => void refresh()}>Refresh</button>
      </div>
    </section>

    <section className="dashboard-metrics" aria-label="Build summary">
      <Metric label="Active now" value={activeCount} tone="green" />
      <Metric label="Needs review" value={reviewCount} tone="gold" />
      <Metric label="Blocked" value={blockedCount} tone="red" />
      <Metric label="Recently shipped" value={shippedCount} tone="blue" />
    </section>

    <section className="agent-grid" aria-label="Agent activity">
      {summary.filter(agent => agent.agent !== 'Unassigned' || agent.total > 0).map(agent => <article className="agent-card" key={agent.agent}>
        <div className="agent-orb" aria-hidden="true">{agent.agent === 'Claude' ? '◇' : agent.agent === 'Agent A' ? 'A' : agent.agent === 'Agent B' ? 'B' : '·'}</div>
        <div><h2>{agent.agent}</h2><p>{agent.running ? 'Working now' : agent.review ? 'Waiting on review' : agent.failed ? 'Has a blocker' : agent.ready ? 'Queued up' : 'Idle or unassigned'}</p></div>
        <div className="agent-bars">
          <span style={{ ['--bar' as string]: `${Math.min(100, agent.running * 35 + agent.review * 25 + agent.ready * 18 + agent.failed * 15)}%` }} />
        </div>
        <p className="agent-counts">{agent.running} running · {agent.review} review · {agent.failed} blocked · {agent.ready} queued</p>
      </article>)}
    </section>

    {load.status === 'error' && <p className="dashboard-error" role="alert">{load.message}</p>}
    {load.status === 'loading' && <p className="dashboard-loading" role="status">Loading public GitHub project data…</p>}

    <section className="dashboard-columns">
      <div className="dashboard-panel">
        <div className="panel-heading"><h2>Current task board</h2><p>{load.status === 'ready' ? `Updated ${formatAge(load.refreshedAt)}` : 'Live public data'}</p></div>
        <div className="task-stack">{visibleTasks.length ? visibleTasks.map(task => <TaskRow task={task} key={`${task.status}-${task.number}`} />) : <p>No active public tasks found.</p>}</div>
      </div>
      <div className="dashboard-panel shipped-panel">
        <div className="panel-heading"><h2>Recently accomplished</h2><p>Latest merged public work</p></div>
        <div className="ship-list">{shipped.map(task => <a href={task.url} key={task.number} target="_blank" rel="noreferrer"><span>#{task.number}</span><strong>{task.title.replace(/^TASK-\d+:\s*/, '')}</strong><small>{formatAge(task.updatedAt)}</small></a>)}</div>
      </div>
    </section>
  </main>
}

function Metric({ label, value, tone }: { label: string; value: number; tone: string }) {
  return <article className={`metric-card ${tone}`}><strong>{value}</strong><span>{label}</span></article>
}

function TaskRow({ task }: { task: DashboardTask }) {
  return <a className={`task-row ${task.status}`} href={task.url} target="_blank" rel="noreferrer">
    <span className="task-status">{statusLabels[task.status]}</span>
    <strong>#{task.number} {task.title}</strong>
    <small>{task.agent} · updated {formatAge(task.updatedAt)}</small>
  </a>
}
