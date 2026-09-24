# RISK-004 — Pin core JavaScript dependencies

## Lane

PLATFORM: dependency and build reproducibility.

## Risk

Every direct JavaScript dependency allowed a later version through either the
`latest` tag or a caret range. Although `pnpm-lock.yaml` made the present
checkout reproducible, a deliberate lockfile refresh could silently select new
major or minor code without an explicit dependency-upgrade review.

## Bounded remediation

Pin each direct dependency and development dependency to the exact version that
was already resolved in `pnpm-lock.yaml` and installed in `node_modules`:

| Package | Exact version |
| --- | --- |
| `@supabase/supabase-js` | `2.116.0` |
| `@vercel/firewall` | `1.2.5` |
| `@vercel/oidc` | `3.8.9` |
| `@vitejs/plugin-react` | `6.1.1` |
| `react` | `19.3.0` |
| `react-dom` | `19.3.0` |
| `typescript` | `7.0.2` |
| `vite` | `8.3.0` |
| `@types/react` | `19.3.0` |
| `@types/react-dom` | `19.3.0` |
| `vitest` | `5.0.1` |

Only the root `package.json` and `pnpm-lock.yaml` are core dependency manifests
in this repository. The lockfile's resolved package versions and integrity
records are unchanged; only its root specifiers now match the exact manifest
versions. No package was added, removed, or upgraded.

## Validation evidence

- `pnpm install --frozen-lockfile --offline` passed and resolved the same 11
  direct versions without downloading packages.
- No `latest`, caret, tilde, or wildcard direct version remains in
  `package.json`.
- `pnpm check` passed 649 tests, the production build, and API typecheck.
- Factory registry/scheduler/live-observer suite passed 59 tests.
- Legacy Factory runner suite passed 208 tests.
- Repository diff check passed.

## Limitations

Transitive versions remain governed by `pnpm-lock.yaml` and its integrity
records. Future upgrades should be explicit, reviewed changes to both manifest
and lockfile. This task does not add automated dependency updates or change any
Factory dispatch authority.
