/** Coalesce visual previews only. Authoritative gesture refs still update on
 * every event, so pointer-up never waits for a frame to commit the latest value. */
export function createCanvasPreviewFrame(request: (render: () => void) => number, cancel: (id: number) => void) {
  let frame: number | undefined
  let latest: (() => void) | undefined
  return {
    schedule(render: () => void) {
      latest = render
      if (frame !== undefined) return
      frame = request(() => { frame = undefined; const current = latest; latest = undefined; current?.() })
    },
    cancel() {
      if (frame !== undefined) cancel(frame)
      frame = undefined; latest = undefined
    },
  }
}
