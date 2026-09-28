"""Publish one signed, read-only Registry snapshot to the hosted dashboard."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import hmac
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .control_center_projection import build_control_center_projection, serialize_control_center_projection
from .sqlite_registry import SQLiteRegistry

MAX_SNAPSHOT_BYTES = 1_048_576


def _publisher_secret(env_name: str, keychain_service: str) -> str:
    value = os.environ.get(env_name, "")
    if value:
        return value
    try:
        result = subprocess.run(["security", "find-generic-password", "-s", keychain_service, "-w"], check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError) as error:
        raise ValueError(f"{env_name} is not available in the environment or macOS Keychain") from error
    return result.stdout.strip()


def publish_snapshot(database: Path, endpoint: str, token: str, signing_secret: str) -> None:
    if not database.is_file():
        raise ValueError("Registry database does not exist")
    parsed = urlsplit(endpoint)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or parsed.fragment:
        raise ValueError("publisher endpoint must be an absolute HTTPS URL without credentials")
    if not token or len(signing_secret) < 32:
        raise ValueError("publisher token and signing secret are required")
    observed_at = datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    projection = serialize_control_center_projection(build_control_center_projection(SQLiteRegistry(database), observed_at=observed_at))
    body = gzip.compress(projection, compresslevel=6)
    if len(body) > MAX_SNAPSHOT_BYTES:
        raise ValueError("compressed Factory snapshot exceeds the 1 MiB limit")
    signature = hmac.new(signing_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    request = Request(endpoint, data=body, method="POST", headers={"Authorization": f"Bearer {token}", "Content-Type": "application/gzip", "X-Threadline-Factory-Signature": f"sha256={signature}"})
    try:
        with urlopen(request, timeout=20) as result:
            if result.status != 200:
                raise RuntimeError(f"snapshot upload failed with HTTP {result.status}")
    except HTTPError as error:
        raise RuntimeError(f"snapshot upload failed with HTTP {error.code}") from error
    except URLError as error:
        raise RuntimeError("snapshot upload could not reach the website") from error


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish one Factory dashboard snapshot")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--endpoint", required=True)
    args = parser.parse_args()
    try:
        publish_snapshot(args.database, args.endpoint, _publisher_secret("FACTORY_CONTROL_PUBLISH_TOKEN", "threadline-factory-dashboard-publish-token"), _publisher_secret("FACTORY_CONTROL_PROJECTION_SIGNING_SECRET", "threadline-factory-dashboard-signing-secret"))
    except (ValueError, RuntimeError) as error:
        parser.exit(1, f"{error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
