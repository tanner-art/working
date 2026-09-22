import type { CanvasElement } from './domain'
import { canvasSize } from './canvasGeometry'

export interface CanvasBranch {
  elements: CanvasElement[]
  childId: string
  arrowId: string
}

const CHILD_SIZE = { width: 190, height: 100 }
const GAP = { x: 72, y: 48 }

function overlaps(a: CanvasElement, b: CanvasElement): boolean {
  const aSize = canvasSize(a), bSize = canvasSize(b)
  return a.x < b.x + bSize.width && a.x + aSize.width > b.x &&
    a.y < b.y + bSize.height && a.y + aSize.height > b.y
}

// Branching is intentionally canvas-only. It adds a normal text block and a visual
// connection in one immutable next snapshot; callers commit that snapshot once.
export function branchCanvasChild(
  elements: CanvasElement[],
  parentId: string,
  nextId: () => string = () => crypto.randomUUID(),
): CanvasBranch | undefined {
  const parent = elements.find(item => item.id === parentId)
  if (!parent || parent.type === 'arrow') return undefined

  const parentSize = canvasSize(parent)
  let child: CanvasElement | undefined
  for (let column = 0; column < 24 && !child; column += 1) {
    for (let row = 0; row < 24 && !child; row += 1) {
      const candidate: CanvasElement = {
        id: '', type: 'text',
        x: parent.x + parentSize.width + GAP.x + column * (CHILD_SIZE.width + GAP.x),
        y: parent.y + row * (CHILD_SIZE.height + GAP.y),
        ...CHILD_SIZE, text: 'New thought',
      }
      if (!elements.some(item => item.type !== 'arrow' && overlaps(candidate, item))) child = candidate
    }
  }
  if (!child) return undefined

  const childId = nextId(), arrowId = nextId()
  if (!childId || !arrowId || childId === arrowId || elements.some(item => item.id === childId || item.id === arrowId)) return undefined
  child.id = childId
  const arrow: CanvasElement = { id: arrowId, type: 'arrow', x: 0, y: 0, fromId: parent.id, toId: childId }
  return { elements: [...elements, child, arrow], childId, arrowId }
}
