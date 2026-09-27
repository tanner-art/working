# Surface render boundary repair

TASK-323 repairs the WP11 composition boundary without adding a product surface.

## Future workspace module contract

WP02 may add `src/surfaces/schedule.tsx` and `src/surfaces/ScheduleView.tsx` without editing `App.tsx`:

```tsx
import { defineAppSurface, type WorkspaceSurfaceProps } from '../appSurfaceRegistry'
import { ScheduleView } from './ScheduleView'

export const surface = defineAppSurface({
  id: 'schedule', path: '/schedule', persistence: 'workspace',
})

export function WorkspaceSurface({ state, update }: WorkspaceSurfaceProps) {
  return <ScheduleView state={state} onUpdate={update} />
}
```

`WorkspaceSurface` receives the already-loaded canonical `AppState` and its functional updater. It must not create a second store or persist independently. The App shell reaches this renderer only after the existing account/session, loading-error, and clear-data guards. Metadata-only `*.surface.ts` files remain supported. A `*.tsx` file is considered a surface only when it explicitly exports `surface`; ordinary support components such as `canvas.tsx` remain excluded.

The registry rejects malformed module shapes, malformed definitions, duplicate IDs/paths, and application-shell overrides. Renderers are resolved only for `persistence: 'workspace'`; `none` previews and `factory-projection` routes cannot receive workspace state through this boundary.

## Limits

This introduces no Schedule, Action, Reminder, or Commitment feature, navigation item, authorization policy, or route-side loader. It intentionally does not make a registered workspace route public before the existing beta/account gating accepts it. A future surface owns its own UI and must stay within the supplied canonical state/update contract.
