"""Prepare and publish an exact-reviewed Git integration artifact.

This adapter does not own lifecycle state. The coordinator supplies an approval
read from the Registry, persists the prepared receipt there *before* publishing,
and records the returned publication receipt. Retrying publication with that same
receipt reconciles a crash after the remote accepted the push.

Validation argv and destination are trusted operator configuration, never model
output. Main/master are disabled by default and require two explicit policy
gates. Preparation only merges in a new detached worktree; it never changes a
checked-out branch. Failed worktrees are retained as diagnostic evidence.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import time
from typing import Any, Callable, Mapping
from urllib.parse import urlparse


class IntegrationError(RuntimeError):
    def __init__(self, code: str, evidence: Mapping[str, Any] | None = None):
        super().__init__(code)
        self.code = code
        self.evidence = dict(evidence or {})


@dataclass(frozen=True)
class ApprovalBinding:
    feature_id: str
    package_id: str
    implementation_commit: str
    implementation_base: str
    contract_sha256: str
    review_outcome_id: str
    review_attempt_id: str
    reviewer_worker_id: str
    implementer_worker_id: str
    reviewed_commit: str
    reviewed_base_commit: str
    pr_url: str
    reviewed_pr_url: str
    validation_commit: str
    validation_evidence_ids: tuple[str, ...]
    review_input_evidence_id: str
    approval_evidence_ids: tuple[str, ...]
    verdict: str = "APPROVED"


@dataclass(frozen=True)
class IntegrationPolicy:
    remote: str
    target_branch: str
    validation_commands: tuple[tuple[str, ...], ...]
    validation_timeout_seconds: int = 900
    git_timeout_seconds: int = 120
    allow_main: bool = False
    repository_policy_allows_main: bool = False


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode()).hexdigest()


def _approval_dict(approval: ApprovalBinding) -> dict[str, Any]:
    return json.loads(json.dumps(asdict(approval)))


def _seal(value: dict[str, Any]) -> dict[str, Any]:
    return {**value, "receipt_sha256": _digest(value)}


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run(argv: list[str], cwd: Path, timeout: int) -> dict[str, Any]:
    """No shell; timeouts terminate the whole subprocess group."""
    started = time.monotonic()
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_PAGER": "cat",
           "GIT_AUTHOR_NAME": "Threadline Factory", "GIT_AUTHOR_EMAIL": "factory@localhost",
           "GIT_COMMITTER_NAME": "Threadline Factory", "GIT_COMMITTER_EMAIL": "factory@localhost"}
    try:
        with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
            process = subprocess.Popen(argv, cwd=cwd, env=env, stdout=out, stderr=err,
                                       start_new_session=True)
            timed_out = False
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            streams = {}
            for name, stream in (("stdout", out), ("stderr", err)):
                stream.seek(0)
                digest = hashlib.sha256()
                tail = b""
                while chunk := stream.read(65536):
                    digest.update(chunk)
                    tail = (tail + chunk)[-16384:]
                streams[name] = tail.decode("utf-8", errors="replace")
                streams[name + "_sha256"] = digest.hexdigest()
    except OSError as error:
        return {"argv": argv, "returncode": None, "timed_out": False,
                "duration_seconds": round(time.monotonic() - started, 6),
                "execution_error": str(error)}
    return {"argv": argv, "returncode": process.returncode, "timed_out": timed_out,
            "duration_seconds": round(time.monotonic() - started, 6), **streams}


def _git(repo: Path, policy: IntegrationPolicy, *args: str, check: bool = True) -> dict[str, Any]:
    result = _run(["git", "--no-replace-objects", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false",
                   "-c", "merge.gpgSign=false", *args], repo, policy.git_timeout_seconds)
    if check and result["returncode"] != 0:
        raise IntegrationError("GIT_OPERATION_FAILED", result)
    return result


def _commit(repo: Path, policy: IntegrationPolicy, sha: str) -> str:
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", sha):
        raise IntegrationError("EXACT_COMMIT_REQUIRED")
    resolved = _git(repo, policy, "rev-parse", "--verify", sha + "^{commit}")["stdout"].strip()
    if resolved != sha:
        raise IntegrationError("EXACT_COMMIT_REQUIRED")
    return resolved


def _ancestor(repo: Path, policy: IntegrationPolicy, before: str, after: str) -> bool:
    result = _git(repo, policy, "merge-base", "--is-ancestor", before, after, check=False)
    if result["returncode"] not in (0, 1):
        raise IntegrationError("ANCESTRY_UNAVAILABLE", result)
    return result["returncode"] == 0


def _validate_inputs(repo: Path, approval: ApprovalBinding, policy: IntegrationPolicy) -> str:
    fields = asdict(approval)
    evidence_fields = ("validation_evidence_ids", "approval_evidence_ids")
    evidence_invalid = any(not isinstance(fields[name], (tuple, list)) or not fields[name]
                           or any(not isinstance(item, str) or not item.strip() for item in fields[name])
                           or len(set(fields[name])) != len(fields[name])
                           for name in evidence_fields)
    pr = urlparse(approval.pr_url)
    if (not all(isinstance(value, str) and value.strip()
                for name, value in fields.items() if name not in evidence_fields)
            or evidence_invalid
            or approval.verdict != "APPROVED"
            or approval.reviewed_commit != approval.implementation_commit
            or approval.reviewed_base_commit != approval.implementation_base
            or approval.reviewed_pr_url != approval.pr_url
            or approval.validation_commit != approval.implementation_commit
            or pr.scheme != "https" or not pr.hostname or pr.username or pr.password
            or not re.fullmatch(r"/[^/]+/[^/]+/pull/[1-9][0-9]*", pr.path)
            or approval.reviewer_worker_id == approval.implementer_worker_id
            or not re.fullmatch(r"[0-9a-f]{64}", approval.contract_sha256)):
        raise IntegrationError("EXACT_INDEPENDENT_APPROVAL_REQUIRED")
    if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", policy.remote)
            or not isinstance(policy.target_branch, str)
            or policy.target_branch.startswith("-")
            or _git(repo, policy, "check-ref-format", "refs/heads/" + policy.target_branch,
                    check=False)["returncode"] != 0):
        raise IntegrationError("INVALID_INTEGRATION_DESTINATION")
    if (policy.target_branch in ("main", "master")
            and not (policy.allow_main is True and policy.repository_policy_allows_main is True)):
        raise IntegrationError("MAIN_INTEGRATION_NOT_AUTHORIZED")
    if (not policy.validation_commands
            or any(not command or isinstance(command, (str, bytes))
                   or any(not isinstance(arg, str) or not arg or "\0" in arg for arg in command)
                   for command in policy.validation_commands)
            or type(policy.validation_timeout_seconds) is not int
            or not 1 <= policy.validation_timeout_seconds <= 7200
            or type(policy.git_timeout_seconds) is not int
            or not 1 <= policy.git_timeout_seconds <= 600):
        raise IntegrationError("TRUSTED_VALIDATION_CONFIGURATION_REQUIRED")
    _commit(repo, policy, approval.implementation_commit)
    _commit(repo, policy, approval.implementation_base)
    if not _ancestor(repo, policy, approval.implementation_base, approval.implementation_commit):
        raise IntegrationError("IMPLEMENTATION_BASE_NOT_ANCESTOR")
    # Bind the concrete push URL as well as its configured alias, preventing a
    # local remote-config change from silently changing the publication target.
    urls = _git(repo, policy, "remote", "get-url", "--push", "--all", policy.remote)["stdout"].splitlines()
    if len(urls) != 1:
        raise IntegrationError("ONE_PUSH_DESTINATION_REQUIRED")
    return urls[0]


def _remote_head(repo: Path, policy: IntegrationPolicy, destination: str) -> str:
    result = _git(repo, policy, "ls-remote", "--refs", "--", destination,
                  "refs/heads/" + policy.target_branch)
    lines = result["stdout"].splitlines()
    if len(lines) != 1 or len(lines[0].split()) != 2:
        raise IntegrationError("TARGET_BRANCH_UNAVAILABLE", result)
    sha, ref = lines[0].split()
    if ref != "refs/heads/" + policy.target_branch or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", sha):
        raise IntegrationError("TARGET_BRANCH_UNAVAILABLE", result)
    return sha


def _fetch_head(repo: Path, policy: IntegrationPolicy, destination: str) -> str:
    observed = _remote_head(repo, policy, destination)
    _git(repo, policy, "fetch", "--no-tags", "--no-write-fetch-head", "--", destination, observed)
    return _commit(repo, policy, observed)


@contextmanager
def _publication_lock(repo: Path, policy: IntegrationPolicy):
    common = Path(_git(repo, policy, "rev-parse", "--git-common-dir")["stdout"].strip())
    common = (repo / common).resolve() if not common.is_absolute() else common.resolve()
    with (common / "factory-integration.lock").open("a") as lock:
        # A lock serializes publishers sharing a clone; the remote CAS below
        # protects against independent clones and human pushes as well.
        deadline = time.monotonic() + policy.git_timeout_seconds
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError as error:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise IntegrationError("INTEGRATION_BUSY") from error
                time.sleep(min(0.05, remaining))
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def prepare_integration(
    repository: str | Path, approval: ApprovalBinding, policy: IntegrationPolicy, *,
    expected_target_sha: str, integration_id: str, workspace_parent: str | Path | None = None,
) -> dict[str, Any]:
    """Return validated candidate evidence; caller must persist it before publish."""
    repo = Path(repository).resolve()
    destination = _validate_inputs(repo, approval, policy)
    if not isinstance(integration_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,159}", integration_id):
        raise IntegrationError("INTEGRATION_ID_REQUIRED")
    _commit(repo, policy, expected_target_sha)
    actual = _fetch_head(repo, policy, destination)
    if actual != expected_target_sha:
        raise IntegrationError("TARGET_MOVED", {"expected_target_sha": expected_target_sha,
                                               "actual_target_sha": actual})
    if not _ancestor(repo, policy, approval.implementation_base, expected_target_sha):
        raise IntegrationError("IMPLEMENTATION_BASE_NOT_IN_TARGET")
    if _ancestor(repo, policy, approval.implementation_commit, expected_target_sha):
        raise IntegrationError("IMPLEMENTATION_ALREADY_IN_TARGET")
    container = Path(tempfile.mkdtemp(prefix="factory-integration-", dir=workspace_parent))
    workspace = container / "worktree"
    evidence: dict[str, Any] = {
        "schema_version": 1, "kind": "factory-integration-candidate",
        "integration_id": integration_id, "approval": _approval_dict(approval),
        "policy_sha256": _digest(asdict(policy)), "push_destination_sha256": _digest(destination),
        "target_branch": policy.target_branch, "target_before": expected_target_sha,
        "workspace": str(workspace), "prepared_at": _stamp(), "validation": [],
    }
    try:
        _git(repo, policy, "worktree", "add", "--detach", str(workspace), expected_target_sha)
        merge = _git(workspace, policy, "merge", "--no-ff", "--no-edit", "-m",
                     f"Integrate {approval.package_id} ({integration_id})", approval.implementation_commit,
                     check=False)
        evidence["merge"] = merge
        if merge["returncode"] != 0:
            evidence["conflicted_paths"] = _git(workspace, policy, "diff", "--name-only",
                                                 "--diff-filter=U")["stdout"].splitlines()
            raise IntegrationError("INTEGRATION_MERGE_FAILED", evidence)
        candidate = _git(workspace, policy, "rev-parse", "HEAD")["stdout"].strip()
        evidence["target_after"] = candidate
        for command in policy.validation_commands:
            result = _run(list(command), workspace, policy.validation_timeout_seconds)
            evidence["validation"].append({**result, "validated_commit": candidate})
            if result["returncode"] != 0:
                raise IntegrationError("INTEGRATION_VALIDATION_FAILED", evidence)
        if (_git(workspace, policy, "rev-parse", "HEAD")["stdout"].strip() != candidate
                or _git(workspace, policy, "status", "--porcelain")["stdout"].strip()):
            raise IntegrationError("VALIDATION_CHANGED_ARTIFACT", evidence)
        return _seal(evidence)
    except IntegrationError as error:
        if not error.evidence.get("workspace"):
            error.evidence = {**evidence, "failure": error.evidence}
        raise


def publish_integration(
    repository: str | Path, receipt: Mapping[str, Any], approval: ApprovalBinding,
    policy: IntegrationPolicy, *, before_publish: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Publish a persisted candidate with exact CAS, or reconcile a prior push.

    A force-with-lease is used only as compare-and-swap: the candidate must have
    the expected target as its exact first parent. Thus a successful CAS is
    always a fast-forward; no remote history is discarded. A moved target is
    re-prepared/revalidated by the coordinator, never force-replaced.
    """
    repo = Path(repository).resolve()
    destination = _validate_inputs(repo, approval, policy)
    value = dict(receipt)
    checksum = value.pop("receipt_sha256", None)
    if (checksum != _digest(value) or value.get("kind") != "factory-integration-candidate"
            or value.get("schema_version") != 1 or value.get("approval") != _approval_dict(approval)
            or value.get("policy_sha256") != _digest(asdict(policy))
            or value.get("push_destination_sha256") != _digest(destination)
            or value.get("target_branch") != policy.target_branch):
        raise IntegrationError("CANDIDATE_BINDING_MISMATCH")
    before = _commit(repo, policy, value.get("target_before"))
    candidate = _commit(repo, policy, value.get("target_after"))
    parents = _git(repo, policy, "rev-list", "--parents", "-n", "1", candidate)["stdout"].split()[1:]
    if parents != [before, approval.implementation_commit]:
        raise IntegrationError("CANDIDATE_PARENTS_MISMATCH")
    validations = value.get("validation", [])
    if (not isinstance(validations, list) or len(validations) != len(policy.validation_commands)
            or any(not isinstance(item, dict) or item.get("returncode") != 0
                   or item.get("timed_out") is not False
                   or item.get("validated_commit") != candidate
                   or item.get("argv") != list(command)
                   for item, command in zip(validations, policy.validation_commands))):
        raise IntegrationError("CANDIDATE_VALIDATION_MISSING")
    with _publication_lock(repo, policy):
        actual = _fetch_head(repo, policy, destination)
        if _ancestor(repo, policy, candidate, actual):
            return _publication_receipt(receipt, actual, "ALREADY_PUBLISHED", None)
        if actual != before:
            raise IntegrationError("TARGET_MOVED", {"expected_target_sha": before, "actual_target_sha": actual,
                                                   "candidate_receipt_sha256": checksum})
        if before_publish is not None:
            # The coordinator rechecks authoritative run identity, mode,
            # deadline and approval immediately before the only remote mutation.
            before_publish()
        ref = "refs/heads/" + policy.target_branch
        # Ambient Git settings must not broaden an exact-branch authorization
        # into publishing annotated tags or referenced submodule repositories.
        pushed = _git(repo, policy, "push", "--porcelain", "--no-follow-tags", "--recurse-submodules=no",
                      f"--force-with-lease={ref}:{before}",
                      "--", destination, f"{candidate}:{ref}", check=False)
        # Always inspect remote state: a transport failure can follow a successful
        # server update, and success alone is not durable Registry evidence.
        try:
            actual = _fetch_head(repo, policy, destination)
        except IntegrationError as error:
            raise IntegrationError("PUBLICATION_UNCERTAIN", {
                "candidate_receipt_sha256": checksum, "push": pushed,
                "observation_failure": error.evidence,
            }) from error
        if _ancestor(repo, policy, candidate, actual):
            return _publication_receipt(receipt, actual, "PUBLISHED", pushed)
        if actual != before:
            raise IntegrationError("TARGET_MOVED", {"expected_target_sha": before, "actual_target_sha": actual,
                                                   "push": pushed})
        raise IntegrationError("PUBLICATION_FAILED", {"push": pushed,
                                                      "candidate_receipt_sha256": checksum})


def _publication_receipt(candidate: Mapping[str, Any], observed: str, state: str,
                         push: Mapping[str, Any] | None) -> dict[str, Any]:
    return _seal({"schema_version": 1, "kind": "factory-integration-publication",
                  "integration_id": candidate["integration_id"], "state": state,
                  "approval": candidate["approval"], "target_branch": candidate["target_branch"],
                  "target_before": candidate["target_before"], "target_after": candidate["target_after"],
                  "observed_target": observed, "candidate_receipt_sha256": candidate["receipt_sha256"],
                  "recorded_at": _stamp(), "push": push})
