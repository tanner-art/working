#!/usr/bin/env python3
"""Install Threadline runner LaunchAgents; runner polling defaults to dry-run."""
import argparse
import json
import os
import pathlib
import plistlib
import pwd
import shutil
import subprocess
import sys
import time

SERIAL_LABEL = 'life.threadline.runner'
LANE_AGENTS = ('codex-a', 'codex-b', 'claude')
DASHBOARD_LABEL = 'life.threadline.factory-dashboard'


def service_environment(path):
    """Return the minimal, non-secret identity environment for LaunchAgents."""
    return {
        'PATH': path,
        'HOME': str(pathlib.Path.home()),
        'USER': pwd.getpwuid(os.getuid()).pw_name,
    }


def launch_agents_dir(home=None):
    return pathlib.Path(home if home is not None else pathlib.Path.home()) / 'Library/LaunchAgents'


def label_path(label, home=None):
    return launch_agents_dir(home) / f'{label}.plist'


def load_config(path):
    try:
        value = json.loads(pathlib.Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise ValueError(f'cannot read config: {exc}') from exc
    if not isinstance(value, dict) or not isinstance(value.get('state'), str) or not value['state']:
        raise ValueError('config requires a non-empty state path')
    if not isinstance(value.get('path'), str) or not value['path']:
        raise ValueError('config requires a non-empty path')
    return value


def validate_port(port):
    if isinstance(port, bool) or not isinstance(port, int) or not 1024 <= port <= 65535:
        raise ValueError('dashboard port must be an integer from 1024 through 65535')
    return port


def runner_data(label, args, root, state, path, stdout, stderr):
    return {
        'Label': label, 'ProgramArguments': args, 'WorkingDirectory': str(root.parent.parent),
        'EnvironmentVariables': service_environment(path),
        'RunAtLoad': True, 'StartInterval': 60, 'ProcessType': 'Background',
        'StandardOutPath': str(state / stdout), 'StandardErrorPath': str(state / stderr),
    }


def dashboard_data(config, root, state, path, port):
    return {
        'Label': DASHBOARD_LABEL,
        'ProgramArguments': [sys.executable, str(root / 'factory_dashboard.py'), '--config', str(config), '--host', '127.0.0.1', '--port', str(port)],
        'WorkingDirectory': str(root.parent.parent),
        'EnvironmentVariables': service_environment(path),
        'RunAtLoad': True, 'ProcessType': 'Background',
        'StandardOutPath': str(state / 'launchd-dashboard.log'),
        'StandardErrorPath': str(state / 'launchd-dashboard-error.log'),
    }


def service_plan(config, config_path, root, mode='serial', live=False, dashboard_port=8787):
    """Return ordered, non-secret plist data without writing or launching it."""
    config_path = pathlib.Path(config_path).resolve()
    state = pathlib.Path(config['state'])
    common = [sys.executable, str(root / 'runner.py'), '--config', str(config_path)]
    if not live:
        common.append('--dry-run')
    if mode == 'serial':
        return [(SERIAL_LABEL, runner_data(SERIAL_LABEL, common, root, state, config['path'], 'launchd.log', 'launchd-error.log'))]
    if mode != 'lanes':
        raise ValueError('mode must be serial or lanes')
    agents = config.get('agents')
    if not isinstance(agents, dict):
        raise ValueError('lane mode requires configured agents')
    for agent in LANE_AGENTS:
        value = agents.get(agent)
        if not isinstance(value, dict) or not isinstance(value.get('command'), list) or not value['command']:
            raise ValueError(f'lane mode requires a configured {agent} command')
    port = validate_port(dashboard_port)
    plan = []
    for agent in LANE_AGENTS:
        label = f'{SERIAL_LABEL}.{agent}'
        args = [*common, '--agent', agent]
        plan.append((label, runner_data(label, args, root, state, config['path'], f'launchd-{agent}.log', f'launchd-{agent}-error.log')))
    plan.append((DASHBOARD_LABEL, dashboard_data(config_path, root, state, config['path'], port)))
    return plan


def labels_for_mode(mode):
    return (SERIAL_LABEL,) if mode == 'serial' else tuple(f'{SERIAL_LABEL}.{agent}' for agent in LANE_AGENTS) + (DASHBOARD_LABEL,)


def is_loaded(label, uid, run=subprocess.run):
    return run(['launchctl', 'print', f'gui/{uid}/{label}'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def atomic_write_plist(destination, data):
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f'.{destination.name}.{os.getpid()}.tmp')
    try:
        with open(temporary, 'wb') as output:
            output.write(plistlib.dumps(data))
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(destination)
    finally:
        if temporary.exists():
            temporary.unlink()


def bootout(label, uid, run=subprocess.run):
    return run(['launchctl', 'bootout', f'gui/{uid}/{label}'], check=False).returncode == 0


def install(plan, *, mode, replace_mode, state, replace_current=False, home=None, run=subprocess.run, uid=None):
    """Install one serial service or the lane set; rollback only this invocation."""
    uid = os.getuid() if uid is None else uid
    state = pathlib.Path(state)
    destinations = {label: label_path(label, home) for label, _ in plan}
    target_labels = tuple(destinations)
    if replace_mode and replace_current:
        raise ValueError('--replace-mode and --replace-current cannot be combined')
    old_mode = 'lanes' if mode == 'serial' else 'serial'
    old_labels = labels_for_mode(old_mode)
    target_loaded = [label for label in target_labels if is_loaded(label, uid, run)]
    old_loaded = [label for label in old_labels if is_loaded(label, uid, run)]
    target_conflicts = [label for label, destination in destinations.items() if destination.exists() or label in target_loaded]
    old_paths = {label: label_path(label, home) for label in old_labels}
    old_conflicts = [label for label, destination in old_paths.items() if destination.exists() or is_loaded(label, uid, run)]
    loaded_before = set(target_loaded) | set(old_loaded)
    if target_conflicts and not replace_current:
        raise ValueError('existing service preserved: ' + ', '.join(target_conflicts))
    if replace_current and not target_conflicts:
        raise ValueError('--replace-current requires an installed current mode')
    if old_conflicts and not replace_mode:
        raise ValueError('mode change requires --replace-mode: ' + ', '.join(old_conflicts))
    if replace_mode and not old_conflicts:
        raise ValueError('--replace-mode requires an installed opposite mode')
    missing_backups = [label for label in old_conflicts if not old_paths[label].exists()]
    if missing_backups:
        raise ValueError('cannot safely migrate without plist backups: ' + ', '.join(missing_backups))
    missing_target_backups = [label for label in target_conflicts if not destinations[label].exists()]
    if missing_target_backups:
        raise ValueError('cannot safely replace without plist backups: ' + ', '.join(missing_target_backups))

    backup_dir = None
    backups = {}
    backup_destinations = {}
    written = []
    bootstrapped = []
    try:
        if old_conflicts:
            backup_dir = state / 'launchd-backups' / str(int(time.time() * 1000))
            backup_dir.mkdir(parents=True, exist_ok=False)
            for label, source in old_paths.items():
                if source.exists():
                    target = backup_dir / source.name
                    shutil.copy2(source, target)
                    backups[label] = target
                    backup_destinations[label] = source
            for label in old_conflicts:
                if not bootout(label, uid, run):
                    raise RuntimeError(f'could not boot out {label}')
        if target_conflicts:
            if backup_dir is None:
                backup_dir = state / 'launchd-backups' / str(int(time.time() * 1000))
                backup_dir.mkdir(parents=True, exist_ok=False)
            for label in target_conflicts:
                source = destinations[label]
                target = backup_dir / source.name
                shutil.copy2(source, target)
                backups[label] = target
                backup_destinations[label] = source
            for label in target_loaded:
                if not bootout(label, uid, run):
                    raise RuntimeError(f'could not boot out {label}')
        for label, data in plan:
            atomic_write_plist(destinations[label], data)
            written.append(label)
        for label in target_labels:
            run(['launchctl', 'bootstrap', f'gui/{uid}', str(destinations[label])], check=True)
            bootstrapped.append(label)
    except Exception as exc:
        for label in reversed(bootstrapped):
            bootout(label, uid, run)
        for label in written:
            destinations[label].unlink(missing_ok=True)
        restored = []
        for label, backup in backups.items():
            destination = backup_destinations[label]
            shutil.copy2(backup, destination)
            if label not in loaded_before:
                continue
            try:
                run(['launchctl', 'bootstrap', f'gui/{uid}', str(destination)], check=True)
                restored.append(label)
            except Exception:
                pass
        suffix = f'; rollback restored: {", ".join(restored)}' if backups else ''
        raise RuntimeError(f'installation failed: {exc}{suffix}') from exc
    return destinations


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--live', action='store_true', help='Allow runner services to execute queued work')
    parser.add_argument('--mode', choices=('serial', 'lanes'), default='serial')
    parser.add_argument('--replace-mode', action='store_true', help='Explicitly replace an installed opposite mode')
    parser.add_argument('--replace-current', action='store_true', help='Explicitly replace installed services in the selected mode')
    parser.add_argument('--dashboard-port', type=int, default=8787)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        config_path = pathlib.Path(args.config).resolve()
        config = load_config(config_path)
        state = pathlib.Path(config['state'])
        state.mkdir(parents=True, exist_ok=True)
        root = pathlib.Path(__file__).resolve().parent
        plan = service_plan(config, config_path, root, args.mode, args.live, args.dashboard_port)
        destinations = install(plan, mode=args.mode, replace_mode=args.replace_mode,
                               replace_current=args.replace_current, state=state)
    except (ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 1
    runner_state = 'live' if args.live else 'dry-run'
    for label, destination in destinations.items():
        print(f'installed {label}: {destination} ({runner_state if label != DASHBOARD_LABEL else "localhost dashboard"})')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
