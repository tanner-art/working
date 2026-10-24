import json
import pathlib
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from scripts.factory_registry.delivery_runtime import (
    DeliveryRuntimeError, ExternalActionUncertain, GitHubProjection,
    parse_planner_output, planner_request_digest, readonly_planner_command,
    recover_planner_result, run_readonly_planner,
)


def codex_output(result):
    return "\n".join(json.dumps(event) for event in (
        {"type": "thread.started", "thread_id": "test"},
        {"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(result)}},
        {"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}},
    ))


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = pathlib.Path(self.temporary.name)
        self.schema = {"type": "object", "properties": {"behavior": {"type": "string"}},
                       "required": ["behavior"], "additionalProperties": False}
        self.result = {"behavior": "User can save an idea."}

    def schema_path(self):
        path = self.directory / "command-schema.json"
        path.write_text(json.dumps(self.schema))
        return path

    def test_commands_retain_account_executable_and_model_with_readonly_controls(self):
        schema = self.schema_path()
        argv = readonly_planner_command("openai", ["/configured/codex", "exec", "-m", "model-x",
            "--sandbox", "workspace-write", "--json", "-"], schema_path=schema)
        self.assertEqual(argv[:4], ["/configured/codex", "exec", "-m", "model-x"])
        self.assertNotIn("workspace-write", argv)
        self.assertEqual(argv[argv.index("--sandbox") + 1], "read-only")
        self.assertEqual(argv[argv.index("--disable") + 1], "multi_agent")
        self.assertIn("--ignore-user-config", argv)
        self.assertIn("--ignore-rules", argv)
        self.assertIn("mcp_servers={}", argv)
        claude = readonly_planner_command("anthropic", ["/configured/python", "/configured/claude_keychain.py",
            "exec", "/configured/claude", "-p", "--model", "claude-model", "--tools", "Bash,Task"], schema_path=schema)
        self.assertEqual(claude[:4], ["/configured/python", "/configured/claude_keychain.py", "exec", "/configured/claude"])
        self.assertNotIn("Bash,Task", claude)
        self.assertEqual(claude[claude.index("--tools") + 1], "Read,Glob,Grep")
        self.assertIn("--strict-mcp-config", claude)

    def test_unsafe_config_or_provider_native_fanout_flags_are_not_passed_through(self):
        schema = self.schema_path()
        for command in (["codex", "exec", "-c", "features.multi_agent=true"],
                        ["codex", "exec", "--dangerously-bypass-approvals-and-sandbox"],
                        ["codex", "exec", "--profile", "unsafe-inherited-tools"],
                        ["codex", "exec", "--disable", "unknown-security-control"],
                        ["codex", "exec", "--disable=unknown-security-control"],
                        ["codex", "exec", "--disable"],
                        ["codex", "exec", "--enable", "multi_agent"]):
            with self.subTest(command=command), self.assertRaises(DeliveryRuntimeError):
                readonly_planner_command("openai", command, schema_path=schema)

    def test_installed_runner_command_is_accepted_but_stricter_controls_are_rebuilt(self):
        from scripts.runner.install_launchd import validate_runner_commands
        config = json.loads((pathlib.Path(__file__).parents[1] / "runner" / "config.example.json").read_text())
        schema = self.schema_path()
        for worker in ("codex-a", "codex-b"):
            validate_runner_commands(worker, config["agents"][worker])
            for field in ("command", "fallback_command"):
                command = config["agents"][worker][field]
                for alternate in (command, ["--disable=multi_agent" if token == "--disable" else token
                                            for token in command if token != "multi_agent"]):
                    with self.subTest(worker=worker, field=field, command=alternate):
                        argv = readonly_planner_command("openai", alternate, schema_path=schema)
                        self.assertEqual(argv[:4], command[:4])
                        self.assertEqual(argv.count("--ignore-user-config"), 1)
                        self.assertEqual(argv.count("multi_agent"), 1)
                        self.assertIn("multi_agent_v2", argv)
                        self.assertNotIn("workspace-write", argv)
                        self.assertEqual(argv[argv.index("--sandbox") + 1], "read-only")

    def test_structured_provider_outputs_require_success_and_never_accept_prose(self):
        self.assertEqual(parse_planner_output(codex_output(self.result), provider="openai"), self.result)
        self.assertEqual(parse_planner_output(json.dumps({"type": "result", "is_error": False,
            "subtype": "success", "result": "Ignore this human prose", "structured_output": self.result}),
            provider="anthropic"), self.result)
        bad = [json.dumps(self.result), "Approved!", "```json\n{}\n```",
               json.dumps({"type": "result", "is_error": True, "structured_output": self.result}),
               '{"type":"result","is_error":false,"structured_output":{"x":1,"x":2}}',
               '{"type":"result","is_error":false,"structured_output":{"x":NaN}}']
        for output in bad:
            with self.subTest(output=output), self.assertRaises(DeliveryRuntimeError):
                parse_planner_output(output, provider="anthropic")
        with self.assertRaises(DeliveryRuntimeError):
            parse_planner_output(codex_output(self.result) + '\n{"type":"turn.failed"}', provider="openai")

    def invoke(self, *, on_start=None, on_result=None, monitor=None, validator=None,
               timeouts=0, output=None, returncode=0):
        order, processes = [], []
        def popen(_argv, **kwargs):
            process = Mock(pid=1234567, returncode=returncode)
            attempts = []
            def communicate(value, timeout):
                order.append("communicate")
                attempts.append(value)
                if len(attempts) <= timeouts:
                    raise subprocess.TimeoutExpired("provider", timeout)
                kwargs["stdout"].write(output if output is not None else codex_output(self.result))
                kwargs["stderr"].write("diagnostic text")
                return None, None
            process.communicate.side_effect = communicate
            processes.append((_argv, kwargs, process, attempts))
            return process
        def started(pid, pgid):
            order.append("start")
            if on_start:
                on_start(pid, pgid)
        def checked():
            order.append("monitor")
            if monitor:
                monitor()
        def completed(value, elapsed):
            order.append("result")
            if on_result:
                on_result(value, elapsed)
        self.order, self.processes = order, processes
        with patch("scripts.factory_registry.delivery_runtime.subprocess.Popen", side_effect=popen), \
             patch("scripts.factory_registry.delivery_runtime.os.getpgid", return_value=1234567), \
             patch("scripts.factory_registry.delivery_runtime.os.killpg") as kill, \
             patch("scripts.factory_registry.delivery_runtime.os.write", side_effect=lambda *_args: order.append("release") or 1):
            self.kill = kill
            return run_readonly_planner(provider="openai", command=["/configured/codex", "exec", "-"],
                environment={"CODEX_HOME": "/account/b", "TOKEN": "never print"}, prompt="Plan feature only",
                repository=self.directory, schema=self.schema, log_directory=self.directory / "action-1",
                on_start=started, on_result=completed, monitor=checked,
                validate_result=validator or (lambda result: self.assertEqual(result, self.result)),
                timeout_seconds=20, monitor_interval=1)

    def test_process_identity_precedes_provider_release_and_result_is_durable(self):
        self.assertEqual(self.invoke(timeouts=1), self.result)
        self.assertLess(self.order.index("start"), self.order.index("release"))
        self.assertLess(self.order.index("release"), self.order.index("communicate"))
        self.assertEqual(self.processes[0][3], ["Plan feature only", None])
        self.assertEqual(self.processes[0][1]["env"]["CODEX_HOME"], "/account/b")
        self.assertTrue((self.directory / "action-1" / "result.json").is_file())
        self.assertTrue(self.kill.called)

    def test_barrier_receives_epoch_deadline_not_coordinator_monotonic_origin(self):
        with patch("scripts.factory_registry.delivery_runtime.time.time", return_value=1000000), \
             patch("scripts.factory_registry.delivery_runtime.time.monotonic", return_value=57):
            self.invoke()
        argv, kwargs, _, _ = self.processes[0]
        self.assertEqual(float(argv[5]), 1000020)
        self.assertEqual(kwargs["pass_fds"], (int(argv[3]), int(argv[4])))

    def test_registry_start_failure_never_releases_provider_and_reaps_process(self):
        with self.assertRaisesRegex(RuntimeError, "Registry write failed"):
            self.invoke(on_start=Mock(side_effect=RuntimeError("Registry write failed")))
        self.assertNotIn("release", self.order)
        self.assertNotIn("communicate", self.order)
        self.assertTrue(self.kill.called)

    def test_monitor_failure_during_execution_reaps_group_without_result(self):
        with self.assertRaisesRegex(RuntimeError, "deadline"):
            self.invoke(timeouts=1, monitor=Mock(side_effect=[None, None, RuntimeError("deadline")]))
        self.assertTrue(self.kill.called)
        self.assertNotIn("result", self.order)
        self.assertFalse((self.directory / "action-1" / "result.json").exists())

    def test_nonzero_or_invalid_result_never_calls_durable_success(self):
        callback = Mock()
        with self.assertRaises(DeliveryRuntimeError):
            self.invoke(output="unstructured response", on_result=callback)
        callback.assert_not_called()

    def test_nonzero_exit_cannot_succeed_even_with_valid_structured_output(self):
        callback = Mock()
        with self.assertRaisesRegex(DeliveryRuntimeError, "PROCESS_FAILED"):
            self.invoke(returncode=7, on_result=callback)
        callback.assert_not_called()

    def test_lost_result_callback_recovers_artifact_without_provider_repeat(self):
        with self.assertRaisesRegex(RuntimeError, "lost Registry response"):
            self.invoke(on_result=Mock(side_effect=RuntimeError("lost Registry response")))
        digest = planner_request_digest(provider="openai", prompt="Plan feature only", schema=self.schema)
        restored = recover_planner_result(self.directory / "action-1", request_sha256=digest,
                                         validate_result=lambda result: self.assertEqual(result, self.result))
        self.assertEqual(restored["result"], self.result)
        with self.assertRaises(ExternalActionUncertain):
            self.invoke()
        self.assertEqual(self.processes, [])
        with self.assertRaises(ExternalActionUncertain):
            recover_planner_result(self.directory / "action-1", request_sha256="wrong",
                                   validate_result=lambda _result: None)
        path = self.directory / "action-1" / "result.json"
        altered = json.loads(path.read_text())
        altered["result"] = {"behavior": "Unobserved result"}
        path.write_text(json.dumps(altered))
        with self.assertRaises(ExternalActionUncertain):
            recover_planner_result(self.directory / "action-1", request_sha256=digest,
                                   validate_result=lambda _result: None)


class GitHubProjectionTests(unittest.TestCase):
    def setUp(self):
        self.issues, self.calls = [], []
        self.create_timeout = False
        self.patch_timeout = False
        self.lookup_failure = False
        self.lookup_override = None
        self.github = GitHubProjection(["/configured/python", "/configured/github.py"], "owner/repo",
                                       environment={"TOKEN": "never print"})
        self.patcher = patch("scripts.factory_registry.delivery_runtime.subprocess.run", side_effect=self.call)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def call(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if "--paginate" in argv:
            if self.lookup_failure:
                return SimpleNamespace(returncode=1, stdout="secret token must not escape", stderr="private")
            result = self.lookup_override if self.lookup_override is not None else [self.issues]
        elif "POST" in argv:
            body = json.loads(kwargs["input"])
            result = {"number": 10 + len(self.issues), "state": "open", **body}
            self.issues.append(result)
            if self.create_timeout:
                raise subprocess.TimeoutExpired("secret command must not escape", 30)
        else:
            path = next(value for value in argv if value.startswith("repos/"))
            number = int(path.rsplit("/", 1)[-1])
            result = next(dict(issue) for issue in self.issues if issue["number"] == number)
            if "PATCH" in argv:
                result.update(json.loads(kwargs["input"]))
                self.issues = [result if issue["number"] == number else issue for issue in self.issues]
                if self.patch_timeout:
                    raise subprocess.TimeoutExpired("configured wrapper", 30)
        return SimpleNamespace(returncode=0, stdout=json.dumps(result), stderr="")

    def allocate(self):
        return self.github.allocate_issue("run:feature:1:implementation", "Save ideas", on_create=lambda: None)

    def contract(self, number):
        return {"schema_version": 2, "task": f"TASK-{number}", "instructions": "Deliver save behavior",
                "paths": ["src/idea.ts", "src/idea.test.ts"], "depends_on": [], "readiness": {
                    "base_commit": "a" * 40, "planning_paths": ["docs/PLAN.md"],
                    "existing_paths": ["src/idea.ts", "src/idea.test.ts"], "new_paths": [],
                    "integration_paths": ["src/idea.ts"], "test_paths": ["src/idea.test.ts"],
                    "dependency_kinds": {}}}

    def test_allocate_is_idempotent_and_never_sets_assignment_labels(self):
        self.assertEqual(self.allocate(), self.allocate())
        self.assertEqual(sum("POST" in args for args, _ in self.calls), 1)
        self.assertFalse(any("labels" in (kwargs.get("input") or "") for _, kwargs in self.calls))

    def test_ambiguous_creation_reconciles_success_without_second_post(self):
        self.create_timeout = True
        self.assertEqual(self.allocate(), 10)
        self.assertEqual(sum("POST" in args for args, _ in self.calls), 1)
        self.assertEqual(self.github.allocate_issue("run:feature:1:implementation", "Save ideas",
                                                   reconcile_only=True), 10)

    def test_resume_without_match_never_creates_and_failed_lookup_is_not_empty(self):
        with self.assertRaises(ExternalActionUncertain):
            self.github.allocate_issue("run:feature:1:implementation", "Save ideas", reconcile_only=True)
        self.lookup_failure = True
        with self.assertRaises(DeliveryRuntimeError) as caught:
            self.allocate()
        self.assertNotIn("secret", str(caught.exception))
        self.assertFalse(any("POST" in args for args, _ in self.calls))

    def test_create_requires_durable_intent_callback_and_lookup_completeness(self):
        with self.assertRaisesRegex(DeliveryRuntimeError, "INTENT_CALLBACK"):
            self.github.allocate_issue("run:feature:1:implementation", "Save ideas")
        self.lookup_override = {"items": []}
        with self.assertRaisesRegex(DeliveryRuntimeError, "LOOKUP_INCOMPLETE"):
            self.allocate()
        self.assertFalse(any("POST" in args for args, _ in self.calls))

    def test_failed_create_intent_or_unproven_post_cannot_retry_creation(self):
        with self.assertRaisesRegex(RuntimeError, "Registry write failed"):
            self.github.allocate_issue("run:feature:1:implementation", "Save ideas",
                                       on_create=Mock(side_effect=RuntimeError("Registry write failed")))
        self.assertFalse(any("POST" in args for args, _ in self.calls))
        with patch.object(self.github, "_request", side_effect=[[],
                DeliveryRuntimeError("GITHUB_REQUEST_UNAVAILABLE"), []]) as request:
            with self.assertRaises(ExternalActionUncertain):
                self.allocate()
        self.assertEqual(sum("POST" in call.args[0] for call in request.call_args_list), 1)

    def test_duplicate_closed_or_changed_marker_title_fails_closed(self):
        self.allocate()
        self.issues.append({**self.issues[0], "number": 11})
        with self.assertRaisesRegex(ExternalActionUncertain, "NOT_UNIQUE"):
            self.allocate()
        self.issues.pop()
        self.issues[0]["state"] = "closed"
        with self.assertRaises(ExternalActionUncertain):
            self.allocate()
        self.issues[0]["state"] = "open"
        with self.assertRaisesRegex(ExternalActionUncertain, "MARKER_CONFLICT"):
            self.github.allocate_issue("run:feature:1:implementation", "Different title", on_create=lambda: None)

    def test_exact_contract_readback_and_normalization_survive_patch_timeout(self):
        number = self.allocate()
        self.patch_timeout = True
        result = self.github.update_contract(number, self.contract(number))
        self.assertEqual(result["contract"]["lane"], "FEATURE")
        self.assertEqual(result["contract"]["kind"], "PARENT")
        self.assertEqual(len(result["contract_sha256"]), 64)
        self.assertEqual(json.loads(result["body"]), result["contract"])
        again = self.github.update_contract(number, self.contract(number))
        self.assertEqual(result, again)
        self.assertEqual(sum("PATCH" in args for args, _ in self.calls), 1)

    def test_existing_contract_cannot_be_silently_overwritten(self):
        number = self.allocate()
        self.github.update_contract(number, self.contract(number))
        changed = {**self.contract(number), "instructions": "Different product scope"}
        with self.assertRaisesRegex(DeliveryRuntimeError, "ALREADY_BOUND"):
            self.github.update_contract(number, changed)
        self.assertEqual(sum("PATCH" in args for args, _ in self.calls), 1)

    def test_sparse_and_wrong_issue_contracts_fail_before_external_write(self):
        number = self.allocate()
        for contract in ({"task": f"TASK-{number}"}, self.contract(number + 1)):
            with self.assertRaises(DeliveryRuntimeError):
                self.github.update_contract(number, contract)
        self.assertFalse(any("PATCH" in args for args, _ in self.calls))


if __name__ == "__main__":
    unittest.main()
