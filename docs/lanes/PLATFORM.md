# PLATFORM lane

## Lane purpose

Build and maintain backend, persistence, authentication, APIs, integrations, deployment, and Factory orchestration infrastructure.

## Approved task categories

- Backend and API behavior
- Persistence and migrations
- Authentication and authorization implementation
- Infrastructure and integrations
- Orchestration, registry, scheduler, telemetry, and recovery

## Refuse or escalate

- Unbounded product feature design
- UI behavior not required by a platform acceptance criterion
- Destructive production operations without explicit authorization
- Security-policy weakening
- Provider-specific coupling presented as a permanent abstraction

## Required inputs

- Data and API contracts
- Migration and rollback behavior
- Security and tenancy invariants
- Failure modes and observability requirements
- Exact allowed files and environmental boundaries

## Preferred tools and workflows

- Contract-first implementation
- Transactional state changes and idempotent operations
- Read-only inventory before migration
- Feature flags or shadow mode before authority changes
- Failure injection for claims, network, auth, and recovery paths

## Canonical files to read

- `AGENTS.md`
- `docs/NORTH_STAR.md`
- `docs/ARCHITECTURE.md`
- `docs/DECISIONS.md`
- `scripts/runner/README.md` for Factory work
- The assigned work package and relevant runbooks

## Architecture invariants

- Central registry owns scheduling truth
- Provider/model data remains diagnostic
- Active claims are transactional leases
- Three active parent packages globally
- Stale/missing usage is constrained
- Orchestra retains at least 20% capacity
- Preserved work is never destructively normalized

## Testing requirements

- Contract and transaction tests
- Concurrent claim and lease-expiry tests where relevant
- Idempotency and rollback tests
- Security/authorization tests for exposed APIs
- Full repository check before completion

## Completion evidence

- Schema/API contract
- Migration and rollback notes
- Failure-injection results
- Test/build output
- Diff inspection, commit SHA, and review artifact

## Common failure modes

- Multiple sources of scheduling truth
- Retry overwriting prior attempt provenance
- Stale usage treated as zero usage
- Locks without expiry or ownership evidence
- Direct dashboard writes bypassing registry rules

## Escalation conditions

- Live credentials, billing, production flags, or destructive data operations are required
- Migration reconciliation has unexplained records
- Orchestra reserve would be breached
- Existing state cannot be represented without data loss

## Review checklist

- Transactions enforce stated invariants
- Adapter boundary permits another backend
- Operations are idempotent or have stable attempt identity
- Observability contains no secrets
- Rollback preserves provenance

## Reusable procedures

- Inventory → immutable snapshot → read-only import → reconciliation → shadow mode → controlled cutover
- Normalize failures at the boundary while retaining human detail

## Known-good examples

- An adapter behind a protocol with shared contract tests and no provider-specific eligibility rules

## Anti-patterns

- Backend-specific calls outside an adapter
- Mutating legacy sources during import
- Big-bang scheduler replacement
- Disabling TLS or clearing state to recover a worker

## Lane-specific metrics

- Claim collision rate
- Recovery success and time
- Provenance reconciliation count
- Heartbeat freshness
- Migration rollback success
- Security and tenancy failures
