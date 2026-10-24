"""Planner-only release barrier with an independent, process-group lifeline.

The coordinator passes only the read end of its private lifeline pipe. Its
exclusive writer is never inherited here or by the provider. A guardian stays
inside this fresh process group and kills that same group when the coordinator
dies or the absolute deadline expires. Membership prevents a stale
PID from making the guardian signal an unrelated, reused process group.
"""

from __future__ import annotations

import math
import os
import select
import signal
import sys
import time


def _kill_own_group() -> None:
    os.killpg(os.getpgrp(), signal.SIGKILL)
    os._exit(75)  # Defensive only: SIGKILL normally never returns.


def _remaining(deadline: float, local_deadline: float) -> float:
    # Wall time crosses process boundaries; monotonic origins do not on older
    # macOS Python. A local monotonic cap prevents a backward wall-clock jump
    # from extending execution indefinitely after this process starts.
    return min(deadline - time.time(), local_deadline - time.monotonic())


def _guardian(lifeline: int, ready: int, *, deadline: float, maximum_remaining: float,
              close_descriptors: tuple[int, ...]) -> None:
    try:
        local_deadline = time.monotonic() + min(maximum_remaining, deadline - time.time())
        # Survive the coordinator's graceful TERM interval. Otherwise a crash
        # during that interval could leave a TERM-resistant provider orphaned.
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        for descriptor in close_descriptors:
            os.close(descriptor)
        os.write(ready, b"1")
        os.close(ready)
        while True:
            remaining = _remaining(deadline, local_deadline)
            if remaining <= 0:
                break
            # Recheck wall-clock changes even while no lifeline event arrives.
            readable, _, _ = select.select([lifeline], [], [], min(remaining, 0.25))
            if readable:
                # The lifeline carries no data. EOF or unexpected data both
                # fail closed; only the coordinator holding the writer is safe.
                os.read(lifeline, 1)
                break
    except BaseException:
        pass
    _kill_own_group()


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        if len(argv) < 4:
            return 64
        barrier, lifeline = int(argv[0]), int(argv[1])
        deadline = float(argv[2])
        remaining = deadline - time.time()
        if (barrier < 3 or lifeline < 3 or barrier == lifeline
                or not math.isfinite(deadline) or not 0 < remaining <= 3600
                or os.getpid() != os.getpgrp() or os.getpid() != os.getsid(0)):
            return 64
        os.fstat(barrier)
        os.fstat(lifeline)
    except (OSError, ValueError):
        return 64

    local_deadline = time.monotonic() + remaining
    ready_read, ready_write = os.pipe()
    try:
        guardian = os.fork()
    except OSError:
        os.close(ready_read)
        os.close(ready_write)
        return 75
    if guardian == 0:
        _guardian(lifeline, ready_write, deadline=deadline,
                  maximum_remaining=_remaining(deadline, local_deadline),
                  close_descriptors=(0, 1, 2, barrier, ready_read))
        os._exit(75)

    os.close(ready_write)
    try:
        # No provider is released until its guardian has installed the signal
        # policy and closed inherited stdio (which would retain PIPE handles).
        wait = min(5.0, max(0.0, _remaining(deadline, local_deadline)))
        readable, _, _ = select.select([ready_read], [], [], wait)
        if not readable or os.read(ready_read, 1) != b"1":
            _kill_own_group()
        os.close(ready_read)
        release = os.read(barrier, 1)
        os.close(barrier)
        if release != b"1":
            _kill_own_group()
        # A dead guardian before exec must never permit provider work. After
        # exec, the coordinator remains the second supervisor; the guardian
        # independently covers coordinator death, not deliberate guardian kill.
        if os.waitpid(guardian, os.WNOHANG)[0] or _remaining(deadline, local_deadline) <= 0:
            _kill_own_group()
        os.close(lifeline)
        os.execvpe(argv[3], argv[3:], os.environ)
    except BaseException:
        _kill_own_group()
    return 75


if __name__ == "__main__":
    raise SystemExit(main())
