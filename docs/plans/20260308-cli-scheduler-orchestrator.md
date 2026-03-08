# Extract CLI/Scheduler Shared Orchestration

## Overview
- `cli.py` and `scheduler.py` share nearly identical orchestration logic for building providers, Zabbix clients, running ingestion, and executing NetBox sync
- Both import ~14 internal modules and contain duplicated `_build_provider_from_account()` functions
- `sync/providers.py` already provides `build_provider()` and `build_providers_from_accounts()` but scheduler doesn't fully use them
- Scheduler's `_run_netbox_sync_per_account()` reimplements `SyncEngine._sync_provider()` logic
- Goal: extract shared orchestration into a single module, eliminating ~200 lines of duplication

## Context
- **CLI:** `src/infraverse/cli.py` — `_build_provider_from_account()` (lines 97-116), `_ingest_to_db()` (lines 118-203), `_ingest_to_db_with_config()` (lines 208-253), `cmd_sync()` (lines 260-299)
- **Scheduler:** `src/infraverse/scheduler.py` — `_build_provider_from_account()` (lines 181-200), `_build_providers()` (lines 136-179), `_build_zabbix_client()` (lines 202-240), `_run_ingestion()` (lines 91-135), `_run_netbox_sync()` (lines 283-339), `_run_netbox_sync_per_account()` (lines 341-413)
- **Existing abstractions:** `sync/providers.py` (build_provider, build_providers_from_accounts), `sync/engine.py` (SyncEngine)
- **Tests:** `tests/test_cli.py`, `tests/test_scheduler.py`

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

### Task 1: Remove duplicate `_build_provider_from_account()` — use `sync/providers.py`
- [x] verify `sync/providers.py:build_provider(account)` handles both `yandex_cloud` and `vcloud` types
- [x] replace CLI `_build_provider_from_account()` (lines 97-116) with call to `build_provider(account)`
- [x] replace Scheduler `_build_provider_from_account()` (lines 181-200) with call to `build_provider(account)`
- [x] handle the difference: CLI raises ValueError on unknown type, Scheduler returns None — standardize to return None + log warning (safer for scheduler loop)
- [x] update `_build_providers()` in scheduler to use `build_provider()` directly
- [x] verify all tests pass
- [x] write tests for edge case: unknown provider type returns None
- [x] run tests — must pass before next task

### Task 2: Extract Zabbix client builder to `sync/providers.py`
- [x] add `build_zabbix_client(infraverse_config=None, legacy_config=None) -> ZabbixClient | None` to `sync/providers.py`
- [x] consolidate logic from CLI (lines 195-203) and Scheduler (lines 202-240): both config modes in one function
- [x] replace CLI Zabbix building with `build_zabbix_client(legacy_config=config)`
- [x] replace Scheduler `_build_zabbix_client()` with call to `build_zabbix_client(infraverse_config=..., legacy_config=...)`
- [x] verify all tests pass
- [x] write tests for `build_zabbix_client()` — YAML config mode, env-var mode, no config case
- [x] run tests — must pass before next task

### Task 3: Extract ingestion cycle to shared function
- [x] create `sync/orchestrator.py` with function:
  ```python
  def run_ingestion_cycle(
      session,
      infraverse_config=None,
      legacy_config=None,
  ) -> dict:
  ```
  ⚠️ Signature uses `session` instead of `session_factory` — cleaner since both callers manage their own session lifecycle for post-ingestion steps
- [x] move shared logic: config-to-db sync, account loading, provider building, DataIngestor execution
- [x] refactor CLI `_ingest_to_db_with_config()` to call `run_ingestion_cycle()`
- [x] refactor Scheduler `_run_ingestion()` to call `run_ingestion_cycle()`
- [x] verify all tests pass
- [x] write tests for `run_ingestion_cycle()` — with YAML config, with legacy config, empty accounts
- [x] run tests — must pass before next task

### Task 4: Eliminate Scheduler's `_run_netbox_sync_per_account()` duplication
- [ ] verify `SyncEngine.run()` already handles per-provider iteration (lines 47-102 of engine.py)
- [ ] refactor Scheduler `_run_netbox_sync_per_account()` (lines 341-413) to use `SyncEngine` instead of reimplementing sync loop
- [ ] ensure scheduler passes correct `dry_run` flag to SyncEngine
- [ ] remove duplicated `sync_infrastructure` + `sync_vms_optimized` direct calls from scheduler
- [ ] verify all tests pass
- [ ] update scheduler tests to verify SyncEngine is called correctly
- [ ] run tests — must pass before next task

### Task 5: Prevent scheduler job overlap (P0)
- [ ] add `max_instances=1` to `add_job()` call in `scheduler.py:42` — prevents APScheduler from running concurrent instances
- [ ] add `coalesce=True` to `add_job()` — coalesce missed runs into single execution
- [ ] protect `trigger_now()` from overlapping with running interval job:
  - add `self._running` lock (threading.Lock or asyncio.Lock)
  - check lock in `_run_ingestion()` — skip with log warning if already running
- [ ] add `replace_existing=True` on manual trigger job to prevent duplicate job IDs
- [ ] write tests for `max_instances=1` and `coalesce=True` params passed to APScheduler
- [ ] write tests for concurrent trigger rejection (mock lock held → trigger returns "already running")
- [ ] write tests for normal trigger when no job is running
- [ ] run tests — must pass before next task

### Task 6: Verify acceptance criteria
- [ ] no `_build_provider_from_account()` function in cli.py or scheduler.py
- [ ] no `_build_zabbix_client()` method in SchedulerService
- [ ] scheduler uses SyncEngine instead of reimplementing sync loop
- [ ] `sync/providers.py` is the single source for provider/client building
- [ ] `sync/orchestrator.py` is the single source for ingestion cycle
- [ ] scheduler jobs have `max_instances=1` and `coalesce=True`
- [ ] manual trigger cannot overlap with running job
- [ ] all tests pass: `python3 -m pytest tests/ -v`
- [ ] run linter: `ruff check src/ tests/`

### Task 7: [Final] Update documentation
- [ ] update MEMORY.md with new module paths (orchestrator.py)
- [ ] update this plan with any deviations

## Technical Details

### Current duplication map
```
CLI                              Scheduler                        Shared (target)
─────────────────────────────────────────────────────────────────────────────────
_build_provider_from_account()   _build_provider_from_account()   sync/providers.py:build_provider()
                                 _build_providers()               sync/providers.py:build_providers_from_accounts()
Zabbix client init (inline)      _build_zabbix_client()           sync/providers.py:build_zabbix_client() [NEW]
_ingest_to_db_with_config()      _run_ingestion()                 sync/orchestrator.py:run_ingestion_cycle() [NEW]
cmd_sync() → SyncEngine          _run_netbox_sync_per_account()   → use SyncEngine.run() directly
```

### Error handling differences to reconcile
| Case | CLI behavior | Scheduler behavior | Target |
|------|-------------|-------------------|--------|
| Unknown provider | raises ValueError | returns None + warning | return None + warning |
| Zabbix build fails | skips (no try/except) | catches Exception, returns None | catch + return None |
| Provider build fails | logs error, skips account | logs warning, skips account | log warning, skip |

### Files affected
| File | Change |
|------|--------|
| `sync/providers.py` | Add `build_zabbix_client()` |
| `sync/orchestrator.py` | **NEW** — `run_ingestion_cycle()` |
| `cli.py` | Remove `_build_provider_from_account`, `_ingest_to_db`, simplify `_ingest_to_db_with_config` |
| `scheduler.py` | Remove `_build_provider_from_account`, `_build_providers`, `_build_zabbix_client`, `_run_netbox_sync_per_account`; simplify `_run_ingestion`, `_run_netbox_sync` |
| `tests/sync/test_providers.py` | Add tests for `build_zabbix_client()` |
| `tests/sync/test_orchestrator.py` | **NEW** — tests for `run_ingestion_cycle()` |

## Post-Completion
- CLI and scheduler should be thin wrappers around shared orchestration
- Future providers only need to be added in `sync/providers.py`
- Consider extracting NetBox client builder too if pattern grows
