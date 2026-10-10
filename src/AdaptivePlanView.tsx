import type { AppState } from './domain'
import { calculateAdaptivePlan } from './adaptivePlan'

export function AdaptivePlanView({ state }: { state: AppState }) {
  try {
    const plan = calculateAdaptivePlan(state)
    return <main className="page schedule-page"><header className="page-header"><div><p className="eyebrow">Flexible work, never a calendar booking</p><h1>Adaptive Plan</h1></div></header>
      <p><a href="/schedule">Back to Schedule</a></p>
      {plan.recommendations.length ? <ol className="detail-list">{plan.recommendations.map((item, index) => <li key={item.objectId}><article><h2>{index === 0 ? 'Recommended next: ' : 'Also ready: '}{item.title}</h2><p>{item.explanation}</p></article></li>)}</ol>
        : <p className="empty">No Actions are eligible for the plan yet. Add a staged Action from Schedule when you are ready.</p>}
      {plan.blockedCount > 0 && <p role="status">{plan.blockedCount} eligible {plan.blockedCount === 1 ? 'Action is' : 'Actions are'} waiting on dependencies.</p>}
    </main>
  } catch {
    return <main className="page schedule-page"><h1>Adaptive Plan unavailable</h1><p role="alert">Action evidence could not be verified. No plan was calculated and your saved data was not changed.</p><a href="/schedule">Back to Schedule</a></main>
  }
}
