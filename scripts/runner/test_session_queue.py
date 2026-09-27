import unittest
from types import SimpleNamespace

from session_queue import ordered_assignments


class SessionQueueTests(unittest.TestCase):
    def test_review_then_author_affine_remediation_then_backlog(self):
        snapshot = SimpleNamespace(work_packages=(
            {"id": "build", "kind": "PARENT", "status": "READY", "priority": 1},
            {"id": "fix", "kind": "PARENT", "status": "READY", "priority": 99,
             "provider_diagnostics": {"remediation_slot": True, "original_author_worker_id": "a"}},
            {"id": "review", "kind": "REVIEW", "status": "READY", "priority": 99},
        ))
        assignments = tuple(SimpleNamespace(package_id=package, worker_id=worker)
                            for package, worker in (("build", "b"), ("fix", "a"), ("review", "c")))
        self.assertEqual([(item.package_id, item.worker_id) for item in ordered_assignments(snapshot, assignments)],
                         [("review", "c"), ("fix", "a"), ("build", "b")])
