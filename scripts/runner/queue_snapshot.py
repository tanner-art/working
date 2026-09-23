"""Pure, local-only staging snapshot for already-fetched GitHub issue metadata."""
import fcntl
import json
import os
import pathlib
import tempfile

AGENTS = frozenset(('codex-a', 'codex-b', 'claude'))
STATUS_LABELS = (
    ('runner:failed', 'failed'), ('runner:review', 'review'),
    ('runner:running', 'running'), ('runner:ready', 'ready'),
)


def _label_names(value):
    if not isinstance(value, list):
        return set()
    names = set()
    for item in value:
        name = item if isinstance(item, str) else item.get('name') if isinstance(item, dict) else None
        if isinstance(name, str):
            names.add(name)
    return names


def _dependencies(value):
    if not isinstance(value, list):
        return []
    return sorted({item for item in value if isinstance(item, int) and not isinstance(item, bool) and item > 0})


def sanitize_queue_entry(issue):
    """Return a whitelisted queue entry, or None for malformed issue metadata.

    Bodies are deliberately never parsed: task instructions and credentials are
    not a dashboard/staging concern and cannot reach the persisted snapshot.
    """
    if not isinstance(issue, dict):
        return None
    number = issue.get('number')
    title = issue.get('title')
    if not isinstance(number, int) or isinstance(number, bool) or number <= 0 or not isinstance(title, str):
        return None
    labels = _label_names(issue.get('labels'))
    agents = sorted(name.removeprefix('agent:') for name in labels if name.startswith('agent:') and name.removeprefix('agent:') in AGENTS)
    agent = agents[0] if len(agents) == 1 else None
    status = next((status for label, status in STATUS_LABELS if label in labels), 'unqueued')
    created_at = issue.get('created_at')
    if not isinstance(created_at, str):
        created_at = None
    dependencies = _dependencies(issue.get('dependencies'))
    return {
        'number': number,
        'title': title,
        'agent': agent,
        'readiness': status == 'ready' and agent is not None,
        'status': status,
        'created_at': created_at,
        'dependencies': {'items': dependencies, 'count': len(dependencies)},
    }


def sanitize_queue_entries(issues):
    if not isinstance(issues, list):
        return []
    entries = [entry for issue in issues if (entry := sanitize_queue_entry(issue)) is not None]
    return sorted(entries, key=lambda entry: entry['number'])


def write_queue_snapshot(state, issues):
    """Atomically write only sanitized entries to ``state/queue.json``.

    A short advisory lock and same-directory temp file make concurrent writers
    produce one complete JSON document, never a partially written snapshot.
    """
    state = pathlib.Path(state)
    state.mkdir(parents=True, exist_ok=True)
    destination = state / 'queue.json'
    payload = json.dumps({'entries': sanitize_queue_entries(issues)}, separators=(',', ':'), sort_keys=True).encode() + b'\n'
    with open(state / 'queue.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        temporary_name = None
        try:
            with tempfile.NamedTemporaryFile(dir=state, prefix='.queue.json.', delete=False) as temporary:
                temporary_name = temporary.name
                temporary.write(payload)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_name, destination)
            directory = os.open(state, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if temporary_name:
                pathlib.Path(temporary_name).unlink(missing_ok=True)
            fcntl.flock(lock, fcntl.LOCK_UN)
    return destination
