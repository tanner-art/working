PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS registry_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

INSERT OR IGNORE INTO registry_metadata(key, value) VALUES
    ('schema_version', '3'),
    ('revision', '0'),
    ('active_parent_limit', '3'),
    ('orchestra_reserve_percent', '20');

CREATE TABLE IF NOT EXISTS features (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    priority INTEGER NOT NULL,
    status TEXT NOT NULL CHECK(status IN (
        'ON_DECK', 'READY', 'ACTIVE', 'VERIFY_REVIEW', 'BLOCKED', 'DONE'
    )),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workers (
    id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('WORKER', 'ORCHESTRA')),
    availability TEXT NOT NULL CHECK(availability IN (
        'IDLE', 'BUSY', 'OFFLINE', 'CONSTRAINED', 'PRESERVED'
    )),
    capabilities_json TEXT NOT NULL,
    approved_lanes_json TEXT NOT NULL,
    provider_diagnostics_json TEXT NOT NULL,
    last_heartbeat_at TEXT,
    usage_state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS work_packages (
    id TEXT PRIMARY KEY,
    feature_id TEXT NOT NULL REFERENCES features(id),
    title TEXT NOT NULL,
    category TEXT NOT NULL,
    lane TEXT CHECK(lane IN ('FEATURE', 'PLATFORM', 'ASSURANCE')),
    kind TEXT NOT NULL CHECK(kind IN ('PARENT', 'TEST', 'REVIEW', 'EVALUATION')),
    capacity_size TEXT NOT NULL DEFAULT 'SUBSTANTIAL' CHECK(capacity_size IN (
        'VERY_SMALL', 'SMALL', 'SUBSTANTIAL'
    )),
    capacity_risk TEXT NOT NULL DEFAULT 'UNCERTAIN' CHECK(capacity_risk IN (
        'BOUNDED', 'UNCERTAIN', 'EMERGENCY_RECOVERY'
    )),
    required_capabilities_json TEXT NOT NULL,
    priority INTEGER NOT NULL,
    acceptance_criteria_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN (
        'ON_DECK', 'READY', 'ACTIVE', 'VERIFY_REVIEW', 'BLOCKED', 'DONE'
    )),
    provider_diagnostics_json TEXT NOT NULL,
    branch TEXT,
    pr_url TEXT,
    ready_at TEXT,
    started_at TEXT,
    last_heartbeat_at TEXT,
    runtime_seconds REAL NOT NULL DEFAULT 0 CHECK(runtime_seconds >= 0),
    usage_consumption_json TEXT NOT NULL,
    failure_code TEXT,
    failure_detail TEXT,
    source_system TEXT,
    source_ref TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS task_dependencies (
    package_id TEXT NOT NULL REFERENCES work_packages(id),
    dependency_id TEXT NOT NULL REFERENCES work_packages(id),
    PRIMARY KEY(package_id, dependency_id),
    CHECK(package_id <> dependency_id)
);

CREATE TABLE IF NOT EXISTS leases (
    id TEXT PRIMARY KEY,
    package_id TEXT NOT NULL REFERENCES work_packages(id),
    worker_id TEXT NOT NULL REFERENCES workers(id),
    acquired_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    released_at TEXT,
    release_reason TEXT,
    CHECK(expires_at > acquired_at)
);

CREATE UNIQUE INDEX IF NOT EXISTS one_active_lease_per_package
    ON leases(package_id) WHERE released_at IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS one_active_lease_per_worker
    ON leases(worker_id) WHERE released_at IS NULL;

CREATE TRIGGER IF NOT EXISTS enforce_active_parent_limit
BEFORE INSERT ON leases
WHEN NEW.released_at IS NULL
 AND (SELECT kind FROM work_packages WHERE id = NEW.package_id) = 'PARENT'
 AND (
    SELECT COUNT(*)
    FROM leases AS active_lease
    JOIN work_packages AS active_package ON active_package.id = active_lease.package_id
    WHERE active_lease.released_at IS NULL
      AND active_lease.expires_at > NEW.acquired_at
      AND active_package.kind = 'PARENT'
 ) >= CAST((SELECT value FROM registry_metadata WHERE key = 'active_parent_limit') AS INTEGER)
BEGIN
    SELECT RAISE(ABORT, 'ACTIVE_PARENT_LIMIT');
END;

CREATE TRIGGER IF NOT EXISTS prevent_orchestra_lease
BEFORE INSERT ON leases
WHEN (SELECT role FROM workers WHERE id = NEW.worker_id) <> 'WORKER'
BEGIN
    SELECT RAISE(ABORT, 'ORCHESTRA_CANNOT_CLAIM');
END;

CREATE TABLE IF NOT EXISTS attempts (
    id TEXT PRIMARY KEY,
    package_id TEXT NOT NULL REFERENCES work_packages(id),
    worker_id TEXT REFERENCES workers(id),
    lease_id TEXT REFERENCES leases(id),
    started_at TEXT NOT NULL,
    ended_at TEXT,
    outcome TEXT,
    runtime_seconds REAL NOT NULL DEFAULT 0 CHECK(runtime_seconds >= 0),
    blocked_seconds REAL NOT NULL DEFAULT 0 CHECK(blocked_seconds >= 0),
    provider_diagnostics_json TEXT NOT NULL,
    failure_code TEXT,
    failure_detail TEXT
);

CREATE TABLE IF NOT EXISTS evidence (
    id TEXT PRIMARY KEY,
    package_id TEXT NOT NULL REFERENCES work_packages(id),
    kind TEXT NOT NULL,
    uri TEXT,
    summary TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS usage_observations (
    id TEXT PRIMARY KEY,
    worker_id TEXT REFERENCES workers(id),
    observed_at TEXT NOT NULL,
    reset_at TEXT,
    consumed_percent REAL,
    state TEXT NOT NULL,
    provider_diagnostics_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS usage_ledger (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    worker_id TEXT NOT NULL REFERENCES workers(id),
    account_id TEXT NOT NULL,
    invocation_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    observation_class TEXT NOT NULL CHECK(observation_class IN (
        'AUTONOMOUS', 'DIAGNOSTIC', 'LEGACY_UNCLASSIFIED'
    )),
    package_id TEXT REFERENCES work_packages(id),
    attempt_id TEXT REFERENCES attempts(id),
    observed_at TEXT NOT NULL,
    model_diagnostic TEXT,
    input_tokens INTEGER CHECK(input_tokens IS NULL OR input_tokens >= 0),
    output_tokens INTEGER CHECK(output_tokens IS NULL OR output_tokens >= 0),
    cache_read_input_tokens INTEGER CHECK(
        cache_read_input_tokens IS NULL OR cache_read_input_tokens >= 0
    ),
    cache_creation_input_tokens INTEGER CHECK(
        cache_creation_input_tokens IS NULL OR cache_creation_input_tokens >= 0
    ),
    duration_ms REAL CHECK(duration_ms IS NULL OR duration_ms >= 0),
    outcome TEXT NOT NULL,
    task_completed INTEGER NOT NULL DEFAULT 0 CHECK(task_completed IN (0, 1)),
    review_completed INTEGER NOT NULL DEFAULT 0 CHECK(review_completed IN (0, 1)),
    limit_signal TEXT,
    limit_reset_at TEXT,
    limit_raw_error TEXT,
    calibration_metadata_json TEXT NOT NULL,
    primary_source_type TEXT NOT NULL CHECK(primary_source_type IN (
        'CLI_JSON', 'CLI_STREAM_JSON', 'TRANSCRIPT'
    )),
    primary_source_identity TEXT NOT NULL UNIQUE,
    primary_source_metadata_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    CHECK(
        (observation_class='AUTONOMOUS' AND package_id IS NOT NULL AND attempt_id IS NOT NULL)
        OR (observation_class='DIAGNOSTIC' AND package_id IS NULL AND attempt_id IS NULL)
        OR observation_class='LEGACY_UNCLASSIFIED'
    ),
    UNIQUE(provider, worker_id, account_id, invocation_id)
);

CREATE TABLE IF NOT EXISTS usage_ledger_sources (
    id TEXT PRIMARY KEY,
    ledger_id TEXT NOT NULL REFERENCES usage_ledger(id),
    source_type TEXT NOT NULL CHECK(source_type IN (
        'CLI_JSON', 'CLI_STREAM_JSON', 'TRANSCRIPT'
    )),
    source_identity TEXT NOT NULL UNIQUE,
    observed_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS usage_ledger_is_append_only_update
BEFORE UPDATE ON usage_ledger
BEGIN
    SELECT RAISE(ABORT, 'USAGE_LEDGER_APPEND_ONLY');
END;

CREATE TRIGGER IF NOT EXISTS usage_ledger_is_append_only_delete
BEFORE DELETE ON usage_ledger
BEGIN
    SELECT RAISE(ABORT, 'USAGE_LEDGER_APPEND_ONLY');
END;

CREATE TRIGGER IF NOT EXISTS usage_ledger_sources_are_append_only_update
BEFORE UPDATE ON usage_ledger_sources
BEGIN
    SELECT RAISE(ABORT, 'USAGE_LEDGER_SOURCES_APPEND_ONLY');
END;

CREATE TRIGGER IF NOT EXISTS usage_ledger_sources_are_append_only_delete
BEFORE DELETE ON usage_ledger_sources
BEGIN
    SELECT RAISE(ABORT, 'USAGE_LEDGER_SOURCES_APPEND_ONLY');
END;

CREATE TABLE IF NOT EXISTS failure_observations (
    id TEXT PRIMARY KEY,
    package_id TEXT REFERENCES work_packages(id),
    worker_id TEXT REFERENCES workers(id),
    attempt_id TEXT REFERENCES attempts(id),
    code TEXT NOT NULL,
    detail TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS task_events (
    id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    package_id TEXT REFERENCES work_packages(id),
    worker_id TEXT REFERENCES workers(id),
    attempt_id TEXT REFERENCES attempts(id),
    detail_json TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS task_events_are_append_only_update
BEFORE UPDATE ON task_events
BEGIN
    SELECT RAISE(ABORT, 'TASK_EVENTS_APPEND_ONLY');
END;

CREATE TRIGGER IF NOT EXISTS task_events_are_append_only_delete
BEFORE DELETE ON task_events
BEGIN
    SELECT RAISE(ABORT, 'TASK_EVENTS_APPEND_ONLY');
END;

CREATE TABLE IF NOT EXISTS preservation_imports (
    id TEXT PRIMARY KEY,
    source_uri TEXT NOT NULL,
    source_sha256 TEXT NOT NULL UNIQUE,
    imported_at TEXT NOT NULL,
    snapshot_version INTEGER NOT NULL,
    reconciliation_json TEXT NOT NULL,
    raw_snapshot_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS preserved_artifacts (
    id TEXT PRIMARY KEY,
    import_id TEXT NOT NULL REFERENCES preservation_imports(id),
    kind TEXT NOT NULL,
    external_identity TEXT NOT NULL,
    dirty INTEGER NOT NULL DEFAULT 0 CHECK(dirty IN (0, 1)),
    metadata_json TEXT NOT NULL,
    UNIQUE(import_id, kind, external_identity)
);

CREATE INDEX IF NOT EXISTS work_packages_queue_order
    ON work_packages(status, priority, ready_at, created_at, id);
CREATE INDEX IF NOT EXISTS work_packages_feature
    ON work_packages(feature_id, status);
CREATE INDEX IF NOT EXISTS usage_ledger_worker_time
    ON usage_ledger(worker_id, observed_at);
CREATE INDEX IF NOT EXISTS usage_ledger_package_time
    ON usage_ledger(package_id, observed_at);
CREATE UNIQUE INDEX IF NOT EXISTS work_packages_source
    ON work_packages(source_system, source_ref)
    WHERE source_system IS NOT NULL AND source_ref IS NOT NULL;
