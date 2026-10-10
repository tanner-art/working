/** Close the secondary menu without leaving keyboard focus in hidden content. */
export function closeMoreMenu(menu: HTMLDetailsElement | null, restoreFocus = false): boolean {
  if (!menu?.open) return false
  menu.open = false
  if (restoreFocus) menu.querySelector<HTMLElement>('summary')?.focus()
  return true
}

export function dismissMoreMenuOutside(menu: HTMLDetailsElement | null, target: EventTarget | null): boolean {
  if (!menu?.open || !(target instanceof Node) || menu.contains(target)) return false
  return closeMoreMenu(menu)
}
