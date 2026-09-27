# Follow-up review source repair — 2026-09-27

At paused revision 12832, the TASK347 follow-up registration derived its GitHub
source reference from the task identifier. Its validated source issue was 307,
so the runner correctly rejected the mismatched claim and the immutable
BLOCKED evidence remains authoritative.

TASK-348 changes only future follow-up review registration. A validated
follow-up specification must provide a positive GitHub `source_ref`; it is
preserved in provider diagnostics and persisted as the package's exact
`github_issue` source reference. The task identifier is not a source fallback.
Missing, malformed, or spec/diagnostic-inconsistent references fail closed.

This does not modify TASK347, its input, past registration, review outcome, or
claim evidence. A later review must be newly registered through the normal
paused-revision, provenance, dependency, exclusivity, canary, and independent
review gates.
