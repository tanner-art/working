# Surface extension test repair — 2026-09-27

## Scope

TASK-331 repairs tests left stale by the extensible application-surface registry. It does not change product code or accept the original feature.

## Evidence

- `src/appSurfaceRegistry.test.tsx` still requires the four currently discovered builtin surfaces, but verifies ID and path uniqueness without fixing the registry size.
- `src/surfaces/surfaceRendering.test.tsx` composes the actual builtin surface definitions with a test-only `fixture-extension` at `/__test__/fixture-extension` and a separately simulated legitimate Schedule module at `/schedule`.
- The renderer assertion resolves and renders the extension with the canonical `state` and `update` callback; Schedule remains independently resolvable. Existing malformed-module, duplicate-ID, duplicate-path, fallback, and shell-override coverage remains in place.

## Validation

- `pnpm exec vitest run src/appSurfaceRegistry.test.tsx src/surfaces/surfaceRendering.test.tsx` — passed: 2 files, 9 tests.
- `pnpm test` — passed: 63 files, 740 tests.
- `pnpm run build` — passed. Vite reported its pre-existing-size-style warning for a 693.13 kB JavaScript chunk after minification.
- `pnpm run check:api` — passed.
- `git diff --check` — passed with no output.

`pnpm check` was not run; the runner owns that final shared-lock validation.
