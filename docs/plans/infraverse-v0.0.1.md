# Infraverse v0.0.1 - Clean Rewrite

## Overview
Transform netbox-yandexcloud-sync (a sync script) into Infraverse, a full infrastructure visibility platform.

**What changes:**
- Project renamed to Infraverse, new package `infraverse`, CLI command `infraverse`
- SQLite + SQLAlchemy ORM for persistent data storage (providers -> DB -> UI)
- Tenant / CloudAccount model for multi-customer, multi-cloud support
- Tabler admin template (CDN) replacing custom CSS UI
- Zabbix connection bug fix
- Clean package structure reflecting the new scope

**What stays:**
- Core business logic: cloud providers, sync engine, comparison engine, IP utilities
- FastAPI + Jinja2 + HTMX web stack
- Existing test coverage (ported to new structure)

**Deferred to v0.0.2+:**
- Scheduled data fetching (cron-like)
- Manual "fetch now" button in UI
- Detail pages for individual VMs and clouds
- Quick-filter buttons (all VMs / problematic / normal)
- External resource links on detail pages

## Context (from discovery)
- Source: `src/netbox_sync/` (30 files, ~5K LOC)
- Tests: `tests/` (25 modules, 490+ tests)
- Web UI: FastAPI + Jinja2 + HTMX, 4 templates, custom CSS
- No database - all data fetched on-demand from APIs
- Providers: Yandex Cloud (httpx), vCloud Director (httpx), Zabbix (JSON-RPC), NetBox (pynetbox)
- Config: env vars via python-dotenv, `.env` file
- Dependencies: httpx, pynetbox, python-dotenv, fastapi, jinja2, uvicorn

## Development Approach
- **Testing approach**: Regular (code first, then tests)
- Complete each task fully before moving to the next
- Make small, focused changes
- **CRITICAL: every task MUST include new/updated tests** for code changes in that task
- **CRITICAL: all tests must pass before starting next task**
- **CRITICAL: update this plan file when scope changes during implementation**
- Run tests after each change
- Maintain backward compatibility for sync-to-NetBox functionality

## Testing Strategy
- **Unit tests**: required for every task
- **Run command**: `python3 -m pytest tests/ -v`
- **Linter**: `ruff check src/ tests/`

## Progress Tracking
- Mark completed items with `[x]` immediately when done
- Add newly discovered tasks with + prefix
- Document issues/blockers with ! prefix
- Update plan if implementation deviates from original scope

## New Package Structure

```
src/infraverse/
  __init__.py
  __main__.py
  cli.py
  config.py
  db/
    __init__.py
    engine.py          # SQLAlchemy engine, session factory
    models.py          # ORM models: Tenant, CloudAccount, VM, MonitoringHost, SyncRun
    repository.py      # Data access layer (CRUD operations)
  providers/           # was clients/
    __init__.py
    base.py            # CloudProvider protocol, VMInfo dataclass
    yandex.py          # Yandex Cloud API client
    vcloud.py          # vCloud Director API client
    zabbix.py          # Zabbix JSON-RPC client
    netbox.py          # NetBox API wrapper (pynetbox)
  sync/
    __init__.py
    engine.py          # Top-level orchestrator
    infrastructure.py  # Sites, clusters, prefixes sync
    vms.py             # VM sync logic
    batch.py           # Optimized batch operations
    cleanup.py         # Orphaned object cleanup
  comparison/
    __init__.py
    engine.py          # Cross-system matching
    models.py          # VMState, ComparisonResult
  ip/
    __init__.py
    classifier.py      # Private IP detection
    utils.py           # CIDR helpers
  web/
    __init__.py
    app.py             # FastAPI app factory
    routes/
      __init__.py
      dashboard.py     # Dashboard routes
      comparison.py    # Comparison routes
    templates/
      base.html        # Tabler layout with sidebar
      dashboard.html   # Provider status, summary cards
      comparison.html  # Comparison table (full page)
      comparison_table.html  # HTMX partial
    static/
      style.css        # Custom overrides (minimal)
tests/
  conftest.py
  db/
    test_models.py
    test_repository.py
  providers/
    test_base.py
    test_yandex.py
    test_vcloud.py
    test_zabbix.py
    test_netbox.py
  sync/
    test_engine.py
    test_infrastructure.py
    test_vms.py
    test_batch.py
    test_cleanup.py
  web/
    test_app.py
    test_dashboard.py
    test_comparison.py
  test_comparison_engine.py
  test_config.py
  test_package.py
```

## Database Models

```
Tenant
  id: Integer PK
  name: String unique
  description: String nullable
  created_at: DateTime
  updated_at: DateTime

CloudAccount
  id: Integer PK
  tenant_id: Integer FK -> Tenant
  provider_type: String (yandex_cloud | vcloud | netbox)
  name: String (display label, e.g. "YC Russia", "vCloud@Dataspace")
  config: JSON (provider-specific config, no secrets - those stay in env)
  created_at: DateTime
  updated_at: DateTime

VM
  id: Integer PK
  cloud_account_id: Integer FK -> CloudAccount
  external_id: String (provider's VM ID)
  name: String
  status: String (active | offline | unknown)
  ip_addresses: JSON (list of strings)
  vcpus: Integer
  memory_mb: Integer
  cloud_name: String nullable
  folder_name: String nullable
  last_seen_at: DateTime
  created_at: DateTime
  updated_at: DateTime

MonitoringHost
  id: Integer PK
  source: String (zabbix)
  external_id: String
  name: String
  status: String (active | offline)
  ip_addresses: JSON (list of strings)
  last_seen_at: DateTime
  created_at: DateTime
  updated_at: DateTime

SyncRun
  id: Integer PK
  cloud_account_id: Integer FK -> CloudAccount nullable
  source: String (yandex_cloud | vcloud | zabbix | netbox)
  started_at: DateTime
  finished_at: DateTime nullable
  status: String (running | success | failed)
  items_found: Integer default 0
  items_created: Integer default 0
  items_updated: Integer default 0
  error_message: String nullable
```

## Tenant/CloudAccount Design

**Problem:** One customer can have multiple Yandex Clouds (RU, KZ). Same cloud at different customers. vCloud at different providers (Dataspace, GlobalIT).

**Solution:**
- Tenant = customer/organization (e.g. "Customer A")
- CloudAccount = one cloud connection belonging to a tenant
  - "Customer A" -> "YC Russia" (yandex_cloud), "YC Kazakhstan" (yandex_cloud), "vCloud@Dataspace" (vcloud)
  - "Customer B" -> "YC Russia" (yandex_cloud), "vCloud@GlobalIT" (vcloud)
- Same physical cloud can appear as different CloudAccounts under different tenants
- VMs belong to a CloudAccount, not directly to a tenant
- Credentials stay in .env (not in DB) - CloudAccount.config stores non-secret settings like org name, API endpoint overrides

## Implementation Steps

### Task 1: Project rename and new package skeleton
- [x] Create `src/infraverse/__init__.py` with `__version__ = "0.0.1"`
- [x] Create `src/infraverse/__main__.py` (copy from netbox_sync, update imports)
- [x] Create all subdirectory `__init__.py` files (db, providers, sync, comparison, ip, web, web/routes)
- [x] Update `pyproject.toml`: name="infraverse", version="0.0.1", update scripts entry to `infraverse = "infraverse.cli:main"`, add sqlalchemy dependency, update package-data paths, update URLs
- [x] Remove old `src/netbox_sync/` directory
- [x] Write tests: verify package imports and version
- [x] Run tests - must pass before next task

### Task 2: Port configuration module
- [x] Create `src/infraverse/config.py` - copy from netbox_sync, add `database_url` field (default: `sqlite:///infraverse.db`)
- [x] Add `DATABASE_URL` env var support in `Config.from_env()`
- [x] Write tests for Config (existing tests adapted + new DATABASE_URL test)
- [x] Run tests - must pass before next task

### Task 3: Database layer - engine and models
- [x] Create `src/infraverse/db/engine.py` with `create_engine()`, `SessionLocal`, `init_db()` (creates all tables)
- [x] Create `src/infraverse/db/models.py` with SQLAlchemy ORM models: Tenant, CloudAccount, VM, MonitoringHost, SyncRun
- [x] Write tests for model creation, relationships (Tenant->CloudAccounts->VMs), and table initialization
- [x] Write tests for edge cases (unique constraints, nullable fields, JSON columns)
- [x] Run tests - must pass before next task

### Task 4: Database repository layer
- [x] Create `src/infraverse/db/repository.py` with Repository class
- [x] Implement tenant CRUD: `create_tenant()`, `get_tenant()`, `list_tenants()`, `delete_tenant()`
- [x] Implement cloud account CRUD: `create_cloud_account()`, `get_cloud_account()`, `list_cloud_accounts()`, `list_cloud_accounts_by_tenant()`
- [x] Implement VM operations: `upsert_vm()`, `get_vms_by_account()`, `get_all_vms()`, `mark_vms_stale()` (VMs not seen in last sync)
- [x] Implement monitoring host operations: `upsert_monitoring_host()`, `get_all_monitoring_hosts()`
- [x] Implement sync run operations: `create_sync_run()`, `update_sync_run()`, `get_latest_sync_runs()`
- [x] Write tests for all CRUD operations (success cases)
- [x] Write tests for edge cases (duplicate names, missing FKs, upsert behavior)
- [x] Run tests - must pass before next task

### Task 5: Port IP utilities
- [x] Copy `src/netbox_sync/ip/classifier.py` -> `src/infraverse/ip/classifier.py`
- [x] Copy `src/netbox_sync/ip/utils.py` -> `src/infraverse/ip/utils.py`
- [x] Port existing IP tests, update imports
- [x] Run tests - must pass before next task

### Task 6: Port provider clients (base, yandex, vcloud, netbox)
- [x] Copy `src/netbox_sync/clients/base.py` -> `src/infraverse/providers/base.py`
- [x] Copy `src/netbox_sync/clients/yandex.py` -> `src/infraverse/providers/yandex.py`, update imports
- [x] Copy `src/netbox_sync/clients/vcloud.py` -> `src/infraverse/providers/vcloud.py`, update imports
- [x] Copy `src/netbox_sync/clients/netbox.py` -> `src/infraverse/providers/netbox.py`, update imports
- [x] Port all client tests, update imports to `infraverse.providers.*`
- [x] Run tests - must pass before next task

### Task 7: Fix Zabbix client and port
- [x] Copy `src/netbox_sync/clients/zabbix.py` -> `src/infraverse/providers/zabbix.py`, update imports
- [x] Diagnose Zabbix connection error: check .env credentials, test with `LOG_LEVEL=DEBUG`
- [x] Fix likely issues: Zabbix 5.4+ uses `username` instead of `user` param in `user.login` - support both, SSL verification for self-signed certs (add `verify_ssl` config option), URL normalization
- [x] Port Zabbix tests, add tests for the fix (both old and new API parameter names)
- [x] Run tests - must pass before next task

### Task 8: Port sync modules
- [x] Copy `src/netbox_sync/sync/engine.py` -> `src/infraverse/sync/engine.py`, update imports
- [x] Copy `src/netbox_sync/sync/infrastructure.py` -> `src/infraverse/sync/infrastructure.py`, update imports
- [x] Copy `src/netbox_sync/sync/vms.py` -> `src/infraverse/sync/vms.py`, update imports
- [x] Copy `src/netbox_sync/sync/batch.py` -> `src/infraverse/sync/batch.py`, update imports
- [x] Copy `src/netbox_sync/sync/cleanup.py` -> `src/infraverse/sync/cleanup.py`, update imports
- [x] Port all sync tests, update imports
- [x] Run tests - must pass before next task

### Task 9: Port comparison engine
- [x] Copy `src/netbox_sync/comparison/engine.py` -> `src/infraverse/comparison/engine.py`, update imports
- [x] Copy `src/netbox_sync/comparison/models.py` -> `src/infraverse/comparison/models.py`
- [x] Port comparison tests, update imports
- [x] Run tests - must pass before next task

### Task 10: Tabler UI - base template and static assets
- [x] Create `src/infraverse/web/templates/base.html` with Tabler CDN layout (sidebar nav: Dashboard, Comparison), responsive, HTMX included
- [x] Create `src/infraverse/web/static/style.css` with minimal custom overrides for Tabler
- [x] Verify Tabler CDN resources load correctly (check tabler.io for latest CDN links)
- [x] Write basic template rendering test
- [x] Run tests - must pass before next task

### Task 11: Web app factory and dashboard route
- [x] Create `src/infraverse/web/app.py` - FastAPI app factory, mount static files, include routers, inject DB session dependency
- [x] Create `src/infraverse/web/routes/__init__.py` with combined router
- [x] Create `src/infraverse/web/routes/dashboard.py` - dashboard route reading provider status from DB (CloudAccounts, latest SyncRuns)
- [x] Create `src/infraverse/web/templates/dashboard.html` - Tabler cards for provider status, tenant overview, last sync timestamps, summary stats
- [x] Write tests for dashboard route (mock DB)
- [x] Run tests - must pass before next task

### Task 12: Comparison route with DB-backed data
- [x] Create `src/infraverse/web/routes/comparison.py` - comparison route reading VMs and monitoring hosts from DB instead of live API calls
- [x] Create `src/infraverse/web/templates/comparison.html` - Tabler table with filters (provider dropdown, status select, name search), HTMX refresh
- [x] Create `src/infraverse/web/templates/comparison_table.html` - HTMX partial for table content
- [x] Wire ComparisonEngine to use DB-sourced data
- [x] Write tests for comparison route (mock DB data)
- [x] Write tests for filter combinations
- [x] Run tests - must pass before next task

### Task 13: CLI entry point
- [x] Create `src/infraverse/cli.py` with subcommands: `sync`, `serve`, `db init` (create tables), `db seed` (create default tenant)
- [x] `sync` command: fetch from providers, store in DB, then sync to NetBox
- [x] `serve` command: start web UI reading from DB
- [x] `db init` command: initialize database tables
- [x] Wire `load_dotenv()` before config loading
- [x] Write tests for CLI argument parsing
- [x] Run tests - must pass before next task

### Task 14: Data ingestion - providers to DB
- [x] Create `src/infraverse/sync/ingest.py` - DataIngestor class that fetches from all configured providers and stores results in DB
- [x] Implement `ingest_cloud_vms(cloud_account)`: fetch VMs from provider, upsert into DB, create SyncRun record
- [x] Implement `ingest_monitoring_hosts()`: fetch from Zabbix, upsert into DB
- [x] Implement `ingest_all()`: iterate over all CloudAccounts, ingest each
- [x] Write tests for ingestion flow (mock providers, real SQLite DB)
- [x] Write tests for error handling (provider failure doesn't stop other providers)
- [x] Run tests - must pass before next task

### Task 15: Verify acceptance criteria
- [ ] Verify project imports as `infraverse` and CLI runs as `infraverse`
- [ ] Verify SQLite DB is created and populated on `infraverse db init`
- [ ] Verify Tenant -> CloudAccount -> VM model works end-to-end
- [ ] Verify Zabbix client connects without error (manual test with .env)
- [ ] Verify Tabler UI renders on `infraverse serve` (dashboard + comparison)
- [ ] Verify comparison reads from DB, not live API
- [ ] Verify sync-to-NetBox still works: `infraverse sync`
- [ ] Run full test suite (unit tests)
- [ ] Run linter (`ruff check src/ tests/`) - all issues must be fixed
- [ ] Verify test count is comparable to original (~490+ tests)

### Task 16: [Final] Update documentation
- [ ] Update README.md: new project name, installation, usage, architecture diagram
- [ ] Update `.env.example`: add DATABASE_URL, document tenant/cloud account setup
- [ ] Update project knowledge docs if new patterns discovered

## Technical Details

### New Dependencies (pyproject.toml)
- `sqlalchemy>=2.0.0` - ORM
- Existing: httpx, pynetbox, python-dotenv, fastapi, jinja2, uvicorn

### Tabler Integration
- Use Tabler CDN (CSS + JS) in base template - no npm/build step needed
- Tabler components used: page layout with sidebar, cards, tables, badges, alerts, form controls
- Custom CSS only for app-specific overrides (minimal)

### Data Flow (new)
```
Provider APIs -> DataIngestor -> SQLite DB -> Web UI (read from DB)
                                           -> ComparisonEngine (read from DB)
                                           -> SyncEngine -> NetBox API (existing flow preserved)
```

### Credentials Management
- All secrets stay in `.env` / environment variables (never in DB)
- CloudAccount.config stores non-secret settings (API endpoint, org name, region)
- Provider client instantiation reads from env + CloudAccount.config

### Migration Path
- No Alembic migrations for v0.0.1 (fresh DB, `init_db()` creates all tables)
- Alembic can be added in v0.0.2 when schema evolves

## Post-Completion

**Manual verification:**
- Start `infraverse serve`, verify Tabler UI loads correctly
- Run `infraverse sync --dry-run` to verify NetBox sync still works
- Verify Zabbix connection with real credentials from .env
- Check comparison page shows data from DB

**Follow-up plans (v0.0.2+):**
- Scheduled data fetching with configurable intervals
- Manual "fetch now" button in UI
- Detail pages for individual VMs and clouds with external links
- Quick-filter buttons/checkboxes (all VMs, problematic only, normal only)
- Repository migration (new git remote, GitHub repo rename)
