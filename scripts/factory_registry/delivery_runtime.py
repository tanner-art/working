"""Narrow, supervised provider and GitHub adapters for delivery coordination.

The caller owns Registry authorization, action reservation, capacity and replay
decisions. Model output is data: it never supplies commands, environments or
GitHub operations. A provider starts only after its process identity has been
durably recorded. An ambiguous external write requires reconciliation.
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import signal
import subprocess
import sys
import time
from typing import Any, Callable, Mapping, Sequence

from scripts.runner.review_protocol import (
    ReviewProtocolError, _codex_structured_output, _load_json, contract_digest,
)
from scripts.runner.task_readiness import contract_shape_reasons


class DeliveryRuntimeError(RuntimeError):
    """Content-free runtime failure safe to place in operational telemetry."""


class ExternalActionUncertain(DeliveryRuntimeError):
    """An external write may have succeeded; reconcile instead of repeating it."""


_MAX_OUTPUT = 4 * 1024 * 1024
_PLACEHOLDER = "Awaiting a Registry-approved execution contract. Not dispatchable."
_MODEL_CONFIG = re.compile(
    r'(?:model\s*=\s*"?[A-Za-z0-9._:-]+"?|'
    r'model_reasoning_effort\s*=\s*"?(?:low|medium|high|xhigh|max|ultra)"?)'
)
_PLANNER_DISABLED_FEATURES = (
    "multi_agent", "multi_agent_v2", "apps", "plugins", "hooks", "remote_plugin",
    "browser_use", "computer_use", "in_app_local_automation",
)


def _encode(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False)


def _argv(value: Sequence[str]) -> list[str]:
    if (not isinstance(value, (list, tuple)) or not value
            or any(not isinstance(item, str) or not item or "\0" in item for item in value)):
        raise DeliveryRuntimeError("INVALID_TRUSTED_COMMAND")
    return list(value)


def _environment(value: Mapping[str, str]) -> dict[str, str]:
    if not isinstance(value, Mapping) or any(
        not isinstance(key, str) or not key or "=" in key or "\0" in key
        or not isinstance(item, str) or "\0" in item for key, item in value.items()
    ):
        raise DeliveryRuntimeError("INVALID_TRUSTED_ENVIRONMENT")
    return dict(value)


def readonly_planner_command(provider: str, command: Sequence[str], *,
                             schema_path: pathlib.Path) -> list[str]:
    """Retain configured executable/auth wrapper and model, replace tool powers."""
    source = _argv(command)
    if not schema_path.is_absolute() or not schema_path.is_file():
        raise DeliveryRuntimeError("PLANNER_SCHEMA_UNAVAILABLE")
    if provider == "openai":
        if len(source) < 2 or pathlib.Path(source[0]).name != "codex" or source[1] != "exec":
            raise DeliveryRuntimeError("PLANNER_CODEX_COMMAND_REQUIRED")
        retained, index = source[:2], 2
        replaced = {"--sandbox", "-s", "--output-schema", "--output-last-message", "-o",
                    "--add-dir", "--cd", "-C", "--ask-for-approval", "-a"}
        while index < len(source):
            item = source[index]
            if item == "-" and index == len(source) - 1:
                break
            if item in {"--json", "--skip-git-repo-check", "--ignore-user-config", "--ignore-rules"}:
                if item == "--skip-git-repo-check":
                    retained.append(item)
                index += 1
                continue
            if item == "--disable" or item.startswith("--disable="):
                inline = item.startswith("--disable=")
                value = item.split("=", 1)[1] if inline else (
                    source[index + 1] if index + 1 < len(source) else None)
                if value not in _PLANNER_DISABLED_FEATURES:
                    raise DeliveryRuntimeError("PLANNER_UNSAFE_CONFIGURATION")
                # Installed runner commands already disable native fan-out.
                # Rebuild the complete stricter allowlisted controls below.
                index += 1 if inline else 2
                continue
            if item in replaced:
                if index + 1 >= len(source) or source[index + 1].startswith("-"):
                    raise DeliveryRuntimeError("PLANNER_COMMAND_VALUE_REQUIRED")
                index += 2
                continue
            if item in {"--model", "-m", "--config", "-c"}:
                if index + 1 >= len(source):
                    raise DeliveryRuntimeError("PLANNER_COMMAND_VALUE_REQUIRED")
                value = source[index + 1]
                if ((item in {"--config", "-c"} and not _MODEL_CONFIG.fullmatch(value))
                        or (item not in {"--config", "-c"}
                            and not re.fullmatch(r"[A-Za-z0-9._:-]+", value))):
                    raise DeliveryRuntimeError("PLANNER_UNSAFE_CONFIGURATION")
                retained.extend((item, value))
                index += 2
                continue
            raise DeliveryRuntimeError("PLANNER_UNSUPPORTED_CODEX_ARGUMENT")
        # These controls are supported by the installed Codex CLI. Ignoring
        # user configuration preserves authentication from the configured
        # CODEX_HOME while removing inherited hooks and execution exceptions.
        # Named config profiles are deliberately not retained: select the
        # planner model explicitly instead of reintroducing arbitrary tools.
        return retained + ["--ignore-user-config", "--ignore-rules", "--sandbox", "read-only",
                           "-c", "mcp_servers={}",
                           *(argument for feature in _PLANNER_DISABLED_FEATURES
                             for argument in ("--disable", feature)),
                           "--json", "--output-schema", str(schema_path), "-"]
    if provider != "anthropic":
        raise DeliveryRuntimeError("PLANNER_PROVIDER_UNSUPPORTED")
    if pathlib.Path(source[0]).name == "claude":
        prefix, tail = source[:1], source[1:]
    elif len(source) >= 4 and pathlib.Path(source[1]).name == "claude_keychain.py":
        if source[2] != "exec" or pathlib.Path(source[3]).name != "claude":
            raise DeliveryRuntimeError("PLANNER_CLAUDE_WRAPPER_INVALID")
        prefix, tail = source[:4], source[4:]
    else:
        raise DeliveryRuntimeError("PLANNER_CLAUDE_COMMAND_REQUIRED")
    replaced = {"--output-format", "--tools", "--allowedTools", "--allowed-tools",
                "--disallowedTools", "--disallowed-tools", "--permission-mode",
                "--permission-prompts", "--json-schema", "--add-dir", "--mcp-config",
                "--setting-sources", "--agents", "--agent"}
    retained, index = prefix + ["--print"], 0
    while index < len(tail):
        item = tail[index]
        if item in {"--print", "-p", "--strict-mcp-config"}:
            index += 1
            continue
        if item in replaced:
            if index + 1 >= len(tail):
                raise DeliveryRuntimeError("PLANNER_COMMAND_VALUE_REQUIRED")
            index += 2
            continue
        if item in {"--model", "--effort", "--max-turns"}:
            if index + 1 >= len(tail) or not re.fullmatch(r"[A-Za-z0-9._:-]+", tail[index + 1]):
                raise DeliveryRuntimeError("PLANNER_COMMAND_VALUE_REQUIRED")
            retained.extend(tail[index:index + 2])
            index += 2
            continue
        raise DeliveryRuntimeError("PLANNER_UNSUPPORTED_CLAUDE_ARGUMENT")
    schema = _load_json(schema_path.read_text(), message="planner schema is invalid")
    return retained + ["--output-format", "json", "--json-schema", _encode(schema),
                       "--tools", "Read,Glob,Grep", "--permission-mode", "dontAsk",
                       "--permission-prompts", "none", "--strict-mcp-config",
                       "--mcp-config", '{"mcpServers":{}}', "--setting-sources", ""]


def parse_planner_output(output: str, *, provider: str) -> dict[str, Any]:
    """Require a successful structured provider result, never prose or fences."""
    try:
        if provider == "openai":
            value = _codex_structured_output(output)
        elif provider == "anthropic":
            envelope = _load_json(output, message="planner output is unparseable")
            if (not isinstance(envelope, Mapping) or envelope.get("type") != "result"
                    or envelope.get("is_error") is not False
                    or envelope.get("subtype") not in (None, "success")
                    or "error" in envelope):
                raise DeliveryRuntimeError("PLANNER_PROVIDER_RESULT_FAILED")
            value = envelope.get("structured_output")
            if "structured_output" not in envelope:
                value = _load_json(envelope.get("result"), message="planner result is not JSON")
        else:
            raise DeliveryRuntimeError("PLANNER_PROVIDER_UNSUPPORTED")
        if not isinstance(value, Mapping):
            raise DeliveryRuntimeError("PLANNER_RESULT_OBJECT_REQUIRED")
        # Also reject NaN/infinity accepted by Python's JSON decoder.
        _encode(value)
        return dict(value)
    except (ReviewProtocolError, TypeError, ValueError):
        raise DeliveryRuntimeError("PLANNER_STRUCTURED_RESULT_INVALID") from None


def planner_request_digest(*, provider: str, prompt: str, schema: Mapping[str, Any]) -> str:
    return hashlib.sha256(_encode({"provider": provider, "prompt": prompt,
                                  "schema": schema}).encode()).hexdigest()


def _stop_group(process: subprocess.Popen, grace_seconds: float = 5) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait(timeout=grace_seconds)


def _persist_json(path: pathlib.Path, value: Mapping[str, Any]) -> None:
    # Exclusive artifacts prevent an uncertain action being silently rerun.
    with path.open("x", encoding="utf-8") as stream:
        os.chmod(path, 0o600)
        stream.write(_encode(value) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def run_readonly_planner(*, provider: str, command: Sequence[str],
                         environment: Mapping[str, str], prompt: str,
                         repository: pathlib.Path, schema: Mapping[str, Any],
                         log_directory: pathlib.Path,
                         on_start: Callable[[int, int], None],
                         on_result: Callable[[Mapping[str, Any], float], None],
                         monitor: Callable[[], None],
                         validate_result: Callable[[Mapping[str, Any]], Any],
                         timeout_seconds: float = 900,
                         monitor_interval: float = 5) -> dict[str, Any]:
    """Run one reserved planner action with durable process/result callbacks.

    The caller must reserve the action and check account capacity first.
    ``monitor`` enforces current authorization/deadline and capacity policy.
    A successful artifact survives a crash before ``on_result`` commits; use
    ``recover_planner_result`` to reconcile it without another provider call.
    """
    if (not isinstance(prompt, str) or not prompt.strip() or len(prompt) > _MAX_OUTPUT
            or not isinstance(schema, Mapping) or schema.get("type") != "object"
            or isinstance(timeout_seconds, bool) or not 0 < timeout_seconds <= 3600
            or isinstance(monitor_interval, bool) or not 0 < monitor_interval <= 30
            or not repository.is_absolute() or not repository.is_dir()
            or not log_directory.is_absolute()
            or not all(callable(value) for value in (on_start, on_result, monitor, validate_result))):
        raise DeliveryRuntimeError("PLANNER_INVOCATION_INVALID")
    env = _environment(environment)
    monitor()
    log_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    schema_path = log_directory / "schema.json"
    request_sha256 = planner_request_digest(provider=provider, prompt=prompt, schema=schema)
    try:
        _persist_json(schema_path, schema)
    except FileExistsError:
        raise ExternalActionUncertain("PLANNER_ARTIFACTS_EXIST_RECONCILE_REQUIRED") from None
    argv = readonly_planner_command(provider, command, schema_path=schema_path)
    stdout_path, stderr_path = log_directory / "stdout.jsonl", log_directory / "stderr.log"
    barrier_read, barrier_write = os.pipe()
    lifeline_read, lifeline_write = os.pipe()
    process = None
    previous = {}
    started = time.monotonic()
    deadline_epoch = time.time() + timeout_seconds
    try:
        with stdout_path.open("x") as stdout, stderr_path.open("x") as stderr:
            os.chmod(stdout_path, 0o600)
            os.chmod(stderr_path, 0o600)
            process = subprocess.Popen(
                [sys.executable, "-I", str(pathlib.Path(__file__).with_name("delivery_planner_barrier.py")),
                 str(barrier_read), str(lifeline_read), str(deadline_epoch), *argv],
                cwd=repository, env=env, stdin=subprocess.PIPE,
                stdout=stdout, stderr=stderr, text=True, start_new_session=True,
                pass_fds=(barrier_read, lifeline_read),
            )
            os.close(barrier_read)
            barrier_read = None
            os.close(lifeline_read)
            lifeline_read = None
            def interrupted(signum, _frame):
                raise DeliveryRuntimeError(f"PLANNER_INTERRUPTED_{signum}")
            for sig in (signal.SIGTERM, signal.SIGINT):
                previous[sig] = signal.signal(sig, interrupted)
            # The barrier process cannot exec the provider before both writes.
            pgid = os.getpgid(process.pid)
            if pgid != process.pid:
                raise DeliveryRuntimeError("PLANNER_PROCESS_IDENTITY_INVALID")
            on_start(process.pid, pgid)
            monitor()
            os.write(barrier_write, b"1")
            os.close(barrier_write)
            barrier_write = None
            pending_input = prompt
            while True:
                remaining = timeout_seconds - (time.monotonic() - started)
                if remaining <= 0:
                    raise DeliveryRuntimeError("PLANNER_TIMEOUT")
                try:
                    process.communicate(pending_input, timeout=min(remaining, monitor_interval))
                    break
                except subprocess.TimeoutExpired:
                    pending_input = None
                    monitor()
                    if any(path.stat().st_size > _MAX_OUTPUT for path in (stdout_path, stderr_path)):
                        raise DeliveryRuntimeError("PLANNER_OUTPUT_LIMIT")
            if process.returncode != 0:
                raise DeliveryRuntimeError("PLANNER_PROCESS_FAILED")
            # Kill any descendant retained by a provider even after parent exit.
            _stop_group(process)
            process = None
            monitor()
            stdout.flush()
            stderr.flush()
            os.fsync(stdout.fileno())
            os.fsync(stderr.fileno())
        if any(path.stat().st_size > _MAX_OUTPUT for path in (stdout_path, stderr_path)):
            raise DeliveryRuntimeError("PLANNER_OUTPUT_LIMIT")
        result = parse_planner_output(stdout_path.read_text(), provider=provider)
        validate_result(result)
        elapsed = time.monotonic() - started
        _persist_json(log_directory / "result.json", {
            "schema_version": 1, "provider": provider,
            "request_sha256": request_sha256, "result": result,
            "elapsed_seconds": elapsed,
            "stdout_sha256": hashlib.sha256(stdout_path.read_bytes()).hexdigest(),
        })
        on_result(result, elapsed)
        return result
    except BaseException:
        if process is not None:
            _stop_group(process)
        raise
    finally:
        # The sole lifeline writer stays in this coordinator, never in a
        # provider. SIGKILL/crash closes it too, so cleanup is not finally-only.
        for descriptor in (barrier_read, barrier_write, lifeline_read, lifeline_write):
            if descriptor is not None:
                os.close(descriptor)
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def recover_planner_result(log_directory: pathlib.Path, *, request_sha256: str,
                           validate_result: Callable[[Mapping[str, Any]], Any]) -> dict[str, Any]:
    """Read a proven result after a caller crash, without restarting a provider."""
    try:
        value = _load_json((log_directory / "result.json").read_text(), message="invalid planner result")
        stdout = (log_directory / "stdout.jsonl").read_bytes()
        if (not isinstance(value, dict) or value.get("schema_version") != 1
                or value.get("request_sha256") != request_sha256
                or value.get("stdout_sha256") != hashlib.sha256(stdout).hexdigest()
                or not isinstance(value.get("result"), dict)
                or isinstance(value.get("elapsed_seconds"), bool)
                or not isinstance(value.get("elapsed_seconds"), (int, float))
                or not 0 <= value["elapsed_seconds"] <= 7200):
            raise ValueError("invalid result identity")
        if parse_planner_output(stdout.decode("utf-8"), provider=value.get("provider")) != value["result"]:
            raise ValueError("result differs from provider output")
        validate_result(value["result"])
        return value
    except (OSError, ValueError, TypeError, DeliveryRuntimeError):
        raise ExternalActionUncertain("PLANNER_RESULT_UNPROVEN") from None


def _normalized_contract(value: Mapping[str, Any], number: int) -> dict[str, Any]:
    """Match the runner's normalized JSON body and require the v2 contract."""
    if not isinstance(value, Mapping):
        raise DeliveryRuntimeError("ISSUE_CONTRACT_INVALID")
    result = dict(value)
    for key, default in (("capacity_size", "SUBSTANTIAL"), ("capacity_risk", "UNCERTAIN"),
                         ("lane", "FEATURE"), ("kind", "PARENT")):
        result[key] = str(result.get(key, default)).upper()
    paths, dependencies = result.get("paths"), result.get("depends_on", [])
    if (result.get("task") != f"TASK-{number}" or result.get("schema_version") != 2
            or not isinstance(paths, list) or not paths
            or any(not isinstance(path, str) or path.startswith(("/", "."))
                   or ".." in path.split("/") or not re.fullmatch(r"[A-Za-z0-9_./-]+", path)
                   for path in paths)
            or not isinstance(dependencies, list)
            or any(type(item) is not int or item <= 0 for item in dependencies)
            or not isinstance(result.get("instructions"), str) or not result["instructions"].strip()
            or result["capacity_size"] not in {"VERY_SMALL", "SMALL", "SUBSTANTIAL"}
            or result["capacity_risk"] not in {"BOUNDED", "UNCERTAIN", "EMERGENCY_RECOVERY"}
            or result["lane"] not in {"FEATURE", "PLATFORM", "ASSURANCE"}
            or result["kind"] not in {"PARENT", "TEST", "REVIEW", "EVALUATION"}
            or contract_shape_reasons(result)):
        raise DeliveryRuntimeError("ISSUE_CONTRACT_INVALID")
    return result


class GitHubProjection:
    """Idempotent issue projection through a configured gh-compatible wrapper.

    No assignment labels are written. The caller must durably reserve a create
    action before calling ``allocate_issue``. After a crash following the
    ``on_create`` callback, use ``reconcile_only=True``; an absent match then is
    uncertain, never permission to issue another POST.
    """

    def __init__(self, command: Sequence[str], repository: str, *,
                 environment: Mapping[str, str] | None = None, timeout_seconds: float = 30):
        self.command = _argv(command)
        if (not isinstance(repository, str)
                or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository)
                or isinstance(timeout_seconds, bool) or not 0 < timeout_seconds <= 120):
            raise DeliveryRuntimeError("GITHUB_CONFIGURATION_INVALID")
        self.repository = repository
        self.environment = _environment(os.environ if environment is None else environment)
        self.timeout_seconds = timeout_seconds

    def _request(self, args: Sequence[str], payload: Mapping[str, Any] | None = None) -> Any:
        try:
            result = subprocess.run(self.command + list(args),
                                    input=_encode(payload) if payload is not None else None,
                                    capture_output=True, text=True, check=False,
                                    env=self.environment, timeout=self.timeout_seconds)
        except (OSError, subprocess.SubprocessError):
            raise DeliveryRuntimeError("GITHUB_REQUEST_UNAVAILABLE") from None
        if result.returncode or len(result.stdout) > 16 * _MAX_OUTPUT:
            raise DeliveryRuntimeError("GITHUB_REQUEST_FAILED")
        try:
            return _load_json(result.stdout, message="GitHub result is not JSON")
        except (ValueError, TypeError):
            raise DeliveryRuntimeError("GITHUB_RESPONSE_INVALID") from None

    @staticmethod
    def _marked_title(marker: str, title: str) -> str:
        if (not isinstance(marker, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{3,200}", marker)
                or not isinstance(title, str) or not title.strip()
                or any(ord(char) < 32 for char in title)):
            raise DeliveryRuntimeError("ISSUE_IDENTITY_INVALID")
        prefix = "[factory-delivery:" + hashlib.sha256(marker.encode()).hexdigest() + "] "
        return prefix + title.strip()[:256 - len(prefix)]

    def _lookup(self, marked_title: str) -> int | None:
        # REST pagination avoids search-index lag and includes closed issues.
        pages = self._request(["api", "--paginate", "--slurp",
                               f"repos/{self.repository}/issues?state=all&per_page=100"])
        if not isinstance(pages, list) or any(not isinstance(page, list) for page in pages):
            raise DeliveryRuntimeError("ISSUE_LOOKUP_INCOMPLETE")
        prefix = marked_title.split("] ", 1)[0] + "] "
        matches = []
        for page in pages:
            for item in page:
                if not isinstance(item, dict) or not isinstance(item.get("title"), str):
                    raise DeliveryRuntimeError("ISSUE_LOOKUP_INCOMPLETE")
                if "pull_request" not in item and item["title"].startswith(prefix):
                    matches.append(item)
        if len(matches) > 1:
            raise ExternalActionUncertain("ISSUE_MARKER_NOT_UNIQUE")
        if not matches:
            return None
        match = matches[0]
        if (match["title"] != marked_title or type(match.get("number")) is not int
                or match["number"] <= 0 or match.get("state") != "open"):
            raise ExternalActionUncertain("ISSUE_MARKER_CONFLICT")
        return match["number"]

    def allocate_issue(self, marker: str, title: str, *, reconcile_only: bool = False,
                       on_create: Callable[[], None] | None = None) -> int:
        marked_title = self._marked_title(marker, title)
        number = self._lookup(marked_title)
        if number is not None:
            return number
        if reconcile_only:
            raise ExternalActionUncertain("ISSUE_CREATION_UNPROVEN")
        if not callable(on_create):
            raise DeliveryRuntimeError("ISSUE_CREATE_INTENT_CALLBACK_REQUIRED")
        on_create()
        try:
            created = self._request(["api", f"repos/{self.repository}/issues", "--method", "POST",
                                     "--input", "-"], {"title": marked_title, "body": _PLACEHOLDER})
            if (not isinstance(created, dict) or created.get("title") != marked_title
                    or type(created.get("number")) is not int or created["number"] <= 0
                    or created.get("state") != "open" or "pull_request" in created):
                raise DeliveryRuntimeError("ISSUE_CREATE_RESPONSE_INVALID")
            return created["number"]
        except DeliveryRuntimeError:
            # Reconcile only by reading. Never repeat an uncertain POST here.
            try:
                number = self._lookup(marked_title)
                if number is not None:
                    return number
            except DeliveryRuntimeError:
                pass
            raise ExternalActionUncertain("ISSUE_CREATION_UNPROVEN") from None

    def _read_issue(self, number: int) -> dict[str, Any]:
        if type(number) is not int or number <= 0:
            raise DeliveryRuntimeError("ISSUE_NUMBER_INVALID")
        value = self._request(["api", f"repos/{self.repository}/issues/{number}"])
        if (not isinstance(value, dict) or value.get("number") != number or "pull_request" in value
                or value.get("state") != "open" or not isinstance(value.get("body"), str)
                or not isinstance(value.get("title"), str)
                or not re.match(r"^\[factory-delivery:[0-9a-f]{64}\] ", value["title"])):
            raise DeliveryRuntimeError("ISSUE_PROJECTION_IDENTITY_INVALID")
        return value

    def update_contract(self, number: int, contract: Mapping[str, Any]) -> dict[str, Any]:
        normalized = _normalized_contract(contract, number)
        expected_digest = contract_digest(normalized)
        before = self._read_issue(number)
        if before["body"] != _PLACEHOLDER:
            try:
                existing = _normalized_contract(_load_json(before["body"], message="invalid issue body"), number)
            except ValueError:
                raise DeliveryRuntimeError("ISSUE_CONTRACT_ALREADY_BOUND") from None
            if contract_digest(existing) != expected_digest:
                raise DeliveryRuntimeError("ISSUE_CONTRACT_ALREADY_BOUND")
        else:
            try:
                self._request(["api", f"repos/{self.repository}/issues/{number}", "--method", "PATCH",
                               "--input", "-"], {"body": _encode(normalized)})
            except DeliveryRuntimeError:
                # A repeated identical PATCH is harmless, but this attempt
                # reports success only when the subsequent read proves it.
                pass
        after = self._read_issue(number)
        try:
            actual = _normalized_contract(_load_json(after["body"], message="invalid issue body"), number)
        except (ValueError, DeliveryRuntimeError):
            raise ExternalActionUncertain("ISSUE_CONTRACT_WRITE_UNPROVEN") from None
        if after["title"] != before["title"] or contract_digest(actual) != expected_digest:
            raise ExternalActionUncertain("ISSUE_CONTRACT_WRITE_UNPROVEN")
        return {"number": number, "body": after["body"], "contract": actual,
                "contract_sha256": expected_digest,
                "url": f"https://github.com/{self.repository}/issues/{number}"}
