"""Loopback-only authenticated HTTP transport for Control Center projections."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import os
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Mapping
from urllib.parse import urlsplit

from .control_center_projection import (
    build_control_center_projection,
    serialize_control_center_projection,
)
from .repository import Registry
from .sqlite_registry import SQLiteRegistry


PROJECTION_PATH = "/v1/factory-control"
SIGNATURE_HEADER = "X-Threadline-Factory-Signature"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _authorized(headers: Mapping[str, str], token: str) -> bool:
    value = headers.get("Authorization", "")
    if not value.startswith("Bearer "):
        return False
    return hmac.compare_digest(value[7:].encode("utf-8"), token.encode("utf-8"))


def create_projection_handler(
    registry: Registry,
    *,
    bearer_token: str,
    signing_secret: str,
    now: Callable[[], str] = _utc_now,
) -> type[BaseHTTPRequestHandler]:
    """Create a stateless handler; every GET reads a fresh Registry revision."""
    if not bearer_token:
        raise ValueError("bearer token is required")
    if len(signing_secret) < 32:
        raise ValueError("signing secret must contain at least 32 characters")

    class ProjectionHandler(BaseHTTPRequestHandler):
        server_version = "ThreadlineFactoryProjection/1"

        def _headers(self, status: int, *, length: int, signature: str | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(length))
            self.send_header("Cache-Control", "private, no-store, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("X-Content-Type-Options", "nosniff")
            if signature is not None:
                self.send_header(SIGNATURE_HEADER, signature)
            self.end_headers()

        def _error(self, status: int, code: str) -> None:
            body = ("{\"error\":\"" + code + "\"}").encode("utf-8")
            self._headers(status, length=len(body))
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            if urlsplit(self.path).path != PROJECTION_PATH:
                self._error(404, "not_found")
                return
            if not _authorized(self.headers, bearer_token):
                self._error(401, "unauthorized")
                return
            try:
                projection = build_control_center_projection(registry, observed_at=now())
                body = serialize_control_center_projection(projection)
                digest = hmac.new(signing_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
            except Exception:
                self._error(503, "projection_unavailable")
                return
            self._headers(200, length=len(body), signature=f"sha256={digest}")
            self.wfile.write(body)

        def do_HEAD(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            self._error(405, "method_not_allowed")

        def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            self._error(405, "method_not_allowed")

        def do_PUT(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            self._error(405, "method_not_allowed")

        def do_DELETE(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            self._error(405, "method_not_allowed")

        def log_message(self, format: str, *args: object) -> None:
            # Avoid logging request targets, query values, or response bodies.
            return

    return ProjectionHandler


def serve_local_projection(
    registry: Registry,
    *,
    bearer_token: str,
    signing_secret: str,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> None:
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("projection transport must bind to loopback")
    handler = create_projection_handler(
        registry, bearer_token=bearer_token, signing_secret=signing_secret
    )
    server = ThreadingHTTPServer((host, port), handler)
    try:
        server.serve_forever()
    finally:
        server.server_close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve the read-only Factory Control Center projection")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    token = os.environ.get("FACTORY_CONTROL_PROJECTION_TOKEN", "")
    secret = os.environ.get("FACTORY_CONTROL_PROJECTION_SIGNING_SECRET", "")
    if not args.database.is_file():
        parser.error("--database must reference an existing Registry database")
    try:
        serve_local_projection(
            SQLiteRegistry(args.database), bearer_token=token,
            signing_secret=secret, host=args.host, port=args.port,
        )
    except ValueError as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
