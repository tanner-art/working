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
MIN_AGENT_SLOTS = 1
MAX_AGENT_SLOTS = 3
DASHBOARD_LABEL = 'life.threadline.factory-dashboard'
PRIVATE_DIRECTORY_MODE = 0o700
PRIVATE_FILE_MODE = 0o600
SERVICE_UMASK = 0o077


def service_environment(path):
    """Return the minimal, non-secret identity environment for LaunchAgents."""
    return {
        'PATH': path,
        'HOME': str(pathlib.Path.home()),
        'USER': pwd.getpwuid(os.getuid()).pw_name,
    }


def _set_owner_only(path, mode):
    """Harden an owned, non-symlink path without changing its ownership."""
    path = pathlib.Path(path)
    metadata = path.lstat()
    if path.is_symlink():
        raise ValueError(f'refusing to change permissions through symlink: {path}')
    if metadata.st_uid != os.getuid():
        raise ValueError(f'refusing to change permissions for a path owned by another user: {path}')
    path.chmod(mode)


def prepare_private_storage(config_path, config, plan):
    """Prepare only installer-managed local paths with owner-only access."""
    config_path = pathlib.Path(config_path)
    state = pathlib.Path(config['state'])
    worktrees_value = config.get('worktrees')
    worktrees = pathlib.Path(worktrees_value) if isinstance(worktrees_value, str) and worktrees_value else None
    try:
        state.mkdir(parents=True, exist_ok=True, mode=PRIVATE_DIRECTORY_MODE)
        _set_owner_only(state, PRIVATE_DIRECTORY_MODE)
        if worktrees is not None:
            worktrees.mkdir(parents=True, exist_ok=True, mode=PRIVATE_DIRECTORY_MODE)
            _set_owner_only(worktrees, PRIVATE_DIRECTORY_MODE)
        if worktrees is not None and state.parent == config_path.parent == worktrees.parent:
            _set_owner_only(config_path.parent, PRIVATE_DIRECTORY_MODE)
        _set_owner_only(config_path, PRIVATE_FILE_MODE)

        # Existing direct state artifacts are private immediately. Directories
        # (for example launchd-backups) protect their descendants without
        # rewriting repository/worktree contents recursively.
        for artifact in state.iterdir():
            if artifact.is_symlink():
                continue
            if artifact.is_dir():
                _set_owner_only(artifact, PRIVATE_DIRECTORY_MODE)
            elif artifact.is_file():
                _set_owner_only(artifact, PRIVATE_FILE_MODE)

        # launchd opens these paths itself, so create without truncating them
        # before bootstrap and establish their final permissions explicitly.
        for _, data in plan:
            for field in ('StandardOutPath', 'StandardErrorPath'):
                log = pathlib.Path(data[field])
                log.touch(exist_ok=True, mode=PRIVATE_FILE_MODE)
                _set_owner_only(log, PRIVATE_FILE_MODE)
    except OSError as exc:
        raise ValueError(f'cannot prepare private factory storage: {exc}') from exc


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
        'Umask': SERVICE_UMASK,
        'RunAtLoad': True, 'StartInterval': 60, 'ProcessType': 'Background',
        'StandardOutPath': str(state / stdout), 'StandardErrorPath': str(state / stderr),
    }


def dashboard_data(config, root, state, path, port):
    return {
        'Label': DASHBOARD_LABEL,
        'ProgramArguments': [sys.executable, str(root / 'factory_dashboard.py'), '--config', str(config), '--host', '127.0.0.1', '--port', str(port)],
        'WorkingDirectory': str(root.parent.parent),
        'EnvironmentVariables': service_environment(path),
        'Umask': SERVICE_UMASK,
        'RunAtLoad': True, 'ProcessType': 'Background',
        'StandardOutPath': str(state / 'launchd-dashboard.log'),
        'StandardErrorPath': str(state / 'launchd-dashboard-error.log'),
    }


def agent_slot_count(agent, value):
    """Return a validated external runner lane count for one agent."""
    slots = value.get('slots', MIN_AGENT_SLOTS)
    if isinstance(slots, bool) or not isinstance(slots, int) or not MIN_AGENT_SLOTS <= slots <= MAX_AGENT_SLOTS:
        raise ValueError(f'{agent} slots must be an integer from {MIN_AGENT_SLOTS} through {MAX_AGENT_SLOTS}')
    return slots


def lane_identity(agent, slot):
    """Return stable label/log identifiers; slot one keeps legacy names."""
    suffix = '' if slot == 1 else f'-{slot}'
    return f'{SERIAL_LABEL}.{agent}{suffix}', f'{agent}{suffix}'


def _has_option_value(command, option, value):
    """Return whether a tokenized command contains an exact option value."""
    for index, token in enumerate(command):
        if token == option and index + 1 < len(command) and command[index + 1] == value:
            return True
        if token == f'{option}={value}':
            return True
    return False


def _claude_tools(command):
    """Return the explicit Claude tool allowlist, or None when it is absent."""
    tools = set()
    found = False
    for index, token in enumerate(command):
        if token == '--tools' and index + 1 < len(command):
            found = True
            tools.update(tool.strip().lower() for tool in command[index + 1].split(',') if tool.strip())
        if token.startswith('--tools='):
            found = True
            tools.update(tool.strip().lower() for tool in token.split('=', 1)[1].split(',') if tool.strip())
    return tools if found else None


def validate_runner_commands(agent, value):
    """Reject commands that could hide provider-native child agents."""
    for field in ('command', 'fallback_command'):
        command = value.get(field)
        if command is None and field == 'fallback_command':
            continue
        if (not isinstance(command, list) or not command
                or not all(isinstance(token, str) and token for token in command)):
            raise ValueError(f'{agent} {field} must be a non-empty string list')
        if agent.startswith('codex-'):
            disabled = _has_option_value(command, '--disable', 'multi_agent')
            enabled = _has_option_value(command, '--enable', 'multi_agent')
            if not disabled or enabled:
                raise ValueError(f'{agent} {field} must disable multi_agent for runner-controlled lanes')
        if agent == 'claude':
            tools = _claude_tools(command)
            if tools is None or 'agent' in tools:
                raise ValueError(f'{agent} {field} must use an explicit --tools allowlist without Agent')


def service_plan(config, config_path, root, mode='serial', live=False, dashboard_port=8787):
    """Return ordered, non-secret plist data without writing or launching it."""
    config_path = pathlib.Path(config_path).resolve()
    state = pathlib.Path(config['state'])
    common = [sys.executable, str(root / 'runner.py'), '--config', str(config_path)]
    if not live:
        common.append('--dry-run')
    agents = config.get('agents')
    if isinstance(agents, dict):
        for agent in LANE_AGENTS:
            value = agents.get(agent)
            if isinstance(value, dict) and 'command' in value:
                validate_runner_commands(agent, value)
    if mode == 'serial':
        return [(SERIAL_LABEL, runner_data(SERIAL_LABEL, common, root, state, config['path'], 'launchd.log', 'launchd-error.log'))]
    if mode != 'lanes':
        raise ValueError('mode must be serial or lanes')
    if not isinstance(agents, dict):
        raise ValueError('lane mode requires configured agents')
    slots_by_agent = {}
    for agent in LANE_AGENTS:
        value = agents.get(agent)
        if not isinstance(value, dict) or not isinstance(value.get('command'), list) or not value['command']:
            raise ValueError(f'lane mode requires a configured {agent} command')
        slots_by_agent[agent] = agent_slot_count(agent, value)
    port = validate_port(dashboard_port)
    plan = []
    for agent in LANE_AGENTS:
        for slot in range(1, slots_by_agent[agent] + 1):
            label, log_name = lane_identity(agent, slot)
            args = [*common, '--agent', agent]
            if slot > 1:
                args.extend(('--slot', str(slot)))
            plan.append((label, runner_data(label, args, root, state, config['path'], f'launchd-{log_name}.log', f'launchd-{log_name}-error.log')))
    plan.append((DASHBOARD_LABEL, dashboard_data(config_path, root, state, config['path'], port)))
    return plan


def labels_for_mode(mode):
    if mode == 'serial':
        return (SERIAL_LABEL,)
    # Include every supported slot so migration back to serial discovers and
    # preserves services installed under a previous lane-count configuration.
    return tuple(
        lane_identity(agent, slot)[0]
        for agent in LANE_AGENTS
        for slot in range(1, MAX_AGENT_SLOTS + 1)
    ) + (DASHBOARD_LABEL,)


def is_loaded(label, uid, run=subprocess.run):
    return run(['launchctl', 'print', f'gui/{uid}/{label}'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def atomic_write_plist(destination, data):
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f'.{destination.name}.{os.getpid()}.tmp')
    try:
        with open(temporary, 'wb') as output:
            os.fchmod(output.fileno(), PRIVATE_FILE_MODE)
            output.write(plistlib.dumps(data))
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(destination)
    finally:
        if temporary.exists():
            temporary.unlink()


def bootout(label, uid, run=subprocess.run):
    return run(['launchctl', 'bootout', f'gui/{uid}/{label}'], check=False).returncode == 0


def pause_to_dry_run(plan, *, mode, registry_control, state, home=None,
                     run=subprocess.run, uid=None):
    """Replace live definitions with reviewed dry-run plists without live rollback."""
    uid = os.getuid() if uid is None else uid
    state = pathlib.Path(state)
    plan = tuple(plan)
    if mode not in ('serial', 'lanes'):
        raise ValueError('mode must be serial or lanes')
    plan_labels = tuple(label for label, _ in plan)
    destinations = {label: label_path(label, home) for label, _ in plan}
    allowed_labels = set(labels_for_mode(mode))
    current_labels = tuple(dict.fromkeys((
        *labels_for_mode('serial'), *labels_for_mode('lanes'),
    )))
    if (
        not plan
        or len(destinations) != len(plan)
        or any(label not in allowed_labels for label in plan_labels)
        or not any(label != DASHBOARD_LABEL for label in plan_labels)
        or any(
            label != DASHBOARD_LABEL
            and '--dry-run' not in data.get('ProgramArguments', ())
            for label, data in plan
        )
    ):
        raise ValueError('pause replacement requires a reviewed dry-run plan')
    if registry_control is None:
        raise ValueError('pause replacement requires Registry control')

    # Persist the kill switch before asking launchd to terminate any runner.
    registry_control.engage_stop('operator requested live-to-dry-run replacement')
    existing = {
        label: label_path(label, home)
        for label in current_labels
        if label_path(label, home).exists()
    }
    loaded = [label for label in current_labels if is_loaded(label, uid, run)]
    missing_backups = [label for label in loaded if label not in existing]
    if missing_backups:
        # The kill switch remains engaged, but no service is stopped unless its
        # exact installed definition can be retained for operator recovery.
        raise ValueError(
            'cannot safely pause without plist backups: ' + ', '.join(missing_backups)
        )

    backup_dir = state / 'launchd-backups' / f'paused-{time.time_ns()}'
    backup_dir.mkdir(parents=True, exist_ok=False)
    for source in existing.values():
        shutil.copy2(source, backup_dir / source.name)

    failed = [label for label in loaded if not bootout(label, uid, run)]
    if failed:
        # Registry stays STOPPING and no definition is reloaded or restored.
        raise RuntimeError('could not stop live services: ' + ', '.join(failed))

    reconciliation = registry_control.reconcile_stopping_runtimes()
    unresolved = tuple(reconciliation.get('unresolved', ()))
    if unresolved:
        # Registry remains STOPPING, live definitions stay on disk, and the
        # adapter has recorded deterministic evidence for every unresolved ID.
        raise RuntimeError(
            'runtime reconciliation incomplete: ' + ', '.join(unresolved)
        )

    for label, data in plan:
        atomic_write_plist(destinations[label], data)
    for label, source in existing.items():
        if label not in destinations:
            source.unlink(missing_ok=True)

    registry_control.finalize_paused(reason='live services stopped; dry-run definitions written')
    bootstrapped = []
    try:
        for label, _ in plan:
            run(
                ['launchctl', 'bootstrap', f'gui/{uid}', str(destinations[label])],
                check=True,
            )
            bootstrapped.append(label)
    except Exception as error:
        for label in reversed(bootstrapped):
            bootout(label, uid, run)
        # Keep PAUSED and keep dry-run definitions. Never restore a live plist.
        raise RuntimeError(f'dry-run bootstrap failed: {error}') from error
    return {'backup_dir': backup_dir, 'destinations': destinations}


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
    current_labels = labels_for_mode(mode)
    obsolete_labels = tuple(label for label in current_labels if label not in destinations)
    obsolete_paths = {label: label_path(label, home) for label in obsolete_labels}
    target_loaded = [label for label in target_labels if is_loaded(label, uid, run)]
    obsolete_loaded = [label for label in obsolete_labels if is_loaded(label, uid, run)]
    old_loaded = [label for label in old_labels if is_loaded(label, uid, run)]
    target_conflicts = [label for label, destination in destinations.items() if destination.exists() or label in target_loaded]
    obsolete_conflicts = [label for label, destination in obsolete_paths.items()
                          if destination.exists() or label in obsolete_loaded]
    old_paths = {label: label_path(label, home) for label in old_labels}
    old_conflicts = [label for label, destination in old_paths.items() if destination.exists() or is_loaded(label, uid, run)]
    loaded_before = set(target_loaded) | set(obsolete_loaded) | set(old_loaded)
    current_conflicts = target_conflicts + obsolete_conflicts
    if current_conflicts and not replace_current:
        raise ValueError('existing service preserved: ' + ', '.join(current_conflicts))
    if replace_current and not current_conflicts:
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
    missing_obsolete_backups = [label for label in obsolete_conflicts if not obsolete_paths[label].exists()]
    if missing_obsolete_backups:
        raise ValueError('cannot safely replace without plist backups: ' + ', '.join(missing_obsolete_backups))

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
        if obsolete_conflicts:
            if backup_dir is None:
                backup_dir = state / 'launchd-backups' / str(int(time.time() * 1000))
                backup_dir.mkdir(parents=True, exist_ok=False)
            for label in obsolete_conflicts:
                source = obsolete_paths[label]
                target = backup_dir / source.name
                shutil.copy2(source, target)
                backups[label] = target
                backup_destinations[label] = source
            for label in obsolete_loaded:
                if not bootout(label, uid, run):
                    raise RuntimeError(f'could not boot out {label}')
        for label, data in plan:
            atomic_write_plist(destinations[label], data)
            written.append(label)
        for label in target_labels:
            run(['launchctl', 'bootstrap', f'gui/{uid}', str(destinations[label])], check=True)
            bootstrapped.append(label)
        for label in obsolete_conflicts:
            obsolete_paths[label].unlink(missing_ok=True)
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
        root = pathlib.Path(__file__).resolve().parent
        plan = service_plan(config, config_path, root, args.mode, args.live, args.dashboard_port)
        prepare_private_storage(config_path, config, plan)
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
