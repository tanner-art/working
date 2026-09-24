# RISK-002 — Factory Python CI coverage

## Lane

PLATFORM: CI and Factory infrastructure.

## Risk

GitHub CI previously ran only `pnpm check`. The registry, capability scheduler,
live observer, and legacy runner are Python, so a pull request could break the
Factory control plane while the required check remained green.

## Bounded remediation

- Pin the CI interpreter through `.github/python-version`.
- Declare the Factory CI dependency set in a hash-enforced requirements file.
  It is intentionally empty because every current Factory suite uses only the
  Python standard library.
- Run both Python discovery roots before the existing `pnpm check` step:
  - `scripts/factory_registry`: registry, scheduler, and live observation;
  - `scripts/runner`: installed-runner behavior and safeguards.
- Preserve `pnpm check` as the app, build, and API gate.

## Failure proof

Before completion, create a temporary intentionally failing test inside the
Factory registry discovery root, run the exact CI discovery command, verify a
non-zero exit with the deliberate assertion identified, then remove the probe
and rerun the complete suites successfully. The failure probe must never be
committed.

## Authority boundary

This change only validates code. It adds no registry cutover, lease, claim,
worker launch, service-control, queue mutation, or live-dispatch authority.

## Acceptance criteria

- GitHub pushes and pull requests install the exact declared Python runtime and
  deterministic dependency set.
- Registry, scheduler, live-observer, and legacy-runner Python tests run in CI.
- A controlled failing test proves the Python CI command fails closed.
- The controlled failure is removed and all Python suites pass.
- Existing `pnpm check` remains present and passes.
- Independent ASSURANCE review approves the change before push.

## Local validation evidence

- Controlled failure: a temporary `test_ci_failure_probe.py` containing one
  deliberate failing assertion was placed under `scripts/factory_registry`.
  The exact discovery pattern ran 60 tests, reported
  `RISK-002 intentional CI failure probe`, and exited non-zero. The file was
  then removed and is not part of this change.
- Restored Factory registry/scheduler/live-observer suite: 59 tests passed.
- Restored legacy Factory runner suite: 208 tests passed.
- Hash-enforced dependency installation accepted the intentionally empty
  standard-library-only requirements file.
- Existing `pnpm check`: 649 tests, production build, and API typecheck passed.
- Workflow YAML and repository diff checks passed.
