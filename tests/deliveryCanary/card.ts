import { createElement, type ReactElement } from 'react'

export const EMPTY_THOUGHT_LABEL = 'No captured thought yet.'

export type CapturedThoughtCardProps = {
  thought: string
}

export function CapturedThoughtCard({ thought }: CapturedThoughtCardProps): ReactElement {
  const trimmedThought = thought.trim()

  return createElement(
    'article',
    { 'aria-label': 'Captured thought preview' },
    trimmedThought || EMPTY_THOUGHT_LABEL,
  )
}
