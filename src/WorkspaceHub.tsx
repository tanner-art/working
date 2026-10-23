export type HubDestination = 'review' | 'canvas' | 'schedule' | 'calendar'

export function WorkspaceHub({ kind, onOpen }: { kind: 'organize' | 'plan'; onOpen: (destination: HubDestination) => void }) {
  const blocks: { destination: HubDestination; title: string; description: string; icon: string }[] = kind === 'organize' ? [
    { destination: 'review', title: 'Captures', description: 'Review, find, and organize your captures into folders.', icon: '▤' },
    { destination: 'canvas', title: 'Canvases', description: 'Open your saved canvases and think visually.', icon: '⌁' },
  ] : [
    { destination: 'schedule', title: 'Schedule', description: 'Plan actions before putting them on your calendar.', icon: '✓' },
    { destination: 'calendar', title: 'Calendar', description: 'See your dates, events, and commitments.', icon: '▦' },
  ]
  return <div className="page workspace-hub"><header className="page-header"><h1>{kind === 'organize' ? 'Organize' : 'Plan'}</h1></header><div className="workspace-hub-blocks">{blocks.map(block => <button type="button" key={block.destination} onClick={() => onOpen(block.destination)}><span className="workspace-hub-icon" aria-hidden="true">{block.icon}</span><span><strong>{block.title}</strong><small>{block.description}</small></span><span aria-hidden="true">→</span></button>)}</div></div>
}
