import { isCanvasBank } from './canvasBank'
import type { CanvasBank, CanvasRecord } from './domain'

const copy = <T>(value: T): T => structuredClone(value)
const equal = (left: unknown, right: unknown) => JSON.stringify(left) === JSON.stringify(right)

export function mergeCanvasBanks(accountValue: CanvasBank, deviceValue: CanvasBank): { merged: CanvasBank; added: number; duplicates: number } {
  if (!isCanvasBank(accountValue) || !isCanvasBank(deviceValue)) throw Error('Merge stopped: a canvas bank is invalid. Both sources are untouched.')
  const canvases = copy(accountValue.canvases)
  let added = 0
  let duplicates = 0
  for (const device of deviceValue.canvases) {
    const account = canvases.find(item => item.id === device.id)
    if (!account) { canvases.push(copy(device)); added++; continue }
    if (account.title !== device.title || !equal(account.elements, device.elements)) {
      throw Error(`Merge stopped: canvas identity ${device.id} has different contents on each device. Both sources are untouched.`)
    }
    const merged: CanvasRecord = {
      ...copy(account),
      createdAt: Date.parse(account.createdAt) <= Date.parse(device.createdAt) ? account.createdAt : device.createdAt,
      updatedAt: Date.parse(account.updatedAt) >= Date.parse(device.updatedAt) ? account.updatedAt : device.updatedAt,
      // The account is the destination, so its current view remains authoritative.
      viewport: copy(account.viewport),
    }
    canvases[canvases.indexOf(account)] = merged
    duplicates++
  }
  return { merged: { canvases }, added, duplicates }
}
