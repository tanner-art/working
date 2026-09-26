import type { ThoughtObject } from './domain'
import { confirmObject, reviewObjects, setObjectKind } from './objectWorkflow'
import { actionResolution } from './resolutions/action'
import { commitmentResolution } from './resolutions/commitment'
import { reminderResolution } from './resolutions/reminder'

/** The only classifications this Review continuation can make. */
export const reviewResolutionKinds = ['action', 'commitment', 'reminder', 'idea'] as const
export type ReviewResolutionKind = typeof reviewResolutionKinds[number]

export type ReviewContinuationResult =
  | { status: 'completed'; object: ThoughtObject }
  | { status: 'unavailable'; message: string }

export type ReviewContinuation = (object: ThoughtObject) => Promise<ReviewContinuationResult> | ReviewContinuationResult

export type ReviewContinuations = Readonly<{
  action?: ReviewContinuation
  commitment?: ReviewContinuation
  reminder?: ReviewContinuation
}>

/**
 * Fixed, one-for-one adapter registration. Later packages replace adapter
 * implementations, not this registry or the Review mounting boundary.
 */
export const registeredReviewContinuations: ReviewContinuations = Object.freeze({
  action: actionResolution,
  commitment: commitmentResolution,
  reminder: reminderResolution,
})

export type ReviewResolutionResult =
  | { status: 'completed'; object: ThoughtObject }
  | { status: 'recoverable-error'; message: string }

const unavailable = (kind: Exclude<ReviewResolutionKind, 'idea'>): ReviewResolutionResult => ({
  status: 'recoverable-error',
  message: `${kind[0].toUpperCase()}${kind.slice(1)} resolution is unavailable. This capture remains in Review.`,
})

/**
 * Resolves exactly one pending capture. Only Idea is completed here: this is
 * the package's sole semantic/persistence transition. The other choices are
 * delegated to their owning packages and cannot remove a capture from Review
 * when their adapter is missing, unavailable, or throws.
 */
export async function resolveReviewCapture(
  object: ThoughtObject,
  kind: ReviewResolutionKind,
  continuations: ReviewContinuations = registeredReviewContinuations,
): Promise<ReviewResolutionResult> {
  if (!reviewObjects([object]).length) {
    return { status: 'recoverable-error', message: 'This capture is no longer awaiting review. Refresh Review and try again.' }
  }

  const classified = object.kind === kind ? object : setObjectKind(object, kind)
  if (kind === 'idea') return { status: 'completed', object: confirmObject(classified, 'idea') }

  const continuation = continuations[kind]
  if (!continuation) return unavailable(kind)
  try {
    const result = await continuation(classified)
    if (result.status !== 'completed') return { status: 'recoverable-error', message: result.message }
    return result
  } catch {
    return {
      status: 'recoverable-error',
      message: `${kind[0].toUpperCase()}${kind.slice(1)} resolution could not finish. This capture remains in Review; try again.`,
    }
  }
}
