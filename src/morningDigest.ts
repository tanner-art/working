import type { ThoughtObject } from './domain'
import { confirmedActions, fixedCommitments } from './objectWorkflow'

export interface MorningDigest {
  fixedToday: ThoughtObject[]
  upcoming: ThoughtObject[]
  recommended: ThoughtObject[]
  needsReview: ThoughtObject[]
  projectSignals: ThoughtObject[]
}

export function buildMorningDigest(objects: ThoughtObject[], now = new Date()): MorningDigest {
  const today = localDateKey(now)
  const commitments = fixedCommitments(objects)
  const fixedToday = commitments.filter(item => commitmentDate(item) === today)
  const upcoming = commitments
    .filter(item => {
      const date = commitmentDate(item)
      return Boolean(date && date > today)
    })
    .sort((a, b) => commitmentDate(a)!.localeCompare(commitmentDate(b)!))
    .slice(0, 3)
  return {
    fixedToday,
    upcoming,
    recommended: confirmedActions(objects).slice(0, 3),
    needsReview: objects.filter(item => item.status === 'review').slice(0, 5),
    projectSignals: objects.filter(item => (item.kind === 'project' || item.kind === 'objective') && item.status === 'confirmed').slice(0, 3)
  }
}

function commitmentDate(item: ThoughtObject): string | undefined {
  const value = item.metadata.deadline ?? item.interpretation.suggestedDate
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return undefined
  const parsed = new Date(`${value}T00:00:00Z`)
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value ? value : undefined
}

function localDateKey(date: Date) {
  const year = date.getFullYear()
  const month = `${date.getMonth() + 1}`.padStart(2, '0')
  const day = `${date.getDate()}`.padStart(2, '0')
  return `${year}-${month}-${day}`
}
