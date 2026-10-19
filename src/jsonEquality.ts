/** Compare JSON persistence values, not object insertion order. JSON transport
 * omits undefined object fields; array order (including audit history) is sacred.
 * This is not validation: callers must still validate schemas and provenance. */
export function stableJson(value: unknown): string | undefined {
  return JSON.stringify(value, (_key, item: unknown) => {
    if (!item || typeof item !== 'object' || Array.isArray(item)) return item
    const record = item as Record<string, unknown>
    return Object.fromEntries(Object.keys(record).sort().map(key => [key, record[key]]))
  })
}

export function jsonEqual(left: unknown, right: unknown): boolean {
  return stableJson(left) === stableJson(right)
}
