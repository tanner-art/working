# Continuous bounded-run telemetry

This optional runner path keeps real provider observations fresh during a bounded Registry run. It has no live authority by itself: normal Registry activation, kill switch, lease, package allowlist, review independence, and exact-commit checks still apply.

## Configuration

`capacity_collectors.<worker>` remains the Codex app-server collector. Add an explicitly verified alias only when the target Registry worker already has the same hashed `capacity_pool` in its provider diagnostics:

```json
{
  "capacity_collectors": {
    "codex-b": {
      "executable": "/absolute/path/to/codex",
      "codex_home": "/absolute/path/to/codex-home",
      "shared_account_aliases": ["orchestra-agent-b"]
    }
  },
  "claude_health_probe": {"worker_id": "claude", "timeout_seconds": 20, "cadence_seconds": 60}
}
```

The collector reads Codex account identity and rate limits once, compares that identity to each alias's existing Registry binding, and emits the same sampled windows and timestamps for the alias. A missing or mismatched binding fails closed. It does not start a Codex model turn or create a separate `usage.json` account record for Orchestra.

Claude uses the configured reviewed Keychain-wrapper command. Its bounded probe has a fixed source-free prompt, JSON output, no tools, and no permission prompts. It records only health/auth/invocation/limit fields; provider output and credentials are not published. `cadence_seconds` is 60 by default (1–900); existing fresh Registry evidence suppresses concurrent lane polls. The runner also skips this probe whenever Claude has an active Registry lease and uses real invocation evidence instead.

## Activation

1. Register each worker and its approved capacity mode/scopes, including the verified hashed `capacity_pool` for a shared Codex account.
2. Add the configuration above to the immutable bounded-run configuration and validate it through the normal prepare/activation process.
3. Start the bounded runner lanes. They coordinate through the state-directory observation lock, append Registry observations without worker upserts, and publish the identical records to existing `usage.json`.

Failed probes and explicit rate-limit, exhaustion, or throttling text become restrictive provider-signal observations. Missing, stale, malformed, concurrent-skipped, or failed evidence never becomes a healthy timestamp.
