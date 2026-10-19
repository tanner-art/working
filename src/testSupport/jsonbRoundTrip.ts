/** Simulate JSON transport and jsonb object-key reordering, never array sorting.
 * Independent of the production comparator so tests cannot mask its mistakes. */
export function jsonbRoundTrip<T>(value: T): T {
  return JSON.parse(JSON.stringify(value, (_key, item: unknown) => {
    if (!item || typeof item !== 'object' || Array.isArray(item)) return item
    const record = item as Record<string, unknown>
    return Object.fromEntries(Object.keys(record).sort((a, b) => a.length - b.length || (a < b ? -1 : a > b ? 1 : 0))
      .map(key => [key, record[key]]))
  })) as T
}
