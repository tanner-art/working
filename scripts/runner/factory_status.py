#!/usr/bin/env python3
"""Read-only local factory health/capacity report for the GitHub queue runner.

Reads only the runner's own state directory (heartbeat.json, issue-N.json
records) as described in scripts/runner/README.md. Never reads or prints
credentials, GitHub tokens, or per-attempt log contents (those may contain
source code). Safe to run against a missing or partially corrupt state
directory: every section degrades to an explicit "missing"/"corrupt" marker
rather than raising.
"""
import argparse
import json
import pathlib
import re
import sys
import time
from datetime import datetime, timezone

DEFAULT_STALE_AFTER_SECONDS = 180
DEFAULT_UTILIZATION_WINDOW_DAYS = 9
DEFAULT_UTILIZATION_TARGET_WORKERS = 2.5
DEFAULT_UTILIZATION_TOTAL_WORKERS = 3

ISSUE_RECORD_RE = re.compile(r'^issue-(\d+)\.json$')

AGENT_KEY_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]*$')


def iso(ts):
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def read_json_safe(path):
    """Return (data, error). error is None on success, else a short safe message."""
    try:
        raw = path.read_text()
    except FileNotFoundError:
        return None, 'missing'
    except OSError as e:
        return None, f'unreadable: {e.__class__.__name__}'
    try:
        return json.loads(raw), None
    except json.JSONDecodeError:
        return None, 'corrupt: invalid JSON'


def load_config(config_path):
    path = pathlib.Path(config_path)
    data, error = read_json_safe(path)
    if error:
        raise ValueError(f'config {error}: {config_path}')
    if not isinstance(data, dict) or not isinstance(data.get('state'), str):
        raise ValueError(f"config missing required string field 'state': {config_path}")
    return data


def heartbeat_status(state_dir, stale_after_seconds, now):
    return _heartbeat_file_status(state_dir / 'heartbeat.json', stale_after_seconds, now)


def _heartbeat_file_status(path, stale_after_seconds, now):
    data, error = read_json_safe(path)
    if error == 'missing':
        return {'found': False, 'error': None, 'time': None, 'age_seconds': None,
                'status': None, 'stale': None, 'stale_threshold_seconds': stale_after_seconds}
    if error:
        return {'found': True, 'error': error, 'time': None, 'age_seconds': None,
                'status': None, 'stale': None, 'stale_threshold_seconds': stale_after_seconds}
    ts = data.get('time') if isinstance(data, dict) else None
    status = data.get('status') if isinstance(data, dict) else None
    if not isinstance(ts, (int, float)):
        return {'found': True, 'error': 'corrupt: missing/invalid time field', 'time': None,
                'age_seconds': None, 'status': status if isinstance(status, str) else None,
                'stale': None, 'stale_threshold_seconds': stale_after_seconds}
    age = max(0.0, now - ts)
    return {
        'found': True,
        'error': None,
        'time': ts,
        'time_iso': iso(ts),
        'age_seconds': age,
        'status': status if isinstance(status, str) else None,
        'stale': age > stale_after_seconds,
        'stale_threshold_seconds': stale_after_seconds,
    }


def capacity_status(state_dir, config, stale_after_seconds, now):
    """Infer live execution mode only from fresh runtime heartbeats."""
    agents = config.get('agents')
    keys = sorted(key for key in agents if isinstance(key, str) and AGENT_KEY_RE.fullmatch(key)) \
        if isinstance(agents, dict) else []
    lane_heartbeats = {
        key: _heartbeat_file_status(state_dir / f'heartbeat-{key}.json', stale_after_seconds, now)
        for key in keys
    }
    fresh_lanes = [key for key, status in lane_heartbeats.items()
                   if status['found'] and not status['error'] and status['stale'] is False]
    serial = heartbeat_status(state_dir, stale_after_seconds, now)
    serial_is_fresh = serial['found'] and not serial['error'] and serial['stale'] is False
    newest_lane_time = max((lane_heartbeats[key]['time'] for key in fresh_lanes), default=None)
    # During a mode switch the old heartbeat files remain on disk briefly.
    # The newest fresh producer is authoritative, avoiding a transient false
    # lane report after serial mode is restored (or vice versa).
    if fresh_lanes and (not serial_is_fresh or newest_lane_time >= serial['time']):
        configured = len(keys)
        observed = len(fresh_lanes)
        return {
            'mode': 'lanes', 'max_parallel_tasks': configured,
            'fresh_lane_count': observed, 'configured_lane_count': configured,
            'note': (
                f'Concurrent lane mode is active: {observed} of {configured} configured '
                f'worker lanes have fresh heartbeats. Configured parallel capacity is '
                f'up to {configured} tasks at a time, one per lane.'
            ),
        }

    if serial_is_fresh:
        return {
            'mode': 'serial', 'max_parallel_tasks': 1,
            'fresh_lane_count': 0, 'configured_lane_count': len(keys),
            'note': 'serial mode is active: live parallel capacity is 1 task at a time.',
        }

    return {
        'mode': 'unknown', 'max_parallel_tasks': None,
        'fresh_lane_count': 0, 'configured_lane_count': len(keys),
        'note': ('Live execution mode is unknown because no fresh serial or per-lane '
                 'heartbeat is available.'),
    }


def issue_record_summary(state_dir):
    by_status = {}
    by_agent = {}
    total = 0
    corrupt = 0
    if not state_dir.is_dir():
        return {'total_records': 0, 'corrupt_records': 0, 'by_status': {}, 'by_agent': {}}
    for entry in sorted(state_dir.iterdir()):
        if not entry.is_file() or not ISSUE_RECORD_RE.match(entry.name):
            continue
        total += 1
        data, error = read_json_safe(entry)
        if error or not isinstance(data, dict):
            corrupt += 1
            continue
        status = data.get('status')
        status_key = status if isinstance(status, str) and status else 'unknown'
        by_status[status_key] = by_status.get(status_key, 0) + 1
        agent = data.get('agent')
        agent_key = agent if isinstance(agent, str) and agent else 'unassigned'
        by_agent[agent_key] = by_agent.get(agent_key, 0) + 1
    return {'total_records': total, 'corrupt_records': corrupt, 'by_status': by_status, 'by_agent': by_agent}


def utilization_section(config, window_days, target_workers):
    agents = config.get('agents')
    total_workers = len(agents) if isinstance(agents, dict) and agents else DEFAULT_UTILIZATION_TOTAL_WORKERS
    return {
        'window_days': window_days,
        'target_workers': target_workers,
        'total_workers': total_workers,
        'observed_utilization': 'unknown',
        'observed_utilization_reason': (
            'issue-N.json records are overwritten in place on each status '
            'transition (see runner.py save()); no append-only start/end '
            'timing history is retained, so utilization cannot be computed '
            'without inventing data'
        ),
    }


def build_report(config_path, config, now=None, stale_after_seconds=DEFAULT_STALE_AFTER_SECONDS,
                  utilization_window_days=DEFAULT_UTILIZATION_WINDOW_DAYS,
                  utilization_target_workers=DEFAULT_UTILIZATION_TARGET_WORKERS):
    now = time.time() if now is None else now
    state_dir = pathlib.Path(config['state'])
    capacity = capacity_status(state_dir, config, stale_after_seconds, now)
    report = {
        'generated_at': iso(now),
        'config_path': str(config_path),
        'state_dir': str(state_dir),
        'state_dir_found': state_dir.is_dir(),
        'heartbeat': heartbeat_status(state_dir, stale_after_seconds, now),
        'issues': issue_record_summary(state_dir),
        'utilization': utilization_section(config, utilization_window_days, utilization_target_workers),
        'capacity': capacity,
        'capacity_note': capacity['note'],
    }
    return report


def format_text(report):
    lines = []
    lines.append(f"Factory health report ({report['generated_at']})")
    lines.append(f"State dir: {report['state_dir']}" + ('' if report['state_dir_found'] else ' (NOT FOUND)'))
    hb = report['heartbeat']
    lines.append('')
    lines.append('Heartbeat:')
    if not hb['found']:
        lines.append('  status: missing (runner has not polled yet, or state dir is fresh)')
    elif hb['error']:
        lines.append(f"  status: {hb['error']}")
    else:
        stale_marker = ' [STALE]' if hb['stale'] else ''
        lines.append(f"  runner status: {hb['status']}")
        lines.append(f"  last heartbeat: {hb['time_iso']} ({hb['age_seconds']:.1f}s ago){stale_marker}")
        lines.append(f"  stale threshold: {hb['stale_threshold_seconds']}s")
    lines.append('')
    issues = report['issues']
    lines.append('Preserved issue records:')
    lines.append(f"  total: {issues['total_records']} (corrupt: {issues['corrupt_records']})")
    lines.append('  by status:')
    for status, count in sorted(issues['by_status'].items()):
        lines.append(f"    {status}: {count}")
    lines.append('  by agent:')
    for agent, count in sorted(issues['by_agent'].items()):
        lines.append(f"    {agent}: {count}")
    lines.append('')
    util = report['utilization']
    lines.append(
        f"Utilization target: {util['target_workers']} of {util['total_workers']} workers "
        f"over a {util['window_days']}-day window"
    )
    lines.append(f"  observed utilization: {util['observed_utilization']} ({util['observed_utilization_reason']})")
    lines.append('')
    lines.append('Capacity note:')
    lines.append(f"  {report['capacity_note']}")
    return '\n'.join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--config', required=True, help='Path to the runner config.json (only its "state" and "agents" fields are read)')
    ap.add_argument('--json', action='store_true', help='Emit machine-readable JSON instead of text')
    ap.add_argument('--stale-after-seconds', type=float, default=DEFAULT_STALE_AFTER_SECONDS,
                     help=f'Heartbeat age threshold considered stale (default {DEFAULT_STALE_AFTER_SECONDS})')
    ap.add_argument('--utilization-window-days', type=float, default=DEFAULT_UTILIZATION_WINDOW_DAYS)
    ap.add_argument('--utilization-target-workers', type=float, default=DEFAULT_UTILIZATION_TARGET_WORKERS)
    args = ap.parse_args(argv)
    try:
        config = load_config(args.config)
    except ValueError as e:
        if args.json:
            print(json.dumps({'error': str(e)}))
        else:
            print(f'error: {e}', file=sys.stderr)
        return 1
    report = build_report(
        args.config, config,
        stale_after_seconds=args.stale_after_seconds,
        utilization_window_days=args.utilization_window_days,
        utilization_target_workers=args.utilization_target_workers,
    )
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(format_text(report))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
