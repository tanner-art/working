# Cross-review adapter

The runner performs an exact-commit, read-only independent review. Claude uses
its existing `Read,Glob,Grep` adapter. Codex is invoked as `codex exec` with
the configured model/config flags retained, while its inherited sandbox,
approval, JSON, and schema controls are removed and replaced with:

```text
--sandbox read-only --json --output-schema /absolute/review-packet/review-verdict-schema.json -
```

The schema is materialized once in the external immutable review packet, never
in the implementation checkout. Codex JSONL progress is not a verdict: one
successful final `agent_message` and one final completed turn must carry the
exact commit, base commit, and contract digest structured verdict. Errors,
failed turns, malformed JSON, duplicate keys, and conflicting final messages
fail closed.

The tested commands are:

```text
python3 -m unittest discover -s scripts/factory_registry
python3 -m unittest discover -s scripts/runner
```

This adapter does not implement queue/WIP progression or readiness repair;
those remain follow-on work.
