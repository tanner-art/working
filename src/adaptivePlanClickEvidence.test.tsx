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

type HostElement = ReactElement<{ children?: unknown; onClick?: () => void; role?: string; open?: boolean }>

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
  const tree = ScheduleView({ state, update }) as HostElement
  const elements = hostElements(tree)
  const directChildren = Array.isArray(tree.props.children) ? tree.props.children : [tree.props.children]
  const topLevelStatus = directChildren.filter(isValidElement).map(element => element as HostElement)
    .filter(element => element.type === 'p' && element.props.role === 'status')
  const hasText = (elements: HostElement[], message: string) => elements.some(element =>
    element.props.role === 'status' && words(element.props.children).replace(/\s+/g, ' ').includes(message))
  return {
    click(label: 'Add to plan' | 'Remove from plan') {
      const button = elements.find(element => element.type === 'button' && words(element.props.children) === label)
      expect(button, `Schedule must render ${label}`).toBeDefined()
      button!.props.onClick!()
    },
    topLevelStatus(message: string) {
      expect(hasText(topLevelStatus, message)).toBe(true)
    },
    noTopLevelStatus(message: string) {
      expect(hasText(topLevelStatus, message)).toBe(false)
    },
    collapsedDetailsStatus(message: string) {
      const details = elements.find(element => element.type === 'details')
      expect(details).toBeDefined()
      expect(details!.props.open).not.toBe(true)
      expect(hasText(hostElements(details!.props.children), message)).toBe(true)
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
  it('invokes Add and Remove handlers with App-style state update and local save/reload, then reverses eligibility', () => {
    const storage = new Map<string, string>()
    vi.stubGlobal('localStorage', { getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => { storage.set(key, value) } })
    expect(saveState(stagedState())).toBeUndefined()
    let state = loadStateResult().state
    let updateCalls = 0
    let saveResult: string | undefined
    const update = (next: (current: AppState) => AppState) => {
      state = next(state) // Mirrors App's synchronous latest-state update before its persistence effect.
      updateCalls += 1
      saveResult = saveState(state)
    }
    schedule(state, update).click('Add to plan')
    expect(updateCalls).toBe(1)
    expect(saveResult).toBeUndefined()
    state = loadStateResult().state
    schedule(state, update).topLevelStatus('Adaptive Plan recommends next: Prepare launch')
    expect(state.objects[0].history.at(-1)?.planEligibility?.eligible).toBe(true)
    expect(state.model?.calendarEvents).toEqual([])
    schedule(state, update).click('Remove from plan')
    expect(updateCalls).toBe(2)
    expect(saveResult).toBeUndefined()
    state = loadStateResult().state
    schedule(state, update).noTopLevelStatus('Adaptive Plan recommends next: Prepare launch')
    expect(state.objects[0].history.map(entry => entry.planEligibility?.eligible).filter(value => value !== undefined)).toEqual([true, false])
    expect(state.model?.calendarEvents).toEqual([])
    schedule(state, update).click('Add to plan')
    expect(updateCalls).toBe(3)
    expect(saveResult).toBeUndefined()
    state = loadStateResult().state
    state = { ...state, objects: state.objects.map(object => object.id === 'plan-action' ? reverseObject(object) : object) }
    expect(saveState(state)).toBeUndefined()
    const reversed = loadStateResult().state
    schedule(reversed, update).noTopLevelStatus('Adaptive Plan recommends next: Prepare launch')
    expect(calculateAdaptivePlan(reversed).recommendations).toEqual([])
    expect(reversed.model?.calendarEvents).toEqual([])
  })

  it('invokes Add and Remove handlers through account session save/reload, keeping another account and local data untouched', async () => {
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
    let currentUser = owner
    let session = createAccountSession(adapter, owner, () => currentUser)
    let state = (await session.open(accountData(stagedState(), defaultSettings, disabledDelivery))).state
    await expect(createAccountSession(adapter, 'other-account', () => 'other-account').open()).rejects.toThrow('No account data yet')
    const pending: Promise<void>[] = []
    let updateCalls = 0
    const update = (next: (current: AppState) => AppState) => {
      state = next(state) // Mirrors App's update before its async account persistence effect.
      updateCalls += 1
      pending.push(session.save(session.snapshot(state, defaultSettings, disabledDelivery)))
    }
    schedule(state, update).click('Add to plan')
    expect(updateCalls).toBe(1)
    expect(pending).toHaveLength(1)
    await Promise.all(pending.splice(0))
    session = createAccountSession(adapter, owner, () => currentUser)
    state = (await session.open()).state
    schedule(state, update).topLevelStatus('Adaptive Plan recommends next: Prepare launch')
    expect(state.model?.calendarEvents).toEqual([])
    schedule(state, update).click('Remove from plan')
    expect(updateCalls).toBe(2)
    expect(pending).toHaveLength(1)
    await Promise.all(pending.splice(0))
    session = createAccountSession(adapter, owner, () => currentUser)
    state = (await session.open()).state
    schedule(state, update).noTopLevelStatus('Adaptive Plan recommends next: Prepare launch')
    expect(state.objects[0].history.map(entry => entry.planEligibility?.eligible).filter(value => value !== undefined)).toEqual([true, false])
    expect(state.model?.calendarEvents).toEqual([])
    schedule(state, update).click('Add to plan')
    expect(updateCalls).toBe(3)
    expect(pending).toHaveLength(1)
    await Promise.all(pending.splice(0))
    session = createAccountSession(adapter, owner, () => currentUser)
    state = (await session.open()).state
    state = { ...state, objects: state.objects.map(object => object.id === 'plan-action' ? reverseObject(object) : object) }
    await session.save(session.snapshot(state, defaultSettings, disabledDelivery))
    state = (await createAccountSession(adapter, owner, () => currentUser).open()).state
    schedule(state, update).noTopLevelStatus('Adaptive Plan recommends next: Prepare launch')
    expect(calculateAdaptivePlan(state).recommendations).toEqual([])
    expect(state.model?.calendarEvents).toEqual([])
    const ownerRow = structuredClone(row)
    currentUser = 'other-account'
    await expect(session.save(session.snapshot(state, defaultSettings, disabledDelivery))).rejects.toThrow('Account session changed')
    expect(row).toEqual(ownerRow)
    await expect(createAccountSession(adapter, 'other-account', () => 'other-account').open()).rejects.toThrow('No account data yet')
    expect(localWrite).not.toHaveBeenCalled()
  })

  it('invokes Add for dependency-blocked work, then reloads the collapsed-details block text without a recommendation', () => {
    const storage = new Map<string, string>()
    vi.stubGlobal('localStorage', { getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => { storage.set(key, value) } })
    expect(saveState(stagedState(true))).toBeUndefined()
    let state = loadStateResult().state
    let updateCalls = 0
    let saveResult: string | undefined
    schedule(state, next => { state = next(state); updateCalls += 1; saveResult = saveState(state) }).click('Add to plan')
    expect(updateCalls).toBe(1)
    expect(saveResult).toBeUndefined()
    state = loadStateResult().state
    const view = schedule(state, () => undefined)
    view.collapsedDetailsStatus('1 eligible Action is waiting on dependencies.')
    view.noTopLevelStatus('Adaptive Plan recommends next: Prepare launch')
    expect(calculateAdaptivePlan(state)).toMatchObject({ recommendations: [], blockedCount: 1 })
    expect(state.model?.calendarEvents).toEqual([])
  })
})
