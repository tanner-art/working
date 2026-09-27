# Cross-review adapter

The runner performs an exact-commit, read-only independent review. Claude uses
its existing `Read,Glob,Grep` adapter. Codex is invoked as `codex exec` with
only its configured model and allowlisted model/reasoning config retained,
while its inherited sandbox,
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

## Validation receipt (2026-09-27)

The two normal CI entry points were executed without a custom `PYTHONPATH`:

```text
python3 -m unittest discover -s scripts/factory_registry
python3 -m unittest discover -s scripts/runner
```

Both returned nonzero only because this provider sandbox prohibits binding a
loopback TCP socket. The genuine summaries were:

```text
scripts/factory_registry: exit 1; Ran 249 tests in 5.327s;
FAILED (errors=29). Every error was ProjectionTransportTest setup failing
ThreadingHTTPServer(("127.0.0.1", 0), ...) with PermissionError:
[Errno 1] Operation not permitted.

scripts/runner: exit 1; Ran 298 tests in 1.985s;
FAILED (errors=1). The sole error was HttpRouteTests.setUpClass failing
ThreadingHTTPServer(("127.0.0.1", 0), ...) with PermissionError:
[Errno 1] Operation not permitted.
```

Focused normal-discovery checks for the changed review paths passed:

```text
python3 -m unittest discover -s scripts/factory_registry -p 'test_review_integrity.py'
# exit 0; Ran 11 tests in 0.001s; OK

python3 -m unittest discover -s scripts/runner -p 'test_runner.py'
# exit 0; Ran 50 tests in 0.612s; OK

python3 -m unittest discover -s scripts/runner -p 'test_registry_control.py'
# exit 0; Ran 28 tests in 0.674s; OK

python3 -m unittest discover -s scripts/runner -p 'test_review_queue.py'
# exit 0; Ran 4 tests in 0.026s; OK
```

The normal suites import through their standard discovery paths. The sandbox
limitation does not turn their server-dependent failures green; an environment
permitting loopback test binds must rerun them for a fully passing receipt.

This adapter does not implement queue/WIP progression or readiness repair;
those remain follow-on work.
