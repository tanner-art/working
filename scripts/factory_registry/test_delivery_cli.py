import contextlib
import io
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts.factory_registry.delivery_cli import main
from scripts.factory_registry.models import Lane, Worker
from scripts.factory_registry.repository import RegistryConflict
from scripts.factory_registry.sqlite_registry import SQLiteRegistry


class DeliveryCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.database = pathlib.Path(self.temporary.name) / "registry.sqlite3"
        self.registry = SQLiteRegistry(self.database)
        self.registry.initialize()
        self.registry.register_worker(Worker("coordinator", "Coordinator", ("coordination",),
                                             (Lane.FEATURE,), role="ORCHESTRA"))
        self.now = "2026-10-16T12:00:00.000000Z"

    def revision(self):
        return self.registry.dispatch_control()["revision"]

    def invoke(self, *args):
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors), \
                patch("scripts.factory_registry.delivery_cli.utc_now", return_value=self.now):
            code = main(list(args))
        return code, json.loads(output.getvalue()) if output.getvalue() else None, \
            json.loads(errors.getvalue()) if errors.getvalue() else None

    def submit(self, feature_id="FEATURE-1", *extra, revision=None):
        return self.invoke("submit", "--database", str(self.database),
            "--expected-revision", str(self.revision() if revision is None else revision),
            "--id", feature_id, "--title", "Save an idea",
            "--experience", "I save a thought and find it in Ideas.", *extra)

    def authorize(self, *extra, revision=None):
        return self.invoke("authorize", "--database", str(self.database),
            "--expected-revision", str(self.revision() if revision is None else revision),
            "--run-id", "run-1", "--feature-id", "FEATURE-1",
            "--deadline", "2026-10-16T14:00:00Z", "--base-ref", "codex/delivery",
            "--parent-limit", "2", "--max-generations", "3",
            "--coordinator-worker-id", "coordinator", *extra)

    def test_submit_preserves_minimal_owner_request_and_stays_paused(self):
        before = self.revision()
        code, result, error = self.submit()
        self.assertEqual((code, error), (0, None))
        self.assertEqual(result["feature_id"], "FEATURE-1")
        self.assertEqual(result["revision"], before + 1)
        snapshot = self.registry.delivery_snapshot()
        self.assertEqual(snapshot["features"][0]["brief"], {
            "id": "FEATURE-1", "title": "Save an idea",
            "user_experience": "I save a thought and find it in Ideas."})
        self.assertEqual(snapshot["control"]["dispatch_mode"], "PAUSED")
        self.assertEqual(snapshot["control"]["kill_switch_engaged"], 1)
        self.assertEqual(snapshot["records"]["request:FEATURE-1"]["submitted_at"], self.now)

    def test_submit_includes_repeatable_constraints_acceptance_and_dependencies(self):
        code, _, _ = self.submit("FEATURE-2", "--constraint", "Preserve source content",
            "--constraint", "Keep optional settings hidden", "--acceptance", "Saved idea survives reload",
            "--depends-on", "FEATURE-1")
        self.assertEqual(code, 0)
        brief = self.registry.delivery_snapshot()["features"][0]["brief"]
        self.assertEqual(brief["constraints"], ["Preserve source content", "Keep optional settings hidden"])
        self.assertEqual(brief["acceptance_criteria"], ["Saved idea survives reload"])
        self.assertEqual(brief["dependency_feature_ids"], ["FEATURE-1"])

    def test_submit_replay_preserves_revision_and_changed_request_is_rejected(self):
        before = self.revision()
        self.assertEqual(self.submit(revision=before)[0], 0)
        after = self.revision()
        self.assertEqual(self.submit(revision=before)[0], 0)
        self.assertEqual(self.revision(), after)
        code, _, error = self.submit("FEATURE-1", "--constraint", "Different request")
        self.assertEqual(code, 1)
        self.assertEqual(error["error"], "OPERATION_ID_REUSED")
        self.assertEqual(self.revision(), after)

    def test_mutations_require_expected_revision_and_stale_revision_fails_closed(self):
        code, _, error = self.invoke("submit", "--database", str(self.database), "--id", "FEATURE-1",
                                    "--title", "Feature", "--experience", "User experience")
        self.assertEqual((code, error["error"]), (2, "DELIVERY_ARGUMENTS_INVALID"))
        code, _, error = self.submit(revision=self.revision() - 1)
        self.assertEqual(code, 1)
        self.assertIn("REVISION", error["error"])
        self.assertEqual(self.registry.delivery_snapshot()["features"], [])

    def test_authorize_records_complete_bound_but_never_activates_or_claims(self):
        self.submit()
        before = self.revision()
        code, result, error = self.authorize()
        self.assertEqual((code, error), (0, None))
        self.assertEqual(result["revision"], before + 1)
        snapshot = self.registry.delivery_snapshot(run_id="run-1")
        authorization = snapshot["authorization"]
        self.assertEqual(authorization["feature_ids"], ["FEATURE-1"])
        self.assertEqual(authorization["deadline"], "2026-10-16T14:00:00.000000Z")
        self.assertEqual(authorization["base_ref"], "codex/delivery")
        self.assertEqual(authorization["parent_limit"], 2)
        self.assertEqual(authorization["max_generations"], 3)
        self.assertEqual(authorization["coordinator_worker_id"], "coordinator")
        self.assertEqual(snapshot["control"]["dispatch_mode"], "PAUSED")
        self.assertTrue(snapshot["control"]["kill_switch_engaged"])
        self.assertEqual(self.registry.active_attempt_runtimes(), ())
        self.assertEqual(self.registry.active_unbound_leases(), ())

    def test_authorize_missing_dependency_invalid_worker_and_expired_deadline_fail(self):
        self.submit("FEATURE-1", "--depends-on", "FEATURE-2")
        for extra, expected in (((), "DELIVERY_DEPENDENCY_NOT_AUTHORIZED"),
                (("--coordinator-worker-id", "missing"), "DELIVERY_COORDINATOR_INVALID"),
                (("--deadline", "2026-10-15T12:00:00Z"), "RUN_DEADLINE_REACHED")):
            with self.subTest(extra=extra):
                code, _, error = self.authorize(*extra)
                self.assertEqual((code, error["error"]), (1, expected))
        self.assertIsNone(self.registry.delivery_snapshot(run_id="run-1")["authorization"])

    def test_status_is_readonly_and_unknown_run_is_not_empty_success(self):
        self.submit()
        self.authorize()
        before = self.revision()
        code, result, error = self.invoke("status", "--database", str(self.database), "--run-id", "run-1")
        self.assertEqual((code, error), (0, None))
        self.assertEqual(result["revision"], before)
        self.assertEqual(result["features"][0]["next_action"], "PLAN")
        self.assertEqual(self.revision(), before)
        code, result, error = self.invoke("status", "--database", str(self.database), "--run-id", "missing")
        self.assertEqual((code, result, error["error"]), (1, None, "DELIVERY_NOT_FOUND"))

    def test_invalid_brief_and_missing_database_do_not_create_records(self):
        code, _, error = self.submit("FEATURE-1", "--depends-on", "FEATURE-1")
        self.assertEqual((code, error["error"]), (1, "FEATURE_BRIEF_INVALID"))
        missing = self.database.with_name("missing.sqlite3")
        code, _, error = self.invoke("status", "--database", str(missing))
        self.assertEqual((code, error["error"]), (1, "DELIVERY_DATABASE_UNAVAILABLE"))
        self.assertFalse(missing.exists())
        code, _, error = self.invoke("status", "--database", "relative.sqlite3")
        self.assertEqual((code, error["error"]), (1, "DELIVERY_DATABASE_UNAVAILABLE"))

    def test_errors_do_not_repeat_values_exception_details_or_credentials(self):
        secret = "secret-auth-value-do-not-print"
        with patch("scripts.factory_registry.delivery_cli.SQLiteRegistry",
                   side_effect=OSError(secret)):
            code, _, error = self.invoke("status", "--database", str(self.database))
        self.assertEqual((code, error["error"]), (1, "DELIVERY_REGISTRY_UNAVAILABLE"))
        self.assertNotIn(secret, json.dumps(error))
        with patch("scripts.factory_registry.delivery_cli.run",
                   side_effect=RegistryConflict("SAFE_CODE", secret)):
            _, _, error = self.invoke("status", "--database", str(self.database))
        self.assertEqual(error["error"], "SAFE_CODE")
        self.assertNotIn(secret, json.dumps(error))
        code, _, error = self.invoke("status", "--database", str(self.database), "--unexpected", secret)
        self.assertEqual((code, error["error"]), (2, "DELIVERY_ARGUMENTS_INVALID"))
        self.assertNotIn(secret, json.dumps(error))

    def test_module_entrypoint_outputs_json_without_dispatch(self):
        result = subprocess.run([sys.executable, "-m", "scripts.factory_registry.delivery_cli", "status",
                                 "--database", str(self.database)], capture_output=True, text=True,
                                cwd=pathlib.Path(__file__).resolve().parents[2], timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["passed"])
        self.assertEqual(payload["control"]["dispatch_mode"], "PAUSED")

    def test_supervised_tick_waits_without_loading_or_mutating_when_not_live(self):
        for mode in ('PAUSED', 'STOPPING', 'RECOVERY_REQUIRED'):
            with self.subTest(mode=mode):
                control = self.registry.dispatch_control()
                if control['dispatch_mode'] != mode:
                    self.registry.set_dispatch_control(expected_revision=control['revision'],
                        expected_mode=control['dispatch_mode'], new_mode=mode, kill_switch_engaged=True,
                        changed_at=self.now, reason='test non-live service')
                before = self.revision()
                with patch('scripts.factory_registry.delivery_service.load_coordinator') as loader:
                    code, result, error = self.invoke('tick', '--database', str(self.database),
                                                     '--config', str(self.database.with_name('unused.json')))
                self.assertEqual((code, error), (0, None))
                self.assertEqual((result['state'], result['factory_mode']), ('WAITING', mode))
                self.assertEqual(self.revision(), before)
                loader.assert_not_called()
                self.assertFalse(self.database.with_suffix('.delivery.lock').exists())

    def test_explicit_prepare_requires_revision_and_selects_preparation_adapter(self):
        config = self.database.with_name('config.json')
        code, _, error = self.invoke('prepare', '--database', str(self.database), '--config', str(config))
        self.assertEqual((code, error['error']), (2, 'DELIVERY_ARGUMENTS_INVALID'))
        with patch('scripts.factory_registry.delivery_service.load_coordinator') as loader:
            loader.return_value.tick.return_value = {'results': [], 'revision': self.revision()}
            code, result, error = self.invoke('prepare', '--database', str(self.database),
                '--config', str(config), '--expected-revision', str(self.revision()))
            loader.assert_called_once_with(config, self.database, prepare=True)
        self.assertEqual((code, error), (0, None))
        self.assertEqual(result['command'], 'prepare')
        with patch('scripts.factory_registry.delivery_service.load_coordinator') as loader:
            code, _, error = self.invoke('prepare', '--database', str(self.database),
                '--config', str(config), '--expected-revision', str(self.revision() - 1))
            loader.assert_not_called()
        self.assertEqual((code, error['error']), (1, 'REGISTRY_REVISION_CHANGED'))


if __name__ == "__main__":
    unittest.main()
