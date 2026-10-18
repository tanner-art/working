import { createElement, type ReactElement } from 'react'
import { CapturedThoughtCard } from './card'

export type ThoughtStatus = 'open' | 'complete'

export type ThoughtStatusFixture = {
  complete: () => void
  reopen: () => void
  render: () => ReactElement
}

export function createThoughtStatusFixture(thought: string): ThoughtStatusFixture {
  let status: ThoughtStatus = 'open'

  const complete = () => {
    status = 'complete'
  }

  const reopen = () => {
    status = 'open'
  }

  const render = () => createElement(
    'section',
    { 'aria-label': 'Thought status' },
    createElement('p', { role: 'status' }, status === 'open' ? 'Open' : 'Complete'),
    createElement(CapturedThoughtCard, { thought }),
    status === 'open'
      ? createElement('button', { type: 'button', onClick: complete }, 'Complete')
      : createElement('button', { type: 'button', onClick: reopen }, 'Reopen'),
  )

  return { complete, reopen, render }
}
