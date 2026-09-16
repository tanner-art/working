export type AgentName = 'Claude' | 'Agent A' | 'Agent B' | 'Unassigned'
export type TaskStatus = 'running' | 'review' | 'failed' | 'ready' | 'open' | 'merged'

export type GitHubLabel = { name: string }
export type GitHubIssue = { number: number; title: string; html_url: string; state: string; labels: GitHubLabel[]; updated_at: string; created_at: string; pull_request?: unknown }
export type GitHubPull = { number: number; title: string; html_url: string; state: string; draft?: boolean; merged_at?: string | null; updated_at: string; created_at: string }

export type DashboardTask = { number: number; title: string; url: string; status: TaskStatus; agent: AgentName; updatedAt: string; createdAt: string }
export type AgentSummary = { agent: AgentName; running: number; review: number; failed: number; ready: number; open: number; merged: number; total: number }

const agentLabels: Record<string, AgentName> = {
  'agent:claude': 'Claude',
  'agent:codex-a': 'Agent A',
  'agent:codex-b': 'Agent B',
}

export function agentFromLabels(labels: GitHubLabel[]): AgentName {
  const found = labels.map(label => label.name).find(name => agentLabels[name])
  return found ? agentLabels[found] : 'Unassigned'
}

export function statusFromLabels(labels: GitHubLabel[]): TaskStatus {
  const names = new Set(labels.map(label => label.name))
  if (names.has('runner:running')) return 'running'
  if (names.has('runner:review')) return 'review'
  if (names.has('runner:failed')) return 'failed'
  if (names.has('runner:ready')) return 'ready'
  return 'open'
}

export function summarizeAgents(tasks: DashboardTask[]): AgentSummary[] {
  const agents: AgentName[] = ['Claude', 'Agent A', 'Agent B', 'Unassigned']
  return agents.map(agent => {
    const mine = tasks.filter(task => task.agent === agent)
    return {
      agent,
      running: mine.filter(task => task.status === 'running').length,
      review: mine.filter(task => task.status === 'review').length,
      failed: mine.filter(task => task.status === 'failed').length,
      ready: mine.filter(task => task.status === 'ready').length,
      open: mine.filter(task => task.status === 'open').length,
      merged: mine.filter(task => task.status === 'merged').length,
      total: mine.length,
    }
  })
}

export function buildTaskRows(issues: GitHubIssue[], pulls: GitHubPull[]): DashboardTask[] {
  const issueRows = issues
    .filter(issue => !issue.pull_request)
    .map(issue => ({
      number: issue.number,
      title: issue.title,
      url: issue.html_url,
      status: statusFromLabels(issue.labels),
      agent: agentFromLabels(issue.labels),
      updatedAt: issue.updated_at,
      createdAt: issue.created_at,
    }))
  const mergedRows = pulls
    .filter(pull => pull.merged_at)
    .slice(0, 8)
    .map(pull => ({
      number: pull.number,
      title: pull.title,
      url: pull.html_url,
      status: 'merged' as const,
      agent: 'Unassigned' as const,
      updatedAt: pull.merged_at ?? pull.updated_at,
      createdAt: pull.created_at,
    }))
  return [...issueRows, ...mergedRows].sort((a, b) => Date.parse(b.updatedAt) - Date.parse(a.updatedAt))
}

export function formatAge(iso: string, now = new Date()): string {
  const ms = Math.max(0, now.getTime() - Date.parse(iso))
  const minutes = Math.floor(ms / 60000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 48) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}
