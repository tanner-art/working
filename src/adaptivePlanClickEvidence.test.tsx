import { afterEach, describe, expect, it, vi } from 'vitest'
import { isValidElement, type ReactElement } from 'react'
import type { AppState, ThoughtObject } from './domain'
import { ScheduleView } from './ScheduleView'
import { stageAction } from './actionStaging'
import { calculateAdaptivePlan } from './adaptivePlan'
import { accountData, createAccountSession, type AccountAdapter, type AccountRow } from './accountStorage'
import { disabledDelivery } from './digestDelivery'
import { legacyUiProjection, migrateLegacyState } from './migration'
import { reverseObject } from './objectWorkflow'
import { defaultSettings } from './settings'
import { loadStateResult, saveState } from './store'

// Vitest has no mounted DOM environment in this repo. Invoke the real Schedule
// component tree and its button callback; mounted App/browser evidence is separate.
vi.mock('react', async importOriginal => {
  const actual = await importOriginal<typeof import('react')>()
  return { ...actual,
    useMemo: (factory: () => unknown) => factory(),
    useState: (initial: unknown) => [typeof initial === 'function' ? (initial as () => unknown)() : initial, () => undefined],
  }
})

type HostElement = ReactElement<{ children?: unknown; onClick?: () => void; role?: string }>

function hostElements(node: unknown): HostElement[] {
  if (Array.isArray(node)) return node.flatMap(hostElements)
  if (!isValidElement(node)) return []
  const element = node as HostElement
  if (typeof element.type === 'function') return hostElements((element.type as (props: typeof element.props) => unknown)(element.props))
  return [element, ...hostElements(element.props.children)]
}

function words(node: unknown): string {
  if (Array.isArray(node)) return node.map(words).join(' ')
  if (isValidElement(node)) return words((node as HostElement).props.children)
  return typeof node === 'string' || typeof node === 'number' ? String(node) : ''
}

function schedule(state: AppState, update: (next: (state: AppState) => AppState) => void) {
  const elements = hostElements(ScheduleView({ state, update }))
  return {
    click(label: 'Add to plan' | 'Remove from plan') {
      const button = elements.find(element => element.type === 'button' && words(element.props.children) === label)
      expect(button, `Schedule must render ${label}`).toBeDefined()
      button!.props.onClick!()
    },
    visible(message: string) {
      expect(elements.some(element => element.props.role === 'status' && words(element.props.children).replace(/\s+/g, ' ').includes(message))).toBe(true)
    },
    absent(message: string) {
      expect(elements.some(element => element.props.role === 'status' && words(element.props.children).replace(/\s+/g, ' ').includes(message))).toBe(false)
    },
  }
}

const reviewAction = (id = 'plan-action'): ThoughtObject => ({
  id, kind: 'action', status: 'review', originalContent: 'Prepare launch', source: 'text', createdAt: '2026-10-09T08:00:00.000Z',
  confidence: .8, interpretation: { summary: 'Prepare launch', suggestedKind: 'action', rationale: 'Work' },
  metadata: {}, relationships: [], history: [],
})

function stagedState(dependency = false): AppState {
  const prerequisite: ThoughtObject = { ...reviewAction('prerequisite'), kind: 'idea', originalContent: 'Finish prerequisite',
    interpretation: { summary: 'Finish prerequisite', suggestedKind: 'idea', rationale: 'Needed first' } }
  const action = { ...reviewAction(), relationships: dependency ? [{ targetId: 'prerequisite', type: 'depends_on' as const }] : [] }
  const base = legacyUiProjection(migrateLegacyState({ objects: dependency ? [action, prerequisite] : [action], canvas: [] }))
  return { ...base, objects: base.objects.map(object => object.id === action.id ? stageAction(object) : object) }
}

afterEach(() => vi.unstubAllGlobals())

describe('AG-03 preparatory Schedule click evidence', () => {
  it('clicks Add and Remove through App-style state update and local save/reload, then reverses eligibility', () => {
    const storage = new Map<string, string>()
    vi.stubGlobal('localStorage', { getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => { storage.set(key, value) } })
    expect(saveState(stagedState())).toBeUndefined()
    let state = loadStateResult().state
    const update = (next: (current: AppState) => AppState) => {
      state = next(state) // App's synchronous latest-state update before its persistence effect.
      expect(saveState(state)).toBeUndefined()
    }
    schedule(state, update).click('Add to plan')
    state = loadStateResult().state
    schedule(state, update).visible('Adaptive Plan recommends next: Prepare launch')
    expect(state.objects[0].history.at(-1)?.planEligibility?.eligible).toBe(true)
    expect(state.model?.calendarEvents).toEqual([])
    schedule(state, update).click('Remove from plan')
    state = loadStateResult().state
    schedule(state, update).absent('Adaptive Plan recommends next: Prepare launch')
    expect(state.objects[0].history.map(entry => entry.planEligibility?.eligible).filter(value => value !== undefined)).toEqual([true, false])
    schedule(state, update).click('Add to plan')
    state = loadStateResult().state
    state = { ...state, objects: state.objects.map(object => object.id === 'plan-action' ? reverseObject(object) : object) }
    expect(saveState(state)).toBeUndefined()
    const reversed = loadStateResult().state
    schedule(reversed, update).absent('Adaptive Plan recommends next: Prepare launch')
    expect(calculateAdaptivePlan(reversed).recommendations).toEqual([])
  })

  it('clicks Add and Remove through account session save/reload without touching local data', async () => {
    const localWrite = vi.fn()
    vi.stubGlobal('localStorage', { getItem: () => 'preserved local data', setItem: localWrite })
    let row: AccountRow | null = null
    let revision = 0
    const adapter: AccountAdapter = {
      async read(userId) { return row?.user_id === userId ? structuredClone(row) : null },
      async write(userId, data, previous) {
        if (row ? previous !== row.revision : previous !== null) throw Error('revision conflict')
        row = { user_id: userId, revision: `revision-${++revision}`, data: structuredClone(data) }
        return structuredClone(row)
      },
    }
    const owner = 'account-owner'
    let session = createAccountSession(adapter, owner, () => owner)
    let state = (await session.open(accountData(stagedState(), defaultSettings, disabledDelivery))).state
    const pending: Promise<void>[] = []
    const update = (next: (current: AppState) => AppState) => {
      state = next(state) // App's update precedes its async account persistence effect.
      pending.push(session.save(session.snapshot(state, defaultSettings, disabledDelivery)))
    }
    schedule(state, update).click('Add to plan')
    await Promise.all(pending.splice(0))
    session = createAccountSession(adapter, owner, () => owner)
    state = (await session.open()).state
    schedule(state, update).visible('Adaptive Plan recommends next: Prepare launch')
    expect(state.model?.calendarEvents).toEqual([])
    schedule(state, update).click('Remove from plan')
    await Promise.all(pending.splice(0))
    state = (await createAccountSession(adapter, owner, () => owner).open()).state
    schedule(state, update).absent('Adaptive Plan recommends next: Prepare launch')
    expect(state.objects[0].history.map(entry => entry.planEligibility?.eligible).filter(value => value !== undefined)).toEqual([true, false])
    expect(localWrite).not.toHaveBeenCalled()
  })

  it('clicks Add for dependency-blocked work, then reloads the visible block without a recommendation', () => {
    const storage = new Map<string, string>()
    vi.stubGlobal('localStorage', { getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => { storage.set(key, value) } })
    expect(saveState(stagedState(true))).toBeUndefined()
    let state = loadStateResult().state
    schedule(state, next => { state = next(state); expect(saveState(state)).toBeUndefined() }).click('Add to plan')
    state = loadStateResult().state
    const view = schedule(state, () => undefined)
    view.visible('1 eligible Action is waiting on dependencies.')
    view.absent('Adaptive Plan recommends next: Prepare launch')
    expect(calculateAdaptivePlan(state)).toMatchObject({ recommendations: [], blockedCount: 1 })
  })
})
