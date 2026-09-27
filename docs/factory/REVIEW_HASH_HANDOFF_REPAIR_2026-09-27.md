# Review hash handoff repair — 2026-09-27

TASK-333 clarifies the review-verdict identity without changing review outcome
semantics or packet validation. `contract_sha256` is the canonical digest of
the semantic contract object. It is the only contract hash a reviewer returns
in a verdict.

The packet manifest SHA-256 and the formatted `contract.json` file SHA-256
remain immutable packet-integrity values only. They are explicitly presented
as distinct from the expected verdict identity, and reviewers are not asked to
calculate or copy either one. Strict parsing continues to reject any verdict
whose head, base, or canonical contract digest differs from the recorded
review input.
