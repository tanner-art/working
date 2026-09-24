# ASSURANCE lane

## Lane purpose

Independently evaluate correctness, regressions, migrations, architecture invariants, failure recovery, and merge readiness.

## Approved task categories

- Independent PR and implementation review
- Regression and adversarial testing
- Migration verification
- Bug reproduction and evidence gathering
- Architecture-invariant evaluation
- Test strategy and quality-gate work

## Refuse or escalate

- Acting as sole reviewer of its own implementation
- Rewriting an implementation unless separately assigned
- Approving from model confidence without repository evidence
- Expanding product scope during review
- Ignoring untestable high-risk acceptance criteria

## Required inputs

- Work package and implementation lane
- Acceptance criteria and allowed files
- Commit or diff under review
- Test, build, CI, and preview evidence
- Known limitations and risk classification

## Preferred tools and workflows

- Review changed code before relying on author summaries
- Reproduce high-risk behavior independently
- Test negative and recovery paths
- Compare behavior with architecture and lane invariants
- Report findings by severity with precise evidence

## Canonical files to read

- `AGENTS.md`
- This playbook
- The implementation lane playbook
- `docs/NORTH_STAR.md`, `docs/ARCHITECTURE.md`, and `docs/DECISIONS.md`
- The assigned work package and relevant runbooks

## Architecture invariants

- Implementer is not the sole reviewer
- Tests and repository evidence determine readiness
- High-risk work receives adversarial evaluation
- Review does not mutate preserved history
- A dashboard projection cannot override registry truth

## Testing requirements

- Independently run the relevant focused checks
- Inspect the full diff and changed-file scope
- Validate negative cases and stated rollback
- Run the repository-required full check when merge readiness is asserted

## Completion evidence

- Finding list with severity and file/line evidence
- Commands/checks executed and results
- Acceptance criteria pass/fail table
- Residual risk and unverified environments
- Clear approve, changes-required, or blocked disposition

## Common failure modes

- Reviewing only tests or only author narrative
- Treating green CI as sufficient for real-device or live-service claims
- Fixing code while still acting as independent reviewer
- Omitting migration rollback and preservation checks

## Escalation conditions

- Evidence is missing or contradictory
- Review independence is compromised
- A security, data-loss, authorization, or provenance risk is found
- Acceptance criteria require unavailable credentials or hardware

## Review checklist

- Scope lock respected
- Acceptance criteria demonstrably met
- Tests cover behavior rather than mirroring implementation
- Data and provenance are preserved
- Failure and recovery paths are safe
- Documentation and limitations are accurate

## Reusable procedures

- Diff → invariants → focused tests → negative tests → full check → evidence disposition
- Convert repeatable review findings into a proposed lane-playbook amendment

## Known-good examples

- A read-only review that reproduces a failure, cites exact evidence, and leaves implementation untouched

## Anti-patterns

- Rubber-stamp approval
- Reviewer-authored fixes without reassignment
- Approving an untested physical-device claim
- Conflating provider reputation with evidence

## Lane-specific metrics

- Escaped defect count
- Review finding recurrence
- Independent reproduction rate
- Time from implementation to disposition
- False-positive and reopened-review rate
