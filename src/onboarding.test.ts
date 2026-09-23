import { describe, expect, it, vi } from 'vitest'
import {
  completeTutorial, initialTutorialState, nextTutorialStep, ONBOARDING_TUTORIAL_STORAGE_KEY,
  persistTutorialState, previousTutorialStep, readTutorialPersistence, skipTutorial,
  startTutorial, stateFromTutorialPersistence, TUTORIAL_STEPS,
} from './onboarding'

function storage(initial?: string) {
  let value = initial ?? null
  return {
    getItem: vi.fn(() => value),
    setItem: vi.fn((_key: string, next: string) => { value = next }),
  }
}

describe('first-run tutorial state', () => {
  it('progresses forward and backward without changing product data', () => {
    let state = startTutorial()
    expect(state.stepIndex).toBe(0)
    state = nextTutorialStep(state)
    expect(state.stepIndex).toBe(1)
    expect(previousTutorialStep(state).stepIndex).toBe(0)
    expect(previousTutorialStep(initialTutorialState())).toEqual(initialTutorialState())
  })

  it('can be skipped and completed explicitly', () => {
    expect(skipTutorial(startTutorial()).status).toBe('skipped')
    let state = startTutorial()
    for (let index = 0; index < TUTORIAL_STEPS.length - 1; index += 1) state = nextTutorialStep(state)
    state = nextTutorialStep(state)
    expect(state.status).toBe('completed')
    expect(state.seenStepIds).toEqual(TUTORIAL_STEPS.map(step => step.id))
    expect(completeTutorial(startTutorial()).status).toBe('completed')
  })

  it('ignores corrupt storage and preserves only known progress', () => {
    expect(readTutorialPersistence(storage('{'))).toBeNull()
    expect(readTutorialPersistence(storage(JSON.stringify({ version: 1, dismissed: false, seenStepIds: ['unknown'] })))).toBeNull()
    const persisted = storage(JSON.stringify({ version: 1, dismissed: false, seenStepIds: ['capture'] }))
    expect(stateFromTutorialPersistence(persisted).stepIndex).toBe(1)
  })

  it('reoffers unseen material after a tutorial version changes', () => {
    const persisted = storage(JSON.stringify({ version: 0, dismissed: true, seenStepIds: ['capture', 'organize'] }))
    expect(stateFromTutorialPersistence(persisted)).toMatchObject({ status: 'active', stepIndex: 2, seenStepIds: ['capture', 'organize'] })
  })

  it('persists dismissal by versioned key without touching another key', () => {
    const store = storage()
    persistTutorialState(store, skipTutorial(startTutorial()))
    expect(store.setItem).toHaveBeenCalledWith(ONBOARDING_TUTORIAL_STORAGE_KEY, expect.any(String))
    expect(JSON.parse(store.setItem.mock.calls[0][1])).toMatchObject({ version: 1, dismissed: true })
  })
})
