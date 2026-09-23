import { completeTutorial, nextTutorialStep, previousTutorialStep, skipTutorial, TUTORIAL_STEPS, type TutorialState } from './onboarding'

export interface OnboardingTutorialProps {
  state: TutorialState
  onStateChange: (state: TutorialState) => void
  onSkip?: () => void
  onComplete?: () => void
}

export function OnboardingTutorial({ state, onStateChange, onSkip, onComplete }: OnboardingTutorialProps) {
  if (state.status !== 'active') return null
  const step = TUTORIAL_STEPS[state.stepIndex]
  const isLast = state.stepIndex === TUTORIAL_STEPS.length - 1

  function goNext() {
    const next = isLast ? completeTutorial(state) : nextTutorialStep(state)
    onStateChange(next)
    if (next.status === 'completed') onComplete?.()
  }

  function goSkip() {
    onStateChange(skipTutorial(state))
    onSkip?.()
  }

  return (
    <section
      aria-labelledby="onboarding-tutorial-title"
      aria-describedby="onboarding-tutorial-description"
      aria-modal="true"
      role="dialog"
      style={{
        boxSizing: 'border-box',
        width: 'min(100%, 32rem)',
        margin: '0 auto',
        padding: 'clamp(1rem, 5vw, 2rem)',
        border: '1px solid #ccd5c6',
        borderRadius: '1rem',
        background: '#fff',
        color: '#1f2a1d',
      }}
    >
      <p aria-live="polite" style={{ margin: '0 0 .75rem', fontSize: '.875rem' }}>
        Step {state.stepIndex + 1} of {TUTORIAL_STEPS.length}
      </p>
      <h2 id="onboarding-tutorial-title" style={{ margin: '0 0 .75rem' }}>{step.title}</h2>
      <p id="onboarding-tutorial-description" style={{ margin: '0 0 1.5rem', lineHeight: 1.5 }}>{step.description}</p>
      <nav aria-label="Tutorial controls" style={{ display: 'flex', flexWrap: 'wrap', gap: '.5rem', justifyContent: 'space-between' }}>
        <button type="button" onClick={goSkip} style={{ minHeight: '2.75rem' }}>Skip</button>
        <span style={{ display: 'flex', flexWrap: 'wrap', gap: '.5rem' }}>
          <button type="button" onClick={() => onStateChange(previousTutorialStep(state))} disabled={state.stepIndex === 0} style={{ minHeight: '2.75rem' }}>Back</button>
          <button type="button" onClick={goNext} style={{ minHeight: '2.75rem' }}>{isLast ? 'Finish' : 'Next'}</button>
        </span>
      </nav>
    </section>
  )
}
