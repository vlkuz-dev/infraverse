# Infraverse v0.0.2 - Scheduler, Detail Pages, and UI Enhancements

## Overview
Extend Infraverse with automated data fetching, richer UI, and repository housekeeping:
- **Scheduled data fetching** via APScheduler with configurable intervals
- **Manual "fetch now" button** in the web UI to trigger on-demand ingestion
- **Detail pages** for individual VMs and cloud accounts with external resource links
- **Quick-filter buttons** on comparison page (all / problematic / normal)
- **Repository migration** - rename git remote from `netbox-yandexcloud-sync` to `infraverse`

These features close the gap between "data is in DB" (v0.0.1) and "data stays fresh automatically with rich browsing."

## Context (from discovery)
- **Source**: `src/infraverse/` - 30+ files, ~5K LOC
- **Tests**: `tests/` - 500+ tests, runs in <1s
- **Web**: FastAPI + Jinja2 + HTMX + Tabler CDN, routes in `web/routes/`
- **DB**: SQLAlchemy ORM (Tenant, CloudAccount, VM, MonitoringHost, SyncRun)
- **Ingestion**: `sync/ingest.py` - DataIngestor fetches from providers, stores in DB
- **CLI**: `cli.py` - subcommands: sync, serve, db init, db seed
- **Current data flow**: `infraverse sync` (CLI) -> providers -> DB -> web UI reads from DB
- **Git remote**: `https://github.com/vlkuz-dev/infraverse.git`

## Development Approach
- **Testing approach**: Regular (code first, then tests)
- Complete each task fully before moving to the next
- Make small, focused changes
- **CRITICAL: every task MUST include new/updated tests** for code changes in that task
  - tests are not optional - they are a required part of the checklist
  - write unit tests for new functions/methods
  - write unit tests for modified functions/methods
  - add new test cases for new code paths
  - update existing test cases if behavior changes
  - tests cover both success and error scenarios
- **CRITICAL: all tests must pass before starting next task** - no exceptions
- **CRITICAL: update this plan file when scope changes during implementation**
- Run tests after each change
- Maintain backward compatibility

## Testing Strategy
- **Unit tests**: required for every task
- **Run command**: `python3 -m pytest tests/ -v`
- **Linter**: `ruff check src/ tests/`

## Progress Tracking
- Mark completed items with `[x]` immediately when done
- Add newly discovered tasks with ➕ prefix
- Document issues/blockers with ⚠️ prefix
- Update plan if implementation deviates from original scope
- Keep plan in sync with actual work done

## What Goes Where
- **Implementation Steps** (`[ ]` checkboxes): tasks achievable within this codebase - code changes, tests, documentation updates
- **Post-Completion** (no checkboxes): items requiring external action - manual testing, changes in consuming projects, deployment configs, third-party verifications

## Implementation Steps

### Task 1: Add APScheduler dependency and scheduler service
- [x] Add `apscheduler>=3.10.0` to `pyproject.toml` dependencies
- [x] Create `src/infraverse/scheduler.py` with `SchedulerService` class
- [x] Implement `start(interval_minutes: int)` that schedules `_run_ingestion()` job at given interval
- [x] Implement `stop()` to gracefully shut down the scheduler
- [x] Implement `trigger_now()` to run ingestion immediately (outside schedule)
- [x] Implement `get_status() -> dict` returning scheduler state (running, next_run_time, last_run_time, last_result)
- [x] `_run_ingestion()` reuses `DataIngestor` logic from `sync/ingest.py` with its own DB session
- [x] Write tests for SchedulerService: start/stop lifecycle
- [x] Write tests for trigger_now() execution
- [x] Write tests for get_status() with various states (idle, running, after success, after error)
- [x] Run tests - must pass before next task

### Task 2: Integrate scheduler with FastAPI lifespan
- [x] Add `SYNC_INTERVAL_MINUTES` env var to `config.py` (default: 0 = disabled)
- [x] Update `web/app.py` to accept scheduler config and start scheduler in FastAPI lifespan if interval > 0
- [x] Store `SchedulerService` instance in `app.state.scheduler`
- [x] Ensure scheduler stops cleanly on app shutdown
- [x] Write tests for config with SYNC_INTERVAL_MINUTES (0, 30, custom values)
- [x] Write tests for app startup with scheduler enabled vs disabled
- [x] Write tests for app shutdown stops scheduler
- [x] Run tests - must pass before next task

### Task 3: Add "fetch now" API endpoint and UI button
- [x] Create `src/infraverse/web/routes/sync.py` with `POST /sync/trigger` route
- [x] Route calls `app.state.scheduler.trigger_now()` and returns status
- [x] Add `GET /sync/status` route returning scheduler status as JSON (for HTMX polling)
- [x] Register sync routes in `web/routes/__init__.py`
- [x] Add "Fetch Now" button to `dashboard.html` using HTMX: `hx-post="/sync/trigger"` with loading indicator
- [x] Add scheduler status display on dashboard (next scheduled run, last run result)
- [x] Write tests for POST /sync/trigger (success, scheduler not configured)
- [x] Write tests for GET /sync/status response format
- [x] Run tests - must pass before next task

### Task 4: Quick-filter buttons on comparison page
- [ ] Update `comparison.html` to add button group above the filter card: "All", "With Issues", "In Sync"
- [ ] Buttons use HTMX `hx-get="/comparison/table?status=..."` to refresh the table
- [ ] Active button gets visual highlight (Tabler `btn-primary` vs `btn-outline-primary`)
- [ ] Wire buttons to work together with existing provider and search filters (include current filter params in HTMX request)
- [ ] Write tests for comparison table route with each filter value
- [ ] Write tests for combined filters (status + provider + search)
- [ ] Run tests - must pass before next task

### Task 5: VM detail page
- [ ] Add `get_vm_by_id(vm_id)` method to `db/repository.py`
- [ ] Create `src/infraverse/web/routes/vms.py` with `GET /vms/{vm_id}` route
- [ ] Create `src/infraverse/web/templates/vm_detail.html` with Tabler card layout:
  - VM name, status badge, external ID
  - IP addresses list
  - Resources (vCPUs, memory)
  - Cloud account and tenant info
  - Timestamps (created, updated, last seen)
  - Comparison status (in NetBox?, in monitoring?)
  - External links section (see Task 7)
- [ ] Register VM routes in `web/routes/__init__.py`
- [ ] Add link from comparison table VM names to detail page
- [ ] Write tests for GET /vms/{vm_id} with valid VM
- [ ] Write tests for GET /vms/{vm_id} with non-existent VM (404)
- [ ] Run tests - must pass before next task

### Task 6: Cloud account detail page
- [ ] Add `get_cloud_account_with_tenant(account_id)` method to `db/repository.py` (joins tenant)
- [ ] Create `src/infraverse/web/routes/accounts.py` with `GET /accounts/{account_id}` route
- [ ] Create `src/infraverse/web/templates/account_detail.html` with Tabler card layout:
  - Account name, provider type badge, tenant name
  - VM count and status summary (active/offline)
  - List of VMs (table with links to VM detail)
  - Latest sync runs for this account
  - Config info (non-secret settings from CloudAccount.config)
- [ ] Register account routes in `web/routes/__init__.py`
- [ ] Add links from dashboard provider/tenant tables to account detail
- [ ] Write tests for GET /accounts/{account_id} with valid account
- [ ] Write tests for GET /accounts/{account_id} with non-existent account (404)
- [ ] Run tests - must pass before next task

### Task 7: External resource links on detail pages
- [ ] Add `external_links` config section to `config.py`: URL templates for Yandex Cloud console, vCloud UI, Zabbix host, NetBox VM
- [ ] Default templates: `YC_CONSOLE_URL=https://console.yandex.cloud/folders/{folder_id}/compute/instances/{vm_id}`, `ZABBIX_HOST_URL={zabbix_url}/hosts.php?form=update&hostid={host_id}`, `NETBOX_VM_URL={netbox_url}/virtualization/virtual-machines/{vm_id}/`
- [ ] Create `src/infraverse/web/links.py` helper that renders URLs from templates + VM/host data
- [ ] Add external link buttons to `vm_detail.html` (cloud console, NetBox, Zabbix)
- [ ] Add external link to `account_detail.html` (cloud console)
- [ ] Write tests for URL template rendering with various data
- [ ] Write tests for missing data (graceful fallback - no link shown)
- [ ] Run tests - must pass before next task

### Task 8: Sidebar navigation update
- [ ] Update `base.html` sidebar to add new navigation items: "Cloud Accounts" section with link to accounts list
- [ ] Add `GET /accounts` route listing all cloud accounts grouped by tenant
- [ ] Create `src/infraverse/web/templates/accounts_list.html` - table of all accounts with links to detail pages
- [ ] Write tests for GET /accounts route
- [ ] Run tests - must pass before next task

### Task 9: Repository migration
- [ ] Rename local directory reference in documentation (README.md)
- [ ] Update any hardcoded repository references in source files (check pyproject.toml URLs - already correct)
- [ ] Verify `.git/config` remote points to correct URL
- [ ] Update `CLAUDE.md` or memory files if they reference old paths/names
- [ ] Run tests - must pass before next task

### Task 10: Version bump
- [ ] Update version to `0.0.2` in `src/infraverse/__init__.py`
- [ ] Update version to `0.0.2` in `pyproject.toml`
- [ ] Write test verifying version string is `0.0.2`
- [ ] Run tests - must pass before next task

### Task 11: Verify acceptance criteria
- [ ] Verify scheduler starts with `infraverse serve` when SYNC_INTERVAL_MINUTES > 0
- [ ] Verify "Fetch Now" button triggers ingestion and shows result
- [ ] Verify scheduler status displayed on dashboard
- [ ] Verify quick-filter buttons work on comparison page
- [ ] Verify VM detail page renders with all fields and external links
- [ ] Verify cloud account detail page renders with VM list and sync history
- [ ] Verify accounts list page shows all accounts grouped by tenant
- [ ] Verify all existing functionality still works (sync, comparison, dashboard)
- [ ] Run full test suite (unit tests)
- [ ] Run linter (`ruff check src/ tests/`) - all issues must be fixed
- [ ] Verify test count is comparable to v0.0.1 (~500+) plus new tests

### Task 12: [Final] Update documentation
- [ ] Update README.md with new features: scheduler, fetch-now, detail pages, quick-filters
- [ ] Add SYNC_INTERVAL_MINUTES and external link URL env vars to `.env.example`
- [ ] Update project knowledge docs if new patterns discovered

## Technical Details

### APScheduler Integration
```python
from apscheduler.schedulers.background import BackgroundScheduler

class SchedulerService:
    def __init__(self, session_factory, config):
        self._scheduler = BackgroundScheduler()
        self._session_factory = session_factory
        self._config = config
        self._last_result = None
        self._last_run_time = None

    def start(self, interval_minutes: int):
        self._scheduler.add_job(
            self._run_ingestion,
            'interval',
            minutes=interval_minutes,
            id='ingestion',
            replace_existing=True,
        )
        self._scheduler.start()

    def trigger_now(self):
        self._scheduler.modify_job('ingestion', next_run_time=datetime.now())

    def _run_ingestion(self):
        session = self._session_factory()
        try:
            repo = Repository(session)
            ingestor = DataIngestor(repo)
            # ... instantiate providers from config, call ingest_all()
        finally:
            session.close()
```

### FastAPI Lifespan Integration
```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app):
    if app.state.config.sync_interval_minutes > 0:
        app.state.scheduler.start(app.state.config.sync_interval_minutes)
    yield
    if hasattr(app.state, 'scheduler'):
        app.state.scheduler.stop()
```

### External Link URL Templates
```
YC_CONSOLE_URL=https://console.yandex.cloud/folders/{folder_id}/compute/instances/{vm_id}
VCD_CONSOLE_URL={vcd_url}/tenant/{org}/vdcs/{vdc}/vapp/{vapp}/vm/{vm}
ZABBIX_HOST_URL={zabbix_url}/hosts.php?form=update&hostid={host_id}
NETBOX_VM_URL={netbox_url}/virtualization/virtual-machines/{vm_id}/
```

### New/Changed Files Summary
```
New:
  src/infraverse/scheduler.py          # APScheduler service
  src/infraverse/web/routes/sync.py    # Fetch-now and status endpoints
  src/infraverse/web/routes/vms.py     # VM detail route
  src/infraverse/web/routes/accounts.py # Cloud account routes
  src/infraverse/web/links.py          # External URL template helper
  src/infraverse/web/templates/vm_detail.html
  src/infraverse/web/templates/account_detail.html
  src/infraverse/web/templates/accounts_list.html
  tests/test_scheduler.py
  tests/web/test_sync_routes.py
  tests/web/test_vm_detail.py
  tests/web/test_account_detail.py
  tests/web/test_accounts_list.py
  tests/web/test_links.py

Modified:
  pyproject.toml                       # APScheduler dep, version bump
  src/infraverse/__init__.py           # Version bump
  src/infraverse/config.py             # SYNC_INTERVAL_MINUTES, external link URLs
  src/infraverse/web/app.py            # Scheduler lifespan integration
  src/infraverse/web/routes/__init__.py # Register new routes
  src/infraverse/web/templates/base.html # Sidebar nav update
  src/infraverse/web/templates/dashboard.html # Fetch-now button, scheduler status
  src/infraverse/web/templates/comparison.html # Quick-filter buttons
  src/infraverse/web/templates/comparison_table.html # VM name links to detail
  src/infraverse/db/repository.py      # get_vm_by_id, get_cloud_account_with_tenant
```

### New Dependencies (pyproject.toml)
- `apscheduler>=3.10.0` - Background job scheduler

## Post-Completion

**Manual verification:**
- Start `infraverse serve` with `SYNC_INTERVAL_MINUTES=5`, verify ingestion runs on schedule
- Click "Fetch Now" button, verify data updates in dashboard
- Navigate through VM detail and account detail pages
- Test quick-filter buttons on comparison page
- Verify external links open correct URLs in cloud consoles / NetBox / Zabbix
- Check responsive layout on mobile screens

**Follow-up plans (v0.0.3+):**
- Tenant/account management UI (create, edit, delete accounts from web)
- Export comparison results to CSV/JSON
- Alembic migrations for schema evolution
- Alerts/notifications for new discrepancies
- Multi-user auth and RBAC
