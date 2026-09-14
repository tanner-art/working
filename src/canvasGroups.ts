import type { CanvasElement } from './domain'
import { canvasSize } from './canvasGeometry'

export function canvasGroups(elements: CanvasElement[]) {
  return elements.filter(item => item.type === 'container')
}

export function setCanvasGroup(elements: CanvasElement[], memberId: string, groupId?: string): CanvasElement[] {
  const member = elements.find(item => item.id === memberId)
  const group = groupId ? elements.find(item => item.id === groupId) : undefined
  if (!member || member.type !== 'text' || (groupId && (!group || group.type !== 'container'))) return elements
  if (member.groupId === groupId) return elements
  return elements.map(item => item.id === memberId ? { ...item, groupId } : item)
}

export function attachBlocksInside(elements: CanvasElement[], groupId: string): CanvasElement[] {
  const group = elements.find(item => item.id === groupId)
  if (!group || group.type !== 'container') return elements
  const { width, height } = canvasSize(group)
  return elements.map(item => item.type === 'text' && item.x >= group.x && item.y >= group.y &&
    item.x + canvasSize(item).width <= group.x + width && item.y + canvasSize(item).height <= group.y + height
    ? { ...item, groupId } : item)
}

export function moveCanvasNode(elements: CanvasElement[], id: string, x: number, y: number): CanvasElement[] {
  const node = elements.find(item => item.id === id)
  if (!node || node.type === 'arrow' || !Number.isFinite(x) || !Number.isFinite(y)) return elements
  const dx = x - node.x, dy = y - node.y
  if (dx === 0 && dy === 0) return elements
  return elements.map(item => item.id === id || (node.type === 'container' && item.groupId === id)
    ? { ...item, x: item.x + dx, y: item.y + dy } : item)
}

export function removeCanvasNode(elements: CanvasElement[], id: string): CanvasElement[] {
  return elements.filter(item => item.id !== id && item.fromId !== id && item.toId !== id)
    .map(item => item.groupId === id ? { ...item, groupId: undefined } : item)
}
