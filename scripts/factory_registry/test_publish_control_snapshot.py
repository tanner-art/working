import hashlib
import hmac
import gzip
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from .publish_control_snapshot import publish_snapshot


class PublishControlSnapshotTests(unittest.TestCase):
    def test_rejects_insecure_endpoint_before_reading_registry(self):
        with tempfile.NamedTemporaryFile() as database:
            with self.assertRaisesRegex(ValueError, "HTTPS URL"):
                publish_snapshot(Path(database.name), "http://example.test/api/factory-control", "token", "x" * 32)

    @patch("scripts.factory_registry.publish_control_snapshot.urlopen")
    @patch("scripts.factory_registry.publish_control_snapshot.serialize_control_center_projection", return_value=b'{"schemaVersion":2}')
    @patch("scripts.factory_registry.publish_control_snapshot.build_control_center_projection", return_value={})
    @patch("scripts.factory_registry.publish_control_snapshot.SQLiteRegistry")
    def test_posts_exact_signed_body(self, _registry, _build, _serialize, urlopen):
        result = MagicMock()
        result.status = 200
        urlopen.return_value.__enter__.return_value = result
        with tempfile.NamedTemporaryFile() as database:
            publish_snapshot(Path(database.name), "https://threadline.test/api/factory-control", "token", "s" * 32)
        request = urlopen.call_args.args[0]
        body = request.data
        expected = hmac.new(b"s" * 32, body, hashlib.sha256).hexdigest()
        self.assertEqual(gzip.decompress(body), b'{"schemaVersion":2}')
        self.assertEqual(request.get_header("Authorization"), "Bearer token")
        self.assertEqual(request.get_header("X-threadline-factory-signature"), f"sha256={expected}")


if __name__ == "__main__":
    unittest.main()
