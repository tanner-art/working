type Props = { status: string; error: string; deviceOnly: number; count: number; details?: boolean }

/** Routine sync/backup information belongs in Data settings, not above every page. */
export function AccountSyncNotice({ status, error, deviceOnly, count, details = false }: Props) {
  const needsAttention = deviceOnly > 0 || deviceOnly === -1
  const message = error || (details || status !== 'Synced with your account.' ? status : '')
  if (!message && !needsAttention && !details) return null
  return <div className="sync-status">
    {message && <p role={error ? 'alert' : 'status'}>{message}{details && ` · ${count} saved thoughts`}</p>}
    {(needsAttention || (details && deviceOnly === -2)) && <details>
      <summary>{deviceOnly === -2 ? 'Device backup kept' : deviceOnly === -1 ? 'Device backup needs attention' : `${deviceOnly} device-only capture${deviceOnly === 1 ? '' : 's'} preserved`}</summary>
      <p>{deviceOnly === -2 ? 'This phone or browser has a different local backup. That alone does not mean account sync failed. ' : ''}Your local copy has not been deleted. To review or combine it, open Settings → Data → Return to this device’s local data.</p>
    </details>}
  </div>
}
