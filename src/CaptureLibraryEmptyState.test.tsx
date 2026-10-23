import { beforeEach, describe, expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { CaptureLibrary } from './CaptureLibraryView'

const state = vi.hoisted(() => ({ index: 0, query: '', filter: 'all', allCaptures: true }))
vi.mock('react', async importOriginal => {
  const actual = await importOriginal<typeof import('react')>()
  return { ...actual, useState: (initial: unknown) => {
    const index = state.index++
    return actual.useState(index === 0 ? state.query : index === 1 ? state.filter : index === 3 ? state.allCaptures : initial)
  } }
})
beforeEach(() => { state.index = 0; state.query = ''; state.filter = 'all'; state.allCaptures = true })
const render = () => renderToStaticMarkup(<CaptureLibrary objects={[]} library={{ folders: [], placements: [] }} onOpen={() => undefined} onChange={() => undefined} />)
describe('empty capture views explain the active filter', () => {
  it('invites a first capture when the entire library is empty', () => {
    expect(render()).toContain('No captures yet. Capture a thought to get started.')
  })
  it('keeps folder placement guidance only for an unfiltered folder', () => {
    state.allCaptures = false
    expect(render()).toContain('Move one here from All captures.')
  })
  it.each(['open', 'completed'])('points back to All when %s has no results', filter => {
    state.filter = filter
    const html = render()
    expect(html).toContain('Choose All to see the rest.')
    expect(html).not.toContain('Move one here')
  })
  it('explains that search is limited by the completion filter', () => {
    state.filter = 'completed'; state.query = 'needle'
    expect(render()).toContain('No matches in this view. Try All or change your search.')
  })
})
