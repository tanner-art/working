export const ONBOARDING_TUTORIAL_VERSION = 1
export const ONBOARDING_TUTORIAL_STORAGE_KEY = 'threadline-onboarding-tutorial-v1'

export const TUTORIAL_STEPS = [
  {
    id: 'capture' as const,
    title: 'Capture a thought',
    description: 'Start with a thought in your own words. Threadline keeps the original expression.',
  },
  {
    id: 'organize' as const,
    title: 'Organize and confirm its meaning',
    description: 'Review what Threadline understands and confirm or adjust its meaning before it becomes actionable.',
  },
  {
    id: 'calendar' as const,
    title: 'See commitments in Calendar',
    description: 'Use Calendar to see commitments alongside scheduled events without changing either one automatically.',
  },
  {
    id: 'canvas' as const,
    title: 'Create/open a Canvas',
    description: 'Use a Canvas to arrange ideas spatially and return to your visual thinking later.',
  },
] as const

export type TutorialStepId = (typeof TUTORIAL_STEPS)[number]['id']
export type TutorialStatus = 'not-started' | 'active' | 'skipped' | 'completed'

export interface TutorialState {
  version: number
  stepIndex: number
  status: TutorialStatus
  seenStepIds: TutorialStepId[]
}

export interface TutorialPersistence {
  version: number
  seenStepIds: TutorialStepId[]
  dismissed: boolean
}

export interface StorageLike {
  getItem(key: string): string | null
  setItem(key: string, value: string): void
}

const stepIds = TUTORIAL_STEPS.map(step => step.id)

export function initialTutorialState(): TutorialState {
  return { version: ONBOARDING_TUTORIAL_VERSION, stepIndex: 0, status: 'not-started', seenStepIds: [] }
}

export function startTutorial(state: TutorialState = initialTutorialState()): TutorialState {
  const firstUnseen = TUTORIAL_STEPS.findIndex(step => !state.seenStepIds.includes(step.id))
  return {
    ...state,
    version: ONBOARDING_TUTORIAL_VERSION,
    stepIndex: firstUnseen === -1 ? TUTORIAL_STEPS.length - 1 : firstUnseen,
    status: 'active',
  }
}

export function nextTutorialStep(state: TutorialState): TutorialState {
  if (state.status !== 'active') return state
  const seenStepIds = state.seenStepIds.includes(TUTORIAL_STEPS[state.stepIndex].id)
    ? state.seenStepIds
    : [...state.seenStepIds, TUTORIAL_STEPS[state.stepIndex].id]
  if (state.stepIndex >= TUTORIAL_STEPS.length - 1) {
    return { ...state, seenStepIds, status: 'completed' }
  }
  return { ...state, stepIndex: state.stepIndex + 1, seenStepIds }
}

export function previousTutorialStep(state: TutorialState): TutorialState {
  if (state.status !== 'active' || state.stepIndex === 0) return state
  return { ...state, stepIndex: state.stepIndex - 1 }
}

export function skipTutorial(state: TutorialState): TutorialState {
  return { ...state, status: 'skipped' }
}

export function completeTutorial(state: TutorialState): TutorialState {
  return { ...state, stepIndex: TUTORIAL_STEPS.length - 1, status: 'completed', seenStepIds: [...stepIds] }
}

function isStepId(value: unknown): value is TutorialStepId {
  return typeof value === 'string' && stepIds.includes(value as TutorialStepId)
}

function isPersistence(value: unknown): value is TutorialPersistence {
  if (!value || typeof value !== 'object') return false
  const record = value as Record<string, unknown>
  return typeof record.version === 'number' && Number.isInteger(record.version)
    && typeof record.dismissed === 'boolean'
    && Array.isArray(record.seenStepIds) && record.seenStepIds.every(isStepId)
}

export function readTutorialPersistence(storage: StorageLike): TutorialPersistence | null {
  const raw = storage.getItem(ONBOARDING_TUTORIAL_STORAGE_KEY)
  if (!raw) return null
  try {
    const value: unknown = JSON.parse(raw)
    return isPersistence(value) ? value : null
  } catch {
    return null
  }
}

export function writeTutorialPersistence(storage: StorageLike, persistence: TutorialPersistence): void {
  storage.setItem(ONBOARDING_TUTORIAL_STORAGE_KEY, JSON.stringify(persistence))
}

export function stateFromTutorialPersistence(storage: StorageLike): TutorialState {
  const persistence = readTutorialPersistence(storage)
  if (!persistence || persistence.dismissed && persistence.version === ONBOARDING_TUTORIAL_VERSION) {
    return initialTutorialState()
  }
  const state = { ...initialTutorialState(), seenStepIds: persistence.seenStepIds }
  return startTutorial(state)
}

export function persistTutorialState(storage: StorageLike, state: TutorialState): void {
  writeTutorialPersistence(storage, {
    version: ONBOARDING_TUTORIAL_VERSION,
    seenStepIds: state.seenStepIds,
    dismissed: state.status === 'skipped' || state.status === 'completed',
  })
}
