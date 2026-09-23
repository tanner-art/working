#!/usr/bin/env python3
"""Small, local-only independent review lane for preserved runner records.

The review command is deliberately an explicit configuration contract.  It
must set ``read_only`` to true; this is an operator assertion, not a security
boundary.  The command receives a redacted packet as JSON on stdin and must
not be given credentials.  This prototype never talks to GitHub and never
approves, comments, merges, or changes a worktree.

Example config fragment::

    {"reviewers": {"claude": {"command": ["claude", "-p"],
                                "read_only": true}}}

The configured reviewer should additionally enforce a read-only sandbox or
read-only tool set.  A packet remains useful for manual review when that
configuration is absent or unsafe.
"""
import argparse
import json
import os
import pathlib
import re
import subprocess
import sys
import time


AGENTS = ("codex-a", "codex-b", "claude")


def reviewer_for(author):
    """Return the reviewer required by the independent-review policy."""
    if author in ("codex-a", "codex-b"):
        return "claude"
    if author == "claude":
        return "codex-a"
    raise ValueError("record has no supported author; cannot choose an independent reviewer")


def _record_author(record):
    value = record.get("agent", record.get("author"))
    if isinstance(value, dict):
        value = value.get("login") or value.get("name")
    return value


def _pr_url(record):
    for key in ("pr", "pr_url", "pull_request", "pull_request_url"):
        value = record.get(key)
        if isinstance(value, str) and value.startswith(("https://", "http://")):
            return value
    return None


def _commit(record):
    value = record.get("commit")
    return value if isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{7,128}", value) else None


def _safe_name(value):
    return re.sub(r"[^A-Za-z0-9_.-]", "_", value)


def packet_for(record, source):
    author = _record_author(record)
    pr_url = _pr_url(record)
    commit = _commit(record)
    if not isinstance(record.get("issue"), int):
        raise ValueError("record is missing an integer issue number")
    if not author:
        raise ValueError("record is missing its author/agent")
    if not pr_url:
        raise ValueError("record is missing a PR URL")
    if not commit:
        raise ValueError("record is missing a commit SHA")
    return {
        "kind": "threadline-independent-review",
        "issue": record["issue"],
        "pr_url": pr_url,
        "commit": commit,
        "authored_by": author,
        "reviewer": reviewer_for(author),
        "source_record": str(source),
        "limitations": [
            "Local packet only; no GitHub mutation is performed.",
            "Human review remains responsible for approval and merge.",
        ],
    }


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def _read_only_config(config):
    command = config.get("command")
    if not isinstance(command, list) or not command or any(not isinstance(x, str) or not x for x in command):
        raise ValueError("reviewer command must be a non-empty list of strings")
    if config.get("read_only") is not True:
        raise ValueError("reviewer command is not declared read-only; set read_only=true after auditing it")
    return command


def _report_path(state, packet):
    return state / ("review-{}-{}.json".format(packet["issue"], _safe_name(packet["commit"])))


def _run_one(packet, reviewer_config, report_path, state, timeout):
    command = _read_only_config(reviewer_config)
    environment = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
    started = time.time()
    try:
        result = subprocess.run(
            command,
            cwd=str(state),
            env=environment,
            input=json.dumps(packet) + "\n",
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
        report = {
            "kind": packet["kind"], "status": "completed" if result.returncode == 0 else "failed",
            "issue": packet["issue"], "commit": packet["commit"], "reviewer": packet["reviewer"],
            "pr_url": packet["pr_url"], "returncode": result.returncode,
            "output": result.stdout[-20000:], "time": started,
        }
        _write_json(report_path, report)
        return report
    except Exception as error:
        _write_json(report_path, {
            "kind": packet["kind"], "status": "failed", "issue": packet["issue"],
            "commit": packet["commit"], "reviewer": packet["reviewer"], "pr_url": packet["pr_url"],
            "error": str(error), "time": started,
        })
        raise


def find_records(state):
    for path in sorted(state.glob("issue-*.json")):
        try:
            record = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(record, dict) and record.get("status") == "review":
            yield path, record


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    config = json.loads(pathlib.Path(args.config).read_text())
    state = pathlib.Path(config["state"]).resolve()
    state.mkdir(parents=True, exist_ok=True) if not args.dry_run else None
    reviewer_configs = config.get("reviewers", {})
    candidates = []
    for source, record in find_records(state):
        try:
            packet = packet_for(record, source)
            report_path = _report_path(state, packet)
            if report_path.exists():
                continue
            candidates.append((source, packet, report_path))
        except ValueError as error:
            if not args.dry_run:
                _write_json(state / (source.stem + ".review-packet.json"), {
                    "kind": "threadline-independent-review", "status": "manual-review-required",
                    "source_record": str(source), "error": str(error),
                })
            print(json.dumps({"record": str(source), "error": str(error)}), file=sys.stderr)
    if not candidates:
        return 0
    source, packet, report_path = candidates[0]
    packet_path = state / ("review-{}-{}.packet.json".format(packet["issue"], _safe_name(packet["commit"])))
    if not args.dry_run:
        _write_json(packet_path, packet)
    print(json.dumps({"packet": str(packet_path), "reviewer": packet["reviewer"], "issue": packet["issue"],
                      "commit": packet["commit"], "dry_run": args.dry_run}))
    if args.dry_run or not args.once:
        return 0
    reviewer_config = reviewer_configs.get(packet["reviewer"])
    if not isinstance(reviewer_config, dict):
        error = "no explicitly configured reviewer command for {}".format(packet["reviewer"])
        _write_json(report_path, {"kind": packet["kind"], "status": "manual-review-required", "error": error,
                                  "issue": packet["issue"], "commit": packet["commit"]})
        raise SystemExit(error)
    try:
        report = _run_one(packet, reviewer_config, report_path, state, int(config.get("review_timeout", 600)))
        print(json.dumps({"report": str(report_path), "status": report["status"]}))
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        if not report_path.exists():
            _write_json(report_path, {"kind": packet["kind"], "status": "manual-review-required", "error": str(error),
                                      "issue": packet["issue"], "commit": packet["commit"]})
        raise SystemExit("review stopped: {}; packet preserved at {}".format(error, packet_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
