#!/usr/bin/env python3
"""Always-viewable local HTTP dashboard over the runner's state directory.

Serves a single-page dashboard (factory_dashboard.html) plus a JSON API
(/api/status) built entirely from local, non-secret runner telemetry:

  - <state>/heartbeat.json         -- overall runner liveness (see factory_status.py)
  - <state>/heartbeat-<agent>.json -- OPTIONAL per-lane heartbeat for a single
                                       concurrent worker, written by runner.py
                                       for each agent lane: {"time": <unix
                                       seconds>, "status": "<str>", "issue":
                                       <int, optional>, "task": "<str,
                                       optional>", "start_time": <unix
                                       seconds, optional>}. Missing or corrupt
                                       per-lane heartbeats fall back safely to
                                       the worker's latest issue-N.json record
                                       and events.jsonl entries.
  - <state>/issue-N.json           -- one record per queue issue the runner has
                                       touched (see runner.py save())
  - <state>/events.jsonl           -- append-only, newline-delimited JSON log
                                       of per-agent status changes over time,
                                       one concurrent worker lane per line,
                                       written by runner.py:
                                         {"timestamp": <unix seconds>,
                                          "agent": "<str>", "status": "<str>",
                                          "issue": <int, optional>,
                                          "title": "<str, optional>",
                                          "elapsed_seconds": <number, optional>,
                                          "files_changed": <int, optional>,
                                          "additions": <int, optional>,
                                          "deletions": <int, optional>,
                                          "validation_result": "<str, optional>",
                                          "commit": "<str, optional>",
                                          "pr": "<str, optional>"}
                                       "status" uses the same vocabulary as
                                       heartbeat.json/issue-N.json ("idle",
                                       "polling", "starting", "agent",
                                       "validation", "review", "failed") plus
                                       "waiting" for a dependency-blocked task.
                                       Each agent has its own independent
                                       timeline, and multiple agents' active
                                       intervals may overlap (this is a
                                       concurrent, not serial, execution
                                       model -- see the utilization section
                                       below). A worker's "active" interval
                                       runs from a "starting"/"agent"/
                                       "validation" event until its next
                                       "review"/"failed"/"idle" event for that
                                       same agent. Utilization and "longest
                                       blocked" are computed per-agent
                                       timeline, never by merging events from
                                       different agents into one sequence.
  - <state>/usage.json             -- provider usage snapshot written by
                                       usage_policy.py, keyed by worker and
                                       account, optionally wrapped in a
                                       "workers" object:
                                         {"workers": {
                                           "codex-a": {"primary":
                                             {"provider": "openai",
                                              "model": "gpt-5-codex",
                                              "used_percent": 42.5,
                                              "observed_at": "<ISO 8601>",
                                              "reset_at": "<ISO 8601, optional>"}}
                                         }}
                                       The wrapper is optional. For local
                                       migration, the older flat worker-to-record
                                       shape is also accepted as account
                                       "default". This dashboard only displays
                                       what is recorded here; it never queries
                                       any provider API itself.

Never reads or displays credentials, tokens, or per-attempt log file
contents (state/issue-N-<attempt>.log may contain source code). Only the
'state' and 'agents' fields of the runner config are read; 'agents' entries
are only inspected for the non-secret descriptive fields 'provider', 'model',
and 'label' -- never for 'command' or 'env'. Worker/provider/model
definitions come entirely from the config file, never hardcoded here.

If a data source is missing or corrupt, every section degrades to an
explicit "Unknown" with a plain-language explanation of what data would be
needed, rather than inventing a value.
"""
import argparse
import json
import math
import pathlib
import re
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import factory_status as fstatus

DEFAULT_HOST = '127.0.0.1'
DEFAULT_PORT = 8787
REFRESH_SECONDS = 10

DEFAULT_STALE_AFTER_SECONDS = fstatus.DEFAULT_STALE_AFTER_SECONDS
DEFAULT_UTILIZATION_WINDOW_DAYS = fstatus.DEFAULT_UTILIZATION_WINDOW_DAYS
DEFAULT_UTILIZATION_TARGET_WORKERS = fstatus.DEFAULT_UTILIZATION_TARGET_WORKERS

DEFAULT_SLOWDOWN_THRESHOLD_PCT = 70.0
DEFAULT_STOP_THRESHOLD_PCT = 80.0
MAX_STOP_THRESHOLD_PCT = 80.0
DEFAULT_USAGE_STALE_AFTER_SECONDS = 3600.0

ACTIVE_STATUSES = {'starting', 'agent', 'validation'}
REVIEW_STATUS = 'review'
FAILED_STATUS = 'failed'
BLOCKED_STATUSES = {'waiting', 'blocked'}
BUSY_STATUSES = ACTIVE_STATUSES
QUEUE_STATUSES = frozenset(('failed', 'review', 'running', 'ready', 'unqueued'))
QUEUE_AGENTS = frozenset(('codex-a', 'codex-b', 'claude'))
QUEUE_ENTRY_FIELDS = frozenset(('number', 'title', 'agent', 'readiness', 'status', 'created_at', 'dependencies'))

# Config fields this dashboard is allowed to read. Everything else in the
# config file (repo path, gh/git/pnpm executables, allowed_authors, per-agent
# command/env) is ignored so it can never leak into the report.
_ALLOWED_AGENT_FIELDS = ('provider', 'model', 'label')

HTML_PATH = pathlib.Path(__file__).resolve().parent / 'factory_dashboard.html'
_SAFE_PR_HOST = 'github.com'
_PATH_LIKE = re.compile(r'(^~(?:/|\\)|^[A-Za-z]:[\\/]|^/|[\\])')
_CONTROL_CHARS = re.compile(r'[\x00-\x1f\x7f]')


def safe_display_identifier(value, *, fallback=None):
    """Keep ordinary labels while rejecting path-like or control-bearing data."""
    if not isinstance(value, str):
        return fallback
    value = value.strip()
    if not value or len(value) > 120 or _CONTROL_CHARS.search(value) or _PATH_LIKE.search(value):
        return fallback
    return value


def safe_pr_url(value):
    """Return only canonical HTTPS GitHub PR URLs, without query/fragment data."""
    if not isinstance(value, str):
        return None
    try:
        parsed = urllib.parse.urlsplit(value.strip())
    except ValueError:
        return None
    if parsed.scheme != 'https' or parsed.hostname != _SAFE_PR_HOST or parsed.username or parsed.password:
        return None
    if not re.fullmatch(r'/[^/]+/[^/]+/pull/[1-9][0-9]*(?:/[^/]*)?', parsed.path):
        return None
    return f'https://{_SAFE_PR_HOST}{parsed.path}'


def safe_public_error(value):
    """Expose a coarse failure reason without returning raw subprocess telemetry."""
    if not isinstance(value, str) or not value.strip():
        return None
    lower = value.lower()
    if 'timeout' in lower or 'timed out' in lower:
        return 'agent timed out'
    if 'auth' in lower or 'credential' in lower or 'login' in lower:
        return 'authentication failed'
    if 'pnpm' in lower or 'npm' in lower or 'yarn' in lower or 'validation' in lower:
        return 'validation failed'
    return 'operation failed'


def format_duration(seconds):
    if seconds is None:
        return None
    seconds = max(0, int(seconds))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f'{days}d')
    if hours or days:
        parts.append(f'{hours}h')
    if minutes or hours or days:
        parts.append(f'{minutes}m')
    parts.append(f'{secs}s')
    return ' '.join(parts)


def agent_definitions(config):
    """Data-driven worker/provider/model definitions from config['agents'].

    Only the non-secret descriptive fields are read. Command lines and
    environment variables are never inspected or exposed.
    """
    agents = config.get('agents')
    result = {}
    if not isinstance(agents, dict):
        return result
    for key, value in agents.items():
        safe_key = safe_display_identifier(key)
        if safe_key is None:
            continue
        entry = {'key': safe_key, 'provider': None, 'model': None, 'label': None}
        if isinstance(value, dict):
            for field in _ALLOWED_AGENT_FIELDS:
                v = value.get(field)
                if isinstance(v, str) and v:
                    entry[field] = safe_display_identifier(v)
        result[safe_key] = entry
    return result


def usage_policy(config, slowdown_override=None, stop_override=None):
    """Read usage_policy.py's canonical percentages, with legacy aliases.

    Only numeric threshold fields are consumed. This keeps arbitrary runner
    configuration, including commands and credentials, out of the report.
    """
    configured = config.get('usage_policy')
    slowdown = DEFAULT_SLOWDOWN_THRESHOLD_PCT
    stop = DEFAULT_STOP_THRESHOLD_PCT
    stale_after = DEFAULT_USAGE_STALE_AFTER_SECONDS
    if isinstance(configured, dict):
        # usage_policy.py writes these canonical names. The dashboard accepts
        # its original names for existing local configs, but canonical values
        # win when both are present.
        v = configured.get('slowdown_percent', configured.get('slowdown_threshold_pct'))
        if isinstance(v, (int, float)):
            slowdown = float(v)
        v = configured.get('stop_percent', configured.get('stop_threshold_pct'))
        if isinstance(v, (int, float)):
            stop = float(v)
        v = configured.get('stale_after_seconds')
        if isinstance(v, (int, float)):
            stale_after = float(v)
    if isinstance(slowdown_override, (int, float)):
        slowdown = float(slowdown_override)
    if isinstance(stop_override, (int, float)):
        stop = float(stop_override)
    clamped = stop > MAX_STOP_THRESHOLD_PCT
    if clamped:
        stop = MAX_STOP_THRESHOLD_PCT
    return {
        'slowdown_percent': slowdown,
        'stop_percent': stop,
        # Kept for the existing dashboard API and command-line integrations.
        'slowdown_threshold_pct': slowdown,
        'stop_threshold_pct': stop,
        'stop_threshold_clamped_to_max': clamped,
        'max_stop_threshold_pct': MAX_STOP_THRESHOLD_PCT,
        'stale_after_seconds': stale_after,
    }


def classify_usage_state(percent_used, policy, observed_at_seconds=None, now=None):
    if not isinstance(percent_used, (int, float)):
        return 'unknown'
    if now is not None:
        if observed_at_seconds is None:
            return 'unknown'
        stale_after = policy.get('stale_after_seconds', DEFAULT_USAGE_STALE_AFTER_SECONDS)
        if not isinstance(stale_after, (int, float)) or now < observed_at_seconds or now - observed_at_seconds > stale_after:
            return 'unknown'
    stop = policy.get('stop_percent', policy.get('stop_threshold_pct', DEFAULT_STOP_THRESHOLD_PCT))
    slowdown = policy.get('slowdown_percent', policy.get('slowdown_threshold_pct', DEFAULT_SLOWDOWN_THRESHOLD_PCT))
    if percent_used >= stop:
        return 'stop'
    if percent_used >= slowdown:
        return 'slow'
    return 'green'


def _parse_iso(value):
    """Parse an ISO 8601 string into unix seconds, or None if unparseable."""
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    if text.endswith('Z'):
        text = text[:-1] + '+00:00'
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def load_usage(state_dir, policy, now=None):
    path = state_dir / 'usage.json'
    data, error = fstatus.read_json_safe(path)
    if error == 'missing':
        return {
            'found': False, 'error': None, 'workers': [], 'corrupt_workers': 0,
            'note': (
                'usage.json not found in the state directory. This dashboard cannot '
                'query provider usage itself; create usage.json with '
                '{"<worker>": {"<account>": {"provider": "...", '
                '"model": "...", '
                '"used_percent": <0-100>, "observed_at": "<ISO 8601>", '
                '"reset_at": "<ISO 8601, optional>"}}} (optionally wrapped '
                'in {"workers": {...}}) to show real usage.'
            ),
        }
    if error:
        return {'found': True, 'error': error, 'workers': [], 'corrupt_workers': 0, 'note': None}
    if isinstance(data, dict) and isinstance(data.get('workers'), dict):
        raw_workers = data['workers']
    elif isinstance(data, dict):
        raw_workers = data
    else:
        raw_workers = None
    if not isinstance(raw_workers, dict):
        return {
            'found': True,
            'error': "corrupt: usage.json must be an object keyed by worker (optionally wrapped in {\"workers\": {...}})",
            'workers': [], 'corrupt_workers': 0, 'note': None,
        }
    observed_now = time.time() if now is None else now
    result = []
    corrupt = 0
    for worker_key, raw_accounts in raw_workers.items():
        if not isinstance(worker_key, str) or not worker_key or not isinstance(raw_accounts, dict):
            corrupt += 1
            continue
        # usage_policy.py's canonical shape is worker -> account -> record.
        # Keep accepting the original flat worker -> record shape as the
        # worker's default account during local migration.
        record_keys = ('provider', 'model', 'used_percent', 'observed_at', 'reset_at')
        is_flat_record = any(key in raw_accounts and not isinstance(raw_accounts[key], dict)
                             for key in record_keys)
        accounts = {'default': raw_accounts} if is_flat_record else raw_accounts
        for account_key, entry in accounts.items():
            if not isinstance(account_key, str) or not account_key or not isinstance(entry, dict):
                corrupt += 1
                continue
            used_percent = entry.get('used_percent')
            if not isinstance(used_percent, (int, float)) or isinstance(used_percent, bool) or not math.isfinite(float(used_percent)):
                used_percent = None
            observed_at = entry.get('observed_at') if isinstance(entry.get('observed_at'), str) else None
            observed_at_seconds = _parse_iso(observed_at)
            reset_at = entry.get('reset_at') if isinstance(entry.get('reset_at'), str) else None
            reset_at_seconds = _parse_iso(reset_at)
            result.append({
                'worker': safe_display_identifier(worker_key, fallback='unknown-worker'),
                'account': safe_display_identifier(account_key, fallback='unknown-account'),
                'provider': safe_display_identifier(entry.get('provider')),
                'model': safe_display_identifier(entry.get('model')),
                'used_percent': used_percent,
                'observed_at': fstatus.iso(observed_at_seconds) if observed_at_seconds is not None else None,
                'observed_at_seconds': observed_at_seconds,
                'reset_at': fstatus.iso(reset_at_seconds) if reset_at_seconds is not None else None,
                'reset_at_seconds': reset_at_seconds,
                'state': classify_usage_state(used_percent, policy, observed_at_seconds, observed_now),
            })
    result.sort(key=lambda w: (w['worker'], w['account']))
    return {'found': True, 'error': None, 'workers': result, 'corrupt_workers': corrupt, 'note': None}


def load_issue_records(state_dir):
    """Return (records, corrupt_count). records is issue_number -> safe dict."""
    records = {}
    corrupt = 0
    if not state_dir.is_dir():
        return records, corrupt
    for entry in sorted(state_dir.iterdir()):
        if not entry.is_file():
            continue
        m = fstatus.ISSUE_RECORD_RE.match(entry.name)
        if not m:
            continue
        data, error = fstatus.read_json_safe(entry)
        if error or not isinstance(data, dict):
            corrupt += 1
            continue
        issue_number = data.get('issue')
        if not isinstance(issue_number, int):
            issue_number = int(m.group(1))
        status = data.get('status')
        rec_time = data.get('time')
        diff_stat = _safe_diff_stat(data.get('diff_stat'))
        records[issue_number] = {
            'issue': issue_number,
            'status': status if isinstance(status, str) and status else 'unknown',
            'time': rec_time if isinstance(rec_time, (int, float)) else None,
            'agent': safe_display_identifier(data.get('agent')),
            'branch': safe_display_identifier(data.get('branch')),
            'commit': data.get('commit') if isinstance(data.get('commit'), str) else None,
            'pr': safe_pr_url(data.get('pr')),
            'error': safe_public_error(data.get('error')),
            'diff_stat': diff_stat,
        }
    return records, corrupt


def load_queue_snapshot(state_dir):
    path = state_dir / 'queue.json'
    data, error = fstatus.read_json_safe(path)
    if error == 'missing':
        return {'found': False, 'error': None, 'entries': []}
    if error or not isinstance(data, dict) or set(data) != {'entries'} or not isinstance(data.get('entries'), list):
        return {'found': True, 'error': error or 'corrupt: queue.json entries must be a list', 'entries': []}
    entries = []
    numbers = set()
    for item in data['entries']:
        if not isinstance(item, dict) or set(item) != QUEUE_ENTRY_FIELDS:
            return {'found': True, 'error': 'corrupt: queue.json entry has an invalid schema', 'entries': []}
        number = item.get('number')
        status = item.get('status')
        title = item.get('title')
        agent = item.get('agent')
        readiness = item.get('readiness')
        created_at = item.get('created_at')
        dependencies = item.get('dependencies')
        if (isinstance(number, bool) or not isinstance(number, int) or number <= 0 or not isinstance(title, str) or
                status not in QUEUE_STATUSES or agent not in QUEUE_AGENTS | {None} or not isinstance(readiness, bool) or
                not (isinstance(created_at, str) or created_at is None) or not isinstance(dependencies, dict) or
                set(dependencies) != {'items', 'count'} or not isinstance(dependencies['items'], list) or
                isinstance(dependencies['count'], bool) or not isinstance(dependencies['count'], int) or
                any(isinstance(dep, bool) or not isinstance(dep, int) or dep <= 0 for dep in dependencies['items']) or
                dependencies['items'] != sorted(set(dependencies['items'])) or dependencies['count'] != len(dependencies['items']) or
                readiness != (status == 'ready' and agent is not None) or number in numbers or
                (created_at is not None and _parse_iso(created_at) is None)):
            return {'found': True, 'error': 'corrupt: queue.json entry has invalid canonical values', 'entries': []}
        numbers.add(number)
        entries.append({
            'number': number,
            'title': title,
            'agent': agent,
            'readiness': readiness,
            'status': status,
            'created_at': created_at,
        })
    return {'found': True, 'error': None, 'entries': entries}


def queue_view(snapshot, issue_summary, records, now):
    if snapshot['found'] and snapshot['error'] is None:
        entries = snapshot['entries']
        by_status = {}
        for entry in entries:
            by_status[entry['status']] = by_status.get(entry['status'], 0) + 1
        created = [_parse_iso(entry['created_at']) for entry in entries]
        created = [value for value in created if value is not None]
        oldest = min(created) if created else None
        age = max(0.0, now - oldest) if oldest is not None else None
        return {
            'source': 'queue.json', 'by_status': by_status, 'by_agent': {},
            'total_records': len(entries), 'corrupt_records': 0,
            'staged_count': len(entries), 'ready_count': sum(entry['readiness'] is True for entry in entries),
            'running_count': by_status.get('running', 0), 'review_count': by_status.get('review', 0),
            'failure_count': by_status.get('failed', 0), 'queue_age_seconds': age,
            'queue_age_human': format_duration(age), 'snapshot_error': None,
            'note': 'Counts and queue age come from the sanitized queue.json snapshot.',
        }
    times = [record['time'] for record in records.values() if record['time'] is not None]
    oldest = min(times) if times else None
    age = max(0.0, now - oldest) if oldest is not None else None
    return {
        'source': 'issue-records', 'by_status': issue_summary['by_status'], 'by_agent': issue_summary['by_agent'],
        'total_records': issue_summary['total_records'], 'corrupt_records': issue_summary['corrupt_records'],
        'staged_count': issue_summary['total_records'], 'ready_count': issue_summary['by_status'].get('ready', 0),
        'running_count': issue_summary['by_status'].get('running', 0), 'review_count': issue_summary['by_status'].get(REVIEW_STATUS, 0),
        'failure_count': issue_summary['by_status'].get(FAILED_STATUS, 0), 'queue_age_seconds': age,
        'queue_age_human': format_duration(age), 'snapshot_error': snapshot['error'],
        'note': 'queue.json unavailable; counts and queue age reflect only locally touched issue records.',
    }


def _safe_diff_stat(value):
    if not isinstance(value, dict):
        return None
    out = {}
    for field in ('additions', 'deletions', 'files_changed'):
        v = value.get(field)
        if isinstance(v, int) and not isinstance(v, bool) and v >= 0:
            out[field] = v
    return out or None


def load_worker_heartbeat(state_dir, key):
    """Per-lane heartbeat for a single agent (state/heartbeat-<agent>.json).

    Reads the same fields runner.py actually writes: 'time', 'status',
    'issue', 'task', and 'start_time'. Falls back safely: a missing or
    corrupt file, or one without a usable 'status' field, is reported as not
    usable so callers can fall back to issue-N.json / events.jsonl inference
    instead.
    """
    path = state_dir / f'heartbeat-{key}.json'
    data, error = fstatus.read_json_safe(path)
    if error == 'missing':
        return {'found': False, 'error': None, 'time': None, 'status': None,
                'issue': None, 'task': None, 'start_time': None}
    if error or not isinstance(data, dict):
        return {'found': True, 'error': error or 'corrupt: not a JSON object', 'time': None,
                'status': None, 'issue': None, 'task': None, 'start_time': None}
    ts = data.get('time')
    if not isinstance(ts, (int, float)) or isinstance(ts, bool):
        ts = None
    status = data.get('status')
    issue_num = data.get('issue')
    if isinstance(issue_num, bool) or not isinstance(issue_num, int):
        issue_num = None
    task = data.get('task')
    start_time = data.get('start_time')
    if not isinstance(start_time, (int, float)) or isinstance(start_time, bool):
        start_time = None
    return {
        'found': True,
        'error': None,
        'time': float(ts) if ts is not None else None,
        'status': status if isinstance(status, str) and status else None,
        'issue': issue_num,
        'task': task if isinstance(task, str) and task else None,
        'start_time': float(start_time) if start_time is not None else None,
    }


def load_events(state_dir):
    path = state_dir / 'events.jsonl'
    if not path.is_file():
        return {'found': False, 'error': None, 'events': [], 'corrupt_lines': 0}
    try:
        raw = path.read_text()
    except OSError as e:
        return {'found': True, 'error': f'unreadable: {e.__class__.__name__}', 'events': [], 'corrupt_lines': 0}
    events = []
    corrupt = 0
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            corrupt += 1
            continue
        if not isinstance(obj, dict) or not isinstance(obj.get('timestamp'), (int, float)) \
                or isinstance(obj.get('timestamp'), bool) \
                or not isinstance(obj.get('status'), str) or not obj['status']:
            corrupt += 1
            continue
        event = {'time': float(obj['timestamp']), 'status': obj['status']}
        issue_num = obj.get('issue')
        if isinstance(issue_num, int) and not isinstance(issue_num, bool):
            event['issue'] = issue_num
        if isinstance(obj.get('agent'), str) and obj['agent']:
            event['agent'] = obj['agent']
        if isinstance(obj.get('title'), str) and obj['title']:
            event['title'] = obj['title']
        elapsed_seconds = obj.get('elapsed_seconds')
        if isinstance(elapsed_seconds, (int, float)) and not isinstance(elapsed_seconds, bool):
            event['elapsed_seconds'] = float(elapsed_seconds)
        if isinstance(obj.get('validation_result'), str) and obj['validation_result']:
            event['validation_result'] = obj['validation_result']
        if isinstance(obj.get('commit'), str) and obj['commit']:
            event['commit'] = obj['commit']
        if isinstance(obj.get('pr'), str) and obj['pr']:
            event['pr'] = obj['pr']
        diff_stat = _safe_diff_stat({
            k: obj.get(k) for k in ('additions', 'deletions', 'files_changed')
        })
        if diff_stat:
            event['diff_stat'] = diff_stat
        events.append(event)
    events.sort(key=lambda e: e['time'])
    return {'found': True, 'error': None, 'events': events, 'corrupt_lines': corrupt}


def _group_events_by_agent(events):
    grouped = {}
    for event in events:
        agent = event.get('agent')
        if not agent:
            continue
        grouped.setdefault(agent, []).append(event)
    return grouped


def compute_intervals(events, now):
    """[(start, end, status), ...] covering from the first event to `now`.

    `events` must already be a single agent's timeline (see
    `_group_events_by_agent`); events from different concurrent agents must
    never be merged into one sequence before calling this.
    """
    if not events:
        return []
    ordered = sorted(events, key=lambda e: e['time'])
    intervals = []
    for i, ev in enumerate(ordered):
        start = ev['time']
        end = ordered[i + 1]['time'] if i + 1 < len(ordered) else now
        if end < start:
            end = start
        intervals.append((start, end, ev['status']))
    return intervals


def _busy_seconds(intervals, window_start, window_end, busy_statuses):
    total = 0.0
    for start, end, status in intervals:
        if status not in busy_statuses:
            continue
        s = max(start, window_start)
        e = min(end, window_end)
        if e > s:
            total += e - s
    return total


def average_active_workers_for_window(events_result, now, window_start, window_end, total_workers,
                                       busy_statuses=BUSY_STATUSES):
    """Average number of concurrently-active workers over a window.

    Each agent's timeline is computed independently (its active interval runs
    from a "starting"/"agent"/"validation" event until its next
    "review"/"failed"/"idle" event), then busy-seconds are summed across all
    agents so overlapping concurrent workers add up rather than clobbering
    each other. The result is workers-in-use (0..total_workers), not a
    fraction of a single serial timeline. Never extrapolates before the
    first recorded telemetry: the window is clamped to start no earlier than
    the first event across all agents.
    """
    if not events_result['found']:
        return {
            'value': None, 'percent_of_capacity': None, 'reason': (
                'events.jsonl not found; utilization requires an append-only history of '
                'per-agent status-change events with timestamp/agent/status fields '
                '(see factory_dashboard.py docstring)'
            ),
        }
    if events_result['error']:
        return {'value': None, 'percent_of_capacity': None, 'reason': f"events.jsonl {events_result['error']}"}
    events = events_result['events']
    if not events:
        return {'value': None, 'percent_of_capacity': None,
                'reason': 'events.jsonl is empty; no status history to compute utilization from'}
    first_event_time = min(e['time'] for e in events)
    effective_start = max(window_start, first_event_time)
    if effective_start >= window_end:
        return {'value': None, 'percent_of_capacity': None, 'reason': 'no recorded events fall within the requested window'}
    duration = window_end - effective_start
    if duration <= 0:
        return {'value': None, 'percent_of_capacity': None, 'reason': 'requested window has zero or negative duration'}
    total_busy = 0.0
    for agent_events in _group_events_by_agent(events).values():
        intervals = compute_intervals(agent_events, now)
        total_busy += _busy_seconds(intervals, effective_start, window_end, busy_statuses)
    average_workers = total_busy / duration
    return {
        'value': average_workers,
        'percent_of_capacity': (average_workers / total_workers) if total_workers else None,
        'window_start': effective_start,
        'window_start_iso': fstatus.iso(effective_start),
        'window_end': window_end,
        'window_end_iso': fstatus.iso(window_end),
    }


def longest_blocked_duration(events_result, now, blocked_statuses=BLOCKED_STATUSES):
    if not events_result['found']:
        return {
            'value': None, 'reason': (
                'events.jsonl not found; blocked duration requires a "waiting"/"blocked" '
                'status event (issue-N.json never persists this state -- see runner.py)'
            ),
        }
    if events_result['error']:
        return {'value': None, 'reason': f"events.jsonl {events_result['error']}"}
    events = events_result['events']
    if not events:
        return {'value': None, 'reason': 'events.jsonl is empty; no status history recorded'}
    best = None
    for agent_events in _group_events_by_agent(events).values():
        for start, end, status in compute_intervals(agent_events, now):
            if status in blocked_statuses:
                dur = end - start
                if best is None or dur > best:
                    best = dur
    if best is None:
        return {'value': None, 'reason': 'no waiting/blocked events recorded'}
    return {'value': best}


def _diff_stat_for_issue(record, events):
    if record.get('diff_stat'):
        return record['diff_stat'], None
    matches = [e for e in events if e.get('issue') == record['issue'] and e.get('diff_stat')]
    if matches:
        return sorted(matches, key=lambda e: e['time'])[-1]['diff_stat'], None
    return None, f"no diff-stat recorded for issue #{record['issue']} (needs a diff_stat field on the issue record or a matching events.jsonl entry)"


def validation_result(record):
    status = record['status']
    if status == FAILED_STATUS:
        return 'failed'
    if status in (REVIEW_STATUS,) or record.get('commit'):
        return 'passed'
    if status == 'validation':
        return 'running'
    if status in ('starting', 'agent'):
        return 'pending'
    return 'unknown'


def completion_metadata(record):
    if record.get('status') != REVIEW_STATUS:
        return None
    return {
        'issue': record['issue'],
        'time_iso': fstatus.iso(record['time']),
        'commit': record.get('commit'),
        'pr': safe_pr_url(record.get('pr')),
        'validation_result': validation_result(record),
    }


def build_issue_views(records, events, now):
    views = []
    for issue_number in sorted(records):
        record = records[issue_number]
        elapsed = None
        if record['status'] in ACTIVE_STATUSES or record['status'] in BLOCKED_STATUSES:
            if record['time'] is not None:
                elapsed = max(0.0, now - record['time'])
        completed_at = fstatus.iso(record['time']) if record['status'] == REVIEW_STATUS else None
        diff_stat, diff_stat_reason = _diff_stat_for_issue(record, events)
        views.append({
            'issue': record['issue'],
            'status': record['status'],
            'agent': record['agent'],
            'branch': record['branch'],
            'commit': record['commit'],
            'pr': safe_pr_url(record['pr']),
            'error': safe_public_error(record['error']),
            'started_at_iso': fstatus.iso(record['time']),
            'completed_at_iso': completed_at,
            'elapsed_seconds': elapsed,
            'elapsed_human': format_duration(elapsed),
            'validation_result': validation_result(record),
            'diff_stat': diff_stat,
            'diff_stat_reason': diff_stat_reason,
        })
    return views


def build_worker_views(agent_defs, records, events, heartbeat, now):
    """Build the per-worker view.

    `heartbeat` is a dict of {agent_key: load_worker_heartbeat(...) result}.
    When a per-lane heartbeat is present, valid, and carries a usable
    'status', it is the primary source for that worker's live status/current
    task/runtime. When it is missing, corrupt, or has no usable status, this
    falls back safely to the worker's latest issue-N.json record plus its
    own events.jsonl timeline, exactly as before per-lane heartbeats existed.
    """
    heartbeat = heartbeat if isinstance(heartbeat, dict) else {}
    workers = []
    for key in sorted(agent_defs):
        definition = agent_defs[key]
        latest_record = None
        for record in records.values():
            if record['agent'] != key or record['time'] is None:
                continue
            if latest_record is None or record['time'] > latest_record['time']:
                latest_record = record
        latest_event = None
        for event in events:
            if event.get('agent') != key:
                continue
            if latest_event is None or event['time'] > latest_event['time']:
                latest_event = event

        record_time = latest_record['time'] if latest_record else None
        event_time = latest_event['time'] if latest_event else None
        worker = {
            'key': key,
            'provider': definition['provider'],
            'model': definition['model'],
            'label': definition['label'],
            'state': 'idle',
            'current_issue': None,
            'elapsed_seconds': None,
            'elapsed_human': None,
            'last_failure': None,
            'last_completion': None,
            'reason': 'no recorded activity for this worker yet' if latest_record is None and latest_event is None else None,
        }

        hb = heartbeat.get(key)
        if isinstance(hb, dict) and hb.get('found') and not hb.get('error') and hb.get('status'):
            status = hb['status']
            current_issue = hb.get('issue')
            if current_issue is None and latest_record is not None:
                current_issue = latest_record['issue']
            elapsed = None
            if hb.get('start_time') is not None:
                elapsed = max(0.0, now - hb['start_time'])
            elif hb.get('time') is not None:
                elapsed = max(0.0, now - hb['time'])
            worker['reason'] = None
            if status in BLOCKED_STATUSES:
                worker['state'] = 'blocked'
                worker['current_issue'] = current_issue
                worker['elapsed_seconds'] = elapsed
                worker['elapsed_human'] = format_duration(elapsed)
            elif status in ACTIVE_STATUSES:
                worker['state'] = 'active'
                worker['current_issue'] = current_issue
                worker['elapsed_seconds'] = elapsed
                worker['elapsed_human'] = format_duration(elapsed)
            elif status == REVIEW_STATUS:
                worker['state'] = 'review'
                worker['current_issue'] = current_issue
                if latest_record is not None and latest_record['status'] == REVIEW_STATUS:
                    worker['last_completion'] = completion_metadata(latest_record)
            elif status == FAILED_STATUS:
                worker['state'] = 'idle'
                if latest_record is not None and latest_record['status'] == FAILED_STATUS:
                    worker['last_failure'] = {
                        'issue': latest_record['issue'],
                        'error': safe_public_error(latest_record['error']),
                        'time_iso': fstatus.iso(record_time),
                    }
            else:
                worker['state'] = 'idle'
            workers.append(worker)
            continue

        # Fall back safely: no usable per-lane heartbeat for this worker. A
        # newer event is authoritative over a stale issue record for every
        # terminal and active status, not only dependency blocking.
        if event_time is not None and (record_time is None or event_time > record_time):
            status = latest_event['status']
            current_issue = latest_event.get('issue')
            if current_issue is None and latest_record is not None:
                current_issue = latest_record['issue']
            worker['current_issue'] = current_issue
            if status in BLOCKED_STATUSES or status in ACTIVE_STATUSES:
                worker['state'] = 'blocked' if status in BLOCKED_STATUSES else 'active'
                worker['elapsed_seconds'] = max(0.0, now - event_time)
                worker['elapsed_human'] = format_duration(worker['elapsed_seconds'])
            elif status == REVIEW_STATUS:
                worker['state'] = 'review'
                if latest_record is not None and latest_record['status'] == REVIEW_STATUS:
                    worker['last_completion'] = completion_metadata(latest_record)
            elif status == FAILED_STATUS:
                worker['state'] = 'idle'
                worker['last_failure'] = {
                    'issue': current_issue,
                    'error': None,
                    'time_iso': fstatus.iso(event_time),
                }
            else:
                worker['state'] = 'idle'
        elif latest_record is not None:
            if latest_record['status'] in ACTIVE_STATUSES:
                worker['state'] = 'active'
                worker['current_issue'] = latest_record['issue']
                worker['elapsed_seconds'] = max(0.0, now - record_time)
                worker['elapsed_human'] = format_duration(worker['elapsed_seconds'])
            elif latest_record['status'] == REVIEW_STATUS:
                worker['state'] = 'review'
                worker['current_issue'] = latest_record['issue']
                worker['last_completion'] = completion_metadata(latest_record)
            elif latest_record['status'] == FAILED_STATUS:
                worker['state'] = 'idle'
                worker['last_failure'] = {
                    'issue': latest_record['issue'],
                    'error': safe_public_error(latest_record['error']),
                    'time_iso': fstatus.iso(record_time),
                }
            else:
                worker['state'] = 'idle'
        workers.append(worker)
    return workers


def build_report(config_path, config, state_dir_override=None, now=None,
                  stale_after_seconds=DEFAULT_STALE_AFTER_SECONDS,
                  utilization_window_days=DEFAULT_UTILIZATION_WINDOW_DAYS,
                  slowdown_threshold_pct=None, stop_threshold_pct=None):
    now = time.time() if now is None else now
    state_dir = pathlib.Path(state_dir_override if state_dir_override is not None else config['state'])

    heartbeat = fstatus.heartbeat_status(state_dir, stale_after_seconds, now)
    issue_summary = fstatus.issue_record_summary(state_dir)
    # by_status/by_agent/total/corrupt counts come from fstatus.issue_record_summary
    # (single source of truth); load_issue_records re-scans the same files only to
    # surface the full per-issue fields the dashboard displays.
    records, _records_corrupt = load_issue_records(state_dir)
    queue_snapshot = load_queue_snapshot(state_dir)
    queue = queue_view(queue_snapshot, issue_summary, records, now)
    events_result = load_events(state_dir)
    events = events_result['events']

    policy = usage_policy(config, slowdown_threshold_pct, stop_threshold_pct)
    usage = load_usage(state_dir, policy, now=now)

    agent_defs = agent_definitions(config)
    total_workers = len(agent_defs) if agent_defs else fstatus.DEFAULT_UTILIZATION_TOTAL_WORKERS

    total_window_start = min(e['time'] for e in events) if events else now
    nine_day_window_start = now - (utilization_window_days * 86400)

    issues = build_issue_views(records, events, now)
    worker_heartbeats = {key: load_worker_heartbeat(state_dir, key) for key in agent_defs}
    workers = build_worker_views(agent_defs, records, events, worker_heartbeats, now)

    return {
        'generated_at': fstatus.iso(now),
        # Keep the keys for API compatibility without disclosing host paths.
        'config_path': None,
        'state_dir': None,
        'state_dir_found': state_dir.is_dir(),
        'heartbeat': heartbeat,
        'workers': workers,
        'queue': queue,
        'issues': issues,
        'completed': [i for i in issues if i['status'] == REVIEW_STATUS],
        'utilization': {
            'window_days': utilization_window_days,
            'total_workers': total_workers,
            'target_workers': DEFAULT_UTILIZATION_TARGET_WORKERS,
            'events_found': events_result['found'],
            'events_error': events_result['error'],
            'events_corrupt_lines': events_result['corrupt_lines'],
            'total': average_active_workers_for_window(events_result, now, total_window_start, now, total_workers),
            'nine_day': average_active_workers_for_window(events_result, now, nine_day_window_start, now, total_workers),
        },
        'longest_blocked_duration': longest_blocked_duration(events_result, now),
        'validation': {
            'note': (
                'Validation result is tracked per issue below (pending/running/passed/failed); '
                'there is no single global validation state.'
            ),
        },
        'usage': {
            'policy': policy,
            'found': usage['found'],
            'error': usage['error'],
            'corrupt_workers': usage['corrupt_workers'],
            'note': usage['note'],
            'workers': usage['workers'],
        },
        'capacity_note': fstatus.CAPACITY_NOTE,
    }


class DashboardRequestHandler(BaseHTTPRequestHandler):
    server_version = 'ThreadlineFactoryDashboard/1.0'
    protocol_version = 'HTTP/1.1'

    def log_message(self, format, *args):  # noqa: A002 - stdlib signature
        pass

    def _write(self, status, content_type, body_bytes):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body_bytes)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body_bytes)

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        opts = self.server.dashboard_options
        if path == '/':
            try:
                html = opts['html_path'].read_text(encoding='utf-8')
            except OSError:
                self._write(500, 'text/plain; charset=utf-8', b'dashboard html not found')
                return
            self._write(200, 'text/html; charset=utf-8', html.encode('utf-8'))
        elif path == '/api/status':
            report = build_report(
                opts['config_path'], opts['config'],
                stale_after_seconds=opts['stale_after_seconds'],
                utilization_window_days=opts['utilization_window_days'],
                slowdown_threshold_pct=opts['slowdown_threshold_pct'],
                stop_threshold_pct=opts['stop_threshold_pct'],
            )
            self._write(200, 'application/json; charset=utf-8', json.dumps(report, indent=2).encode('utf-8'))
        else:
            self._write(404, 'text/plain; charset=utf-8', b'not found')


def loopback_host_arg(value):
    if value != DEFAULT_HOST:
        raise argparse.ArgumentTypeError(f'host must be {DEFAULT_HOST}')
    return value


def make_server(host, port, config_path, config, html_path=HTML_PATH,
                 stale_after_seconds=DEFAULT_STALE_AFTER_SECONDS,
                 utilization_window_days=DEFAULT_UTILIZATION_WINDOW_DAYS,
                 slowdown_threshold_pct=None, stop_threshold_pct=None):
    if host != DEFAULT_HOST:
        raise ValueError(f'dashboard host must be {DEFAULT_HOST}')
    server = ThreadingHTTPServer((host, port), DashboardRequestHandler)
    server.dashboard_options = {
        'config_path': config_path,
        'config': config,
        'html_path': html_path,
        'stale_after_seconds': stale_after_seconds,
        'utilization_window_days': utilization_window_days,
        'slowdown_threshold_pct': slowdown_threshold_pct,
        'stop_threshold_pct': stop_threshold_pct,
    }
    return server


def build_arg_parser():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--config', required=True, help='Path to the runner config.json (only "state" and "agents" fields are read)')
    ap.add_argument('--host', type=loopback_host_arg, default=DEFAULT_HOST,
                    help=f'Bind host (fixed to {DEFAULT_HOST})')
    ap.add_argument('--port', type=int, default=DEFAULT_PORT, help=f'Bind port (default {DEFAULT_PORT})')
    ap.add_argument('--stale-after-seconds', type=float, default=DEFAULT_STALE_AFTER_SECONDS)
    ap.add_argument('--utilization-window-days', type=float, default=DEFAULT_UTILIZATION_WINDOW_DAYS)
    ap.add_argument('--slowdown-threshold-pct', type=float, default=None,
                     help=f'Overrides config usage_policy.slowdown_threshold_pct (default {DEFAULT_SLOWDOWN_THRESHOLD_PCT})')
    ap.add_argument('--stop-threshold-pct', type=float, default=None,
                     help=f'Overrides config usage_policy.stop_threshold_pct (default {DEFAULT_STOP_THRESHOLD_PCT}, capped at {MAX_STOP_THRESHOLD_PCT})')
    return ap


def main(argv=None):
    args = build_arg_parser().parse_args(argv)
    try:
        config = fstatus.load_config(args.config)
    except ValueError as e:
        print(f'error: {e}', file=sys.stderr)
        return 1
    server = make_server(
        args.host, args.port, args.config, config,
        stale_after_seconds=args.stale_after_seconds,
        utilization_window_days=args.utilization_window_days,
        slowdown_threshold_pct=args.slowdown_threshold_pct,
        stop_threshold_pct=args.stop_threshold_pct,
    )
    print(f'Factory dashboard listening on http://{args.host}:{args.port}/ (auto-refreshes every {REFRESH_SECONDS}s)')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
