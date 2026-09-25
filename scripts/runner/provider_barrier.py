#!/usr/bin/env python3
"""Hold a provider command behind a parent-controlled, pre-exec barrier."""

import os
import sys


def main() -> int:
    if len(sys.argv) < 3:
        return 64
    barrier_fd = int(sys.argv[1])
    try:
        release = os.read(barrier_fd, 1)
    finally:
        os.close(barrier_fd)
    if release != b"1":
        return 75
    os.execvpe(sys.argv[2], sys.argv[2:], os.environ)
    return 70


if __name__ == "__main__":
    raise SystemExit(main())
