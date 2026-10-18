"""Shared publication of measured capacity to the runner's compatibility gate."""
from contextlib import contextmanager
from datetime import datetime
import fcntl
import json
import os
from pathlib import Path
import tempfile

from scripts.runner.usage_policy import agent_settings, validate_usage


@contextmanager
def file_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def save(path, data):
    descriptor, temporary = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w') as handle:
            json.dump(data, handle, indent=2)
            handle.write('\n')
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def usage_path(config):
    path = Path(config.get('usage_file', Path(config['state']) / 'usage.json'))
    return path if path.is_absolute() else Path(config['repo']) / path


def _stamp(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def write_collected_usage(path, config, collected):
    """Publish only fresh collector records in the existing usage-policy shape."""
    with file_lock(path.with_suffix('.collector.lock')):
        try:
            workers = validate_usage(json.loads(path.read_text()))
        except FileNotFoundError:
            workers = {}
        for item in collected:
            # A failed percentage collection intentionally has no replacement
            # observation.  Retain its prior usage record so normal staleness
            # gating constrains it; never write a fabricated fresh timestamp.
            if not item['observations']:
                continue
            worker_id = item['worker_id']
            # Registry-only aliases may receive a verified shared-account
            # observation, but are not runner dispatch agents.  Their
            # Registry fact must remain there without inventing a usage.json
            # account or requiring dispatch settings.
            if worker_id not in config.get('agents', {}):
                continue
            settings = agent_settings(config, worker_id)
            first = item['observations'][0]
            prior = workers.get(worker_id, {}).get(settings['account'], {})
            prior_samples = list(prior.get('scopes', {}).values()) or ([prior] if prior else [])
            # Collection precedes this shared lock. A slower producer must not
            # overwrite newer published evidence after finally obtaining it.
            if prior_samples and max(_stamp(value['observed_at']) for value in prior_samples) > min(
                    _stamp(value['observed_at']) for value in item['observations']):
                continue
            diagnostics = first['provider_diagnostics']
            if diagnostics.get('capacity_mode') == 'provider_signal':
                # Provider signal has no percentage scopes.  Preserve the
                # exact provider observation timestamp and never invent one.
                workers.setdefault(worker_id, {})[settings['account']] = {
                    'provider': 'anthropic', 'model': settings['model'],
                    'capacity_mode': 'provider_signal',
                    'observed_at': first['observed_at'],
                    'service_state': diagnostics['service_state'],
                    'authentication_state': diagnostics['authentication_state'],
                    'live_invocation_state': diagnostics['live_invocation_state'],
                    'limit_signal': diagnostics['limit_signal'],
                }
                continue
            scopes = {}
            for observation in item['observations']:
                diagnostics = observation['provider_diagnostics']
                value = {'used_percent': observation['consumed_percent'],
                         'observed_at': observation['observed_at']}
                if observation['reset_at'] is not None:
                    value['reset_at'] = observation['reset_at']
                scopes[diagnostics['capacity_scope']] = value
            workers.setdefault(worker_id, {})[settings['account']] = {
                'provider': 'openai', 'model': settings['model'],
                'capacity_mode': 'percentage', 'scopes': scopes,
            }
        current = {'workers': workers}
        validate_usage(current)
        save(path, current)
