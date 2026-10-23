/** Restore focus only to a connected, visible part of the resumed app. */
export function findWorkspaceReturnFocusTarget(root: ParentNode): HTMLElement | null {
  for (const selector of [
    '[role="dialog"][aria-modal="true"] .close-button',
    '.sidebar [aria-label="Search"]',
    '.sidebar .nav-item[aria-current="page"]',
    '.sidebar .nav-item',
  ]) {
    const target = root.querySelector<HTMLElement>(selector)
    if (target?.isConnected && !target.closest('[inert], [hidden]')) return target
  }
  return null
}
