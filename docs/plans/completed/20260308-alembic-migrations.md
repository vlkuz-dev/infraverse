# Migrate to Alembic Schema Migrations

## Overview
- Currently `_migrate_schema()` in `db/engine.py` applies manual `ALTER TABLE` at runtime during every `init_db()` call
- 4 manual migrations exist: `tenant_id` on netbox_hosts, `last_sync_error`/`monitoring_exempt`/`monitoring_exempt_reason` on vms
- No migration history, no rollback capability, no versioning
- Goal: adopt Alembic for versioned migrations with rollback path, remove manual ALTER TABLE code

## Context
- **Manual migrations:** `src/infraverse/db/engine.py:30-56` — `_migrate_schema()` with 4 ALTER TABLE statements
- **Models:** `src/infraverse/db/models.py` — 6 tables (Tenant, CloudAccount, VM, MonitoringHost, NetBoxHost, SyncRun)
- **init_db:** `src/infraverse/db/engine.py:58-61` — creates tables + runs _migrate_schema
- **CLI:** `src/infraverse/cli.py:385-396` — `db init` command calls `init_db(engine)`
- **Dependencies:** `pyproject.toml` — SQLAlchemy >=2.0.0, no Alembic yet
- **Tests:** `tests/db/test_models.py:46-74` — test init_db creates tables and is idempotent

## Development Approach
- **Testing approach**: Regular (code first, then tests)
- Complete each task fully before moving to the next
- **CRITICAL: every task MUST include new/updated tests**
- **CRITICAL: all tests must pass before starting next task**
- **CRITICAL: update this plan file when scope changes during implementation**
- Run `python3 -m pytest tests/ -v` after each change

## Progress Tracking
- Mark completed items with `[x]` immediately when done
- Add newly discovered tasks with ➕ prefix
- Document issues/blockers with ⚠️ prefix

## Implementation Steps

### Task 1: Add Alembic dependency and initialize
- [x] add `alembic>=1.13` to `pyproject.toml` dependencies
- [x] run `alembic init src/infraverse/db/migrations` to scaffold migration directory
- [x] configure `alembic.ini` — set `script_location = src/infraverse/db/migrations`
- [x] configure `migrations/env.py` — import `Base` from models, set `target_metadata = Base.metadata`
- [x] configure SQLAlchemy URL: use `DATABASE_URL` env var with SQLite default
- [x] verify `alembic current` works with empty database
- [x] run tests — must pass before next task

### Task 2: Create initial migration from current schema
- [x] run `alembic revision --autogenerate -m "initial_schema"` to capture current model state
- [x] review generated migration — ensure all 6 tables with all columns are captured
- [x] handle existing databases: add `alembic stamp head` to mark existing DBs as current
- [x] update `db init` CLI command: call `alembic upgrade head` instead of `init_db()`
- [x] write test for fresh database: `alembic upgrade head` creates all tables
- [x] write test for existing database: `alembic stamp head` + `alembic upgrade head` is no-op
- [x] run tests — must pass before next task

### Task 3: Remove manual migration code
- [x] remove `_migrate_schema()` function from `db/engine.py`
- [x] simplify `init_db()` to only call `Base.metadata.create_all()` (for tests) or delegate to Alembic (for production)
- [x] keep `create_all()` path for test fixtures (simpler than running Alembic in tests)
- [x] update `test_models.py` — remove tests for `_migrate_schema()` if any
- [x] verify scheduler and CLI still initialize DB correctly
- [x] run tests — must pass before next task

### Task 4: Add `db migrate` and `db upgrade` CLI commands
- [x] add `db migrate` subcommand — wraps `alembic revision --autogenerate -m "<message>"`
- [x] add `db upgrade` subcommand — wraps `alembic upgrade head`
- [x] add `db downgrade` subcommand — wraps `alembic downgrade -1`
- [x] write tests for CLI commands (mock Alembic calls)
- [x] run tests — must pass before next task

### Task 5: Verify acceptance criteria
- [x] no `ALTER TABLE` statements in codebase (except in Alembic migrations)
- [x] `alembic upgrade head` on fresh DB creates all tables correctly
- [x] `alembic upgrade head` on existing DB is safe (stamped)
- [x] `alembic downgrade -1` rolls back last migration
- [x] all tests pass: `python3 -m pytest tests/ -v`
- [x] run linter: `ruff check src/ tests/`

### Task 6: [Final] Update documentation
- [x] update README.md with new `db migrate`/`db upgrade` commands
- [x] update MEMORY.md with Alembic patterns

## Technical Details

### Migration directory structure
```
src/infraverse/db/
├── engine.py          (simplified: create_engine, create_session_factory)
├── models.py          (unchanged)
├── repository.py      (unchanged)
└── migrations/
    ├── env.py         (Alembic env config)
    ├── script.py.mako (template)
    └── versions/
        └── 001_initial_schema.py
```

### Existing manual migrations to preserve in initial Alembic migration
| Table | Column | Type | Added by _migrate_schema |
|-------|--------|------|--------------------------|
| netbox_hosts | tenant_id | INTEGER FK→tenants.id | Yes |
| vms | last_sync_error | TEXT | Yes |
| vms | monitoring_exempt | BOOLEAN DEFAULT 0 | Yes |
| vms | monitoring_exempt_reason | TEXT | Yes |

### DB initialization flow change
```
BEFORE:
  init_db() → Base.metadata.create_all() → _migrate_schema() [ALTER TABLE]

AFTER (production):
  db init → alembic upgrade head

AFTER (tests):
  init_db() → Base.metadata.create_all()  [all columns in models, no migration needed]
```

## Post-Completion
- All future schema changes go through `alembic revision --autogenerate`
- Test downgrade path manually before deploying migrations
- Consider adding migration tests to CI pipeline
