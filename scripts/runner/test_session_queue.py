import unittest
from types import SimpleNamespace

from session_queue import ordered_assignments


class SessionQueueTests(unittest.TestCase):
    def test_ready_review_precedes_ready_parent_without_making_blocked_work_ready(self):
        snapshot = SimpleNamespace(work_packages=(
            {"id": "parent", "kind": "PARENT", "status": "READY", "priority": 99},
            {"id": "review", "kind": "REVIEW", "status": "READY", "priority": 1},
            {"id": "blocked", "kind": "PARENT", "status": "BLOCKED", "priority": 1000},
        ))
        assignments = tuple(SimpleNamespace(package_id=package, worker_id=worker)
                            for package, worker in (("parent", "builder"), ("review", "reviewer")))

        self.assertEqual(
            [(item.package_id, item.worker_id) for item in ordered_assignments(snapshot, assignments)],
            [("review", "reviewer"), ("parent", "builder")],
        )


if __name__ == "__main__":
    unittest.main()
