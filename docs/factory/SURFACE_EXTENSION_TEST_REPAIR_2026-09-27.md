# Surface extension test repair — 2026-09-27

## Scope

TASK-335 cumulatively repairs the tests left stale by the extensible application-surface registry. It does not change product code or accept the original feature; the prior review remains `CHANGES_REQUESTED`.

## Evidence

- `src/appSurfaceRegistry.test.tsx` still requires the four currently discovered builtin surfaces, but verifies ID and path uniqueness without fixing the registry size. The cardinality assertions use `new Set(values).size` explicitly, and a small regression demonstrates that the check distinguishes unique values from duplicate IDs and paths.
- `src/surfaces/surfaceRendering.test.tsx` composes the actual builtin surface definitions with a test-only `fixture-extension` at `/__test__/fixture-extension` and a separately simulated legitimate Schedule module at `/schedule`.
- The renderer assertion resolves and renders the extension with the canonical `state` and `update` callback; Schedule remains independently resolvable. Existing malformed-module, duplicate-ID, duplicate-path, fallback, and shell-override coverage remains in place.

The explicit `.size` correction removes reviewer ambiguity and improves matcher clarity/portability. It is not a claim that the original focused tests failed: the coordinator reproduced the original exact-head two-file, nine-test suite successfully under Vitest 5.0.1 at 02:49.

## Validation

- `pnpm exec vitest run src/appSurfaceRegistry.test.tsx src/surfaces/surfaceRendering.test.tsx --reporter verbose` — passed: 2 files, 10 tests.
  - `workspace surface rendering > renders a synthetic extension alongside builtins and a legitimate schedule module`
  - `workspace surface rendering > rejects malformed rendered modules and never resolves previews or factory projections`
  - `workspace surface rendering > only selects TSX modules that explicitly declare a surface export`
  - `application surface registry > discovers every existing hosted surface from separate modules`
  - `application surface registry > distinguishes unique surface ids and paths from duplicates by cardinality`
  - `application surface registry > keeps the main workspace as the safe fallback without assigning persistence to previews`
  - `application surface registry > allows a new module to join without editing a shared list`
  - `application surface registry > fails closed on duplicate ids and duplicate paths`
  - `application surface registry > fails closed on malformed modules and definitions`
  - `application surface registry > rejects attempts to override the application shell`
- `pnpm test` — passed: 63 files, 741 tests.
- `pnpm run build` — passed. Vite reported the existing chunk-size warning for a 693.13 kB minified JavaScript chunk.
- `pnpm run check:api` — passed.
- `git diff --check` — passed with no output.

`pnpm check` is intentionally not run; the runner owns that final shared-lock validation.
