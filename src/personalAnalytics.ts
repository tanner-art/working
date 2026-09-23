/** Inputs are deliberately local snapshots, not a storage or network adapter. */
export interface PersonalAnalyticsRecord {
  originalContent?: unknown
  content?: unknown
  kind?: unknown
  status?: unknown
  createdAt?: unknown
  completedAt?: unknown
}

export interface PersonalAnalyticsInput {
  thoughts?: readonly PersonalAnalyticsRecord[]
  commitments?: readonly PersonalAnalyticsRecord[]
  /** Ranking is never inferred from data; only the literal true opts in. */
  crossUserRankingOptIn?: boolean
}

export interface PersonalStatistics {
  thoughtCount: number
  averageThoughtCharacterCount: number | null
  commitmentCount: number
  completionRate: number | null
  averageCompletionTimeMs: number | null
  crossUserRankingOptIn: boolean
}

const completedStatuses = new Set(['complete', 'completed'])

function isRecord(value: unknown): value is PersonalAnalyticsRecord {
  return !!value && typeof value === 'object' && !Array.isArray(value)
}

function textOf(record: PersonalAnalyticsRecord): string | null {
  const value = record.originalContent ?? record.content
  return typeof value === 'string' ? value : null
}

function timestampOf(value: unknown): number | null {
  if (typeof value !== 'string' || value.trim() === '') return null
  const timestamp = Date.parse(value)
  return Number.isFinite(timestamp) ? timestamp : null
}

function usableRecords(records: readonly PersonalAnalyticsRecord[] | undefined): PersonalAnalyticsRecord[] {
  return (records ?? []).filter(isRecord)
}

/**
 * Calculates private, personal statistics from already-loaded local records.
 * Invalid records and unavailable measurements are ignored rather than guessed.
 */
export function calculatePersonalStatistics(input: PersonalAnalyticsInput = {}): PersonalStatistics {
  const thoughts = usableRecords(input.thoughts).filter(record => textOf(record) !== null)
  const commitmentSource = input.commitments === undefined
    ? thoughts.filter(record => record.kind === 'commitment')
    : usableRecords(input.commitments)
  const characterCounts = thoughts
    .map(textOf)
    .filter((value): value is string => value !== null)
    .map(value => Array.from(value).length)
  const completed = commitmentSource.filter(record => completedStatuses.has(record.status as string))
  const completionTimes = completed
    .map(record => {
      const createdAt = timestampOf(record.createdAt)
      const completedAt = timestampOf(record.completedAt)
      if (createdAt === null || completedAt === null || completedAt < createdAt) return null
      return completedAt - createdAt
    })
    .filter((value): value is number => value !== null)

  return {
    thoughtCount: thoughts.length,
    averageThoughtCharacterCount: characterCounts.length === 0
      ? null
      : characterCounts.reduce((sum, count) => sum + count, 0) / characterCounts.length,
    commitmentCount: commitmentSource.length,
    completionRate: commitmentSource.length === 0 ? null : completed.length / commitmentSource.length,
    averageCompletionTimeMs: completionTimes.length === 0
      ? null
      : completionTimes.reduce((sum, duration) => sum + duration, 0) / completionTimes.length,
    crossUserRankingOptIn: input.crossUserRankingOptIn === true,
  }
}
