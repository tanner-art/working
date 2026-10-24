"""Real-process tests: no AI provider, live Registry or external service."""

import json
import os
import pathlib
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from scripts.factory_registry import delivery_planner_barrier, delivery_runtime


class PlannerLifelineTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = pathlib.Path(self.temporary.name)
        self.barrier = pathlib.Path(delivery_runtime.__file__).with_name("delivery_planner_barrier.py")
        self.descriptors = set()
        self.addCleanup(self.close_descriptors)

    def close_descriptors(self):
        for descriptor in tuple(self.descriptors):
            self.close_descriptor(descriptor)

    def close_descriptor(self, descriptor):
        self.descriptors.remove(descriptor)
        os.close(descriptor)

    def wait_until(self, predicate, message, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = predicate()
            if value:
                return value
            time.sleep(0.02)
        self.fail(message)

    def live_group(self, pgid):
        rows = subprocess.run(["ps", "-axo", "pid=,ppid=,pgid=,stat="],
                              capture_output=True, text=True, check=True).stdout.splitlines()
        return [(int(pid), int(ppid)) for row in rows
                for pid, ppid, group, state in [row.split()]
                if int(group) == pgid and not state.startswith("Z")]

    def cleanup_group(self, process):
        # Every process used here was launched into a fresh session. The group
        # is still owned by one of those live members whenever it is signalled.
        if self.live_group(process.pid):
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        process.wait(timeout=5)
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream:
                stream.close()

    def barrier_process(self, script, *, timeout=10, release=True):
        barrier_read, barrier_write = os.pipe()
        lifeline_read, lifeline_write = os.pipe()
        process = subprocess.Popen([sys.executable, "-I", str(self.barrier), str(barrier_read),
            str(lifeline_read), str(time.time() + timeout), sys.executable, "-c", script],
            pass_fds=(barrier_read, lifeline_read), start_new_session=True,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        os.close(barrier_read)
        os.close(lifeline_read)
        self.addCleanup(self.cleanup_group, process)
        self.descriptors.update((lifeline_write, barrier_write))
        if release:
            os.write(barrier_write, b"1")
        return process, barrier_write, lifeline_write

    def marker_script(self, *, sleep=60):
        marker = self.directory / "provider.json"
        return ("import json,os,pathlib,time; "
                f"pathlib.Path({str(marker)!r}).write_text(json.dumps({{'pid':os.getpid()}})); "
                f"time.sleep({sleep})")

    def test_absolute_deadline_kills_provider_and_guardian_without_coordinator_poll(self):
        # A long-lived coordinator and fresh Python 3.9 child on macOS have
        # different monotonic origins. Inject that offset on every platform.
        monotonic = time.monotonic
        with patch.object(time, "monotonic", side_effect=lambda: monotonic() + 100):
            process, _, _ = self.barrier_process(self.marker_script(), timeout=0.8)
        self.wait_until(lambda: (self.directory / "provider.json").exists(), "Provider did not start")
        self.assertEqual(len(self.live_group(process.pid)), 2)
        self.assertEqual(process.wait(timeout=3), -signal.SIGKILL)
        self.wait_until(lambda: not self.live_group(process.pid), "Deadline left a live process")

    def test_local_monotonic_deadline_survives_backward_wall_clock_jump(self):
        with patch.object(time, "time", return_value=500), \
             patch.object(time, "monotonic", return_value=61):
            self.assertLessEqual(delivery_planner_barrier._remaining(1000, 60), 0)

    def test_forward_wall_clock_jump_obeys_absolute_deadline(self):
        with patch.object(time, "time", return_value=1001), \
             patch.object(time, "monotonic", return_value=10):
            self.assertLessEqual(delivery_planner_barrier._remaining(1000, 60), 0)

    def test_unreleased_barrier_never_executes_and_lifeline_eof_kills_group(self):
        process, _, lifeline = self.barrier_process(self.marker_script(), release=False)
        self.wait_until(lambda: len(self.live_group(process.pid)) == 2, "Guardian did not start")
        self.assertFalse((self.directory / "provider.json").exists())
        # Close the only writer without relying on the coordinator's cleanup.
        self.close_descriptor(lifeline)
        self.assertEqual(process.wait(timeout=3), -signal.SIGKILL)
        self.wait_until(lambda: not self.live_group(process.pid), "Unreleased barrier leaked")
        self.assertFalse((self.directory / "provider.json").exists())

    def test_guardian_closes_inherited_stdio_before_provider_exec(self):
        process, _, _ = self.barrier_process("print('finished')")
        # The coordinator deliberately keeps its lifeline open. A guardian
        # retaining stdout/stderr would make communicate hang until the deadline.
        stdout, stderr = process.communicate(timeout=2)
        self.assertEqual((process.returncode, stdout, stderr), (0, b"finished\n", b""))
        self.assertEqual(len(self.live_group(process.pid)), 1)

    def test_guardian_survives_graceful_term_until_lifeline_closes(self):
        script = "import signal; signal.signal(signal.SIGTERM, signal.SIG_IGN); " + self.marker_script()
        process, _, lifeline = self.barrier_process(script)
        self.wait_until(lambda: (self.directory / "provider.json").exists(), "Provider did not start")
        os.killpg(process.pid, signal.SIGTERM)
        self.assertIsNone(process.poll())
        self.assertEqual(len(self.live_group(process.pid)), 2)
        self.close_descriptor(lifeline)
        self.assertEqual(process.wait(timeout=3), -signal.SIGKILL)
        self.wait_until(lambda: not self.live_group(process.pid), "Grace interval orphaned provider")

    def runtime_process(self, *, sleep=60, timeout=20):
        provider_marker = self.directory / "provider.json"
        provenance = self.directory / "started.json"
        executable = self.directory / "codex"
        executable.write_text(f"#!{sys.executable}\n" + "\n".join([
            "import json,os,pathlib,subprocess,sys,time",
            "sys.stdin.read()",
            "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])",
            f"pathlib.Path({str(provider_marker)!r}).write_text(json.dumps({{'pid':os.getpid(), 'child':child.pid, 'pgid':os.getpgrp()}}))",
            f"time.sleep({sleep})",
            "result = {'behavior': 'Saved idea'}",
            "print(json.dumps({'type':'item.completed', 'item': {'type':'agent_message', 'text': json.dumps(result)}}))",
            "print(json.dumps({'type':'turn.completed', 'usage':{}}))",
        ]) + "\n")
        executable.chmod(0o700)
        source = "\n".join([
            "import json,os,pathlib",
            "from scripts.factory_registry.delivery_runtime import run_readonly_planner",
            f"directory=pathlib.Path({str(self.directory)!r})",
            "def started(pid,pgid):",
            f"    pathlib.Path({str(provenance)!r}).write_text(json.dumps({{'pid':pid, 'pgid':pgid}}))",
            "run_readonly_planner(provider='openai', command=[str(directory/'codex'),'exec','-'],",
            " environment=dict(os.environ), prompt='Plan only', repository=directory,",
            " schema={'type':'object'}, log_directory=directory/'logs', on_start=started,",
            " on_result=lambda value,elapsed: None, monitor=lambda: None, validate_result=lambda value: None,",
            f" timeout_seconds={timeout}, monitor_interval=0.1)",
        ])
        process = subprocess.Popen([sys.executable, "-c", source],
            cwd=pathlib.Path(__file__).parents[2], start_new_session=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.addCleanup(self.cleanup_group, process)
        self.wait_until(provider_marker.exists, "Fake planner did not start")
        marker = json.loads(provider_marker.read_text())
        recorded = json.loads(provenance.read_text())
        self.assertEqual(recorded, {"pid": marker["pid"], "pgid": marker["pgid"]})
        def cleanup_provider_group():
            if self.live_group(marker["pgid"]):
                try:
                    os.killpg(marker["pgid"], signal.SIGKILL)
                except ProcessLookupError:
                    pass
        self.addCleanup(cleanup_provider_group)
        return process, marker

    def test_sigkill_of_real_coordinator_stops_provider_guardian_and_descendant(self):
        process, marker = self.runtime_process()
        members = self.live_group(marker["pgid"])
        self.assertEqual(len(members), 3)
        self.assertIn(marker["child"], [pid for pid, _ in members])
        os.kill(process.pid, signal.SIGKILL)
        process.wait(timeout=2)
        self.wait_until(lambda: not self.live_group(marker["pgid"]),
                        "Coordinator SIGKILL left orphan provider/guardian/child")
        self.assertFalse((self.directory / "logs" / "result.json").exists())

    def test_normal_runtime_completion_leaves_no_guardian_or_provider_descendant(self):
        process, marker = self.runtime_process(sleep=0.15)
        _, stderr = process.communicate(timeout=4)
        self.assertEqual(process.returncode, 0, stderr.decode())
        self.wait_until(lambda: not self.live_group(marker["pgid"]), "Normal completion leaked process")
        result = json.loads((self.directory / "logs" / "result.json").read_text())
        self.assertEqual(result["result"], {"behavior": "Saved idea"})


if __name__ == "__main__":
    unittest.main()
