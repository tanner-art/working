import type { ReactNode } from 'react'

/**
 * The narrow-screen Canvas command strip deliberately owns no canvas state or
 * persistence. It gives the Canvas surface a compact, named control boundary
 * while the existing Canvas workspace continues to own edits and save queues.
 */
export function MobileCanvasToolbar({ primary, secondary }: { primary: ReactNode; secondary: ReactNode }) {
  return <div className="canvas-mobile-toolbar" aria-label="Canvas tools">
    <div className="canvas-mobile-primary">{primary}</div>
    <details className="canvas-mobile-more">
      <summary aria-label="More canvas tools">•••</summary>
      <div className="canvas-mobile-more-menu">{secondary}</div>
    </details>
  </div>
}
