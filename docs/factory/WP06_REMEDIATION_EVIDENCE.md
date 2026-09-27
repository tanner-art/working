# WP06 remediation evidence — TASK-325 / issue #271

## Scope and operational record

This is cumulative code-and-test remediation for original TASK-181 / review TASK-182,
not a replacement feature or a rewritten historical verdict. The owner authorized the
first overnight Factory operations from 2026-09-26T23:40Z through 07:40Z, including
bounded feature work, repairs, and independent reviews. TASK-179 became DONE only
after independent Claude TASK-213 approved exact merged PR #209 head
`3b620b91fff3cc27d0b1a786f73d95608ea4833e`. The historical TASK-180 failed outcome
is preserved. TASK-181 was claimed at 00:55:10Z in the explicit original-feature
allowlist 173/174/181/182 at revision 6356. TASK-182 requested changes at 01:06:15Z
because the referenced plan, targeted regression tests, and physical-phone proof were
missing.

This record supplies the plan and executable code/test evidence only. It does not
change those historical records, claim deployment, or claim physical-device acceptance.

## WP06 plan excerpt

Product behavior: tap selection, drag-selected movement, finger-safe resize,
empty-canvas pan, pinch zoom, outside deselect, and complete gesture arbitration
without text-edit or undo regressions.

Acceptance: one committed drag creates one undo step; resize target is at least 44 by
44 CSS pixels; two pointers safely cancel or transition a one-pointer gesture;
textarea remains reliable; pointer cancellation/loss commits no stale movement; pan
and zoom never alter content coordinates; pen, lasso, connection, and refinement
regressions remain covered. Persistence is through existing Canvas
repository/session interfaces only.

Observable full completion additionally requires select → move → resize → pan → pinch
→ deselect on a physical phone and persistence after reopen.

## Remediation and focused test matrix

| Concern | Production seam | Executable evidence |
| --- | --- | --- |
| Latest pinch preview commits before React rerender | `Canvas` uses `canvasInteraction`'s mutable pinch interaction to render state and synchronously commit the last preview. | `canvasInteraction.test.ts`: two previews then immediate commit returns the second preview. |
| Resize from externally entered edit mode | `Canvas` routes resize pointer-down through `reduceResizePointerDown`, which mirrors visible edit state into `reduceCanvasGesture`. | `canvasInteraction.test.ts`: no-hold edit-mode bridge enters `resizing` and emits `begin-resize`. |
| Finger-safe target | `Canvas` provides the tested 44px resize custom property; `.canvas-resize-handle` uses it for both dimensions. | `canvasInteraction.test.ts`: `CANVAS_RESIZE_TARGET_SIZE === 44`. |
| One undo per completed drag | Gesture reducer emits one `commit-move`; Canvas commits only on that effect. | `canvasInteraction.test.ts`: completed drag is committed once through `canvasHistory`. |
| Cancellation / stale commit | Gesture reducer returns idle and only `cancel` for a cancelled pinch. | `canvasInteraction.test.ts`; existing `canvasGestures.test.ts` cancellation regression. |
| Coordinate isolation | Viewport pan/zoom operate on viewport values, not elements. | `canvasInteraction.test.ts`; existing `canvasViewport.test.ts`. |
| Textarea, pen, lasso, connection, refinement | Existing production reducers and persistence helpers remain unchanged. | `canvasGestures.test.ts`, `canvasStrokes.test.ts`, `canvasConnectionHandles.test.ts`, and repository/history coverage. |

Focused command run for this remediation:

```text
pnpm exec vitest run src/canvasInteraction.test.ts src/canvasGestures.test.ts src/canvasGeometry.test.ts
```

## Still pending

No physical-phone test was performed for this remediation. The full interaction flow
and persistence-after-reopen observation remain explicitly pending and must be
performed without altering existing live data. Browser/unit evidence above is not a
substitute for physical-phone acceptance.
