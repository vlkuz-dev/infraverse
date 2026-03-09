# Repository Simplification

## Overview
- `db/repository.py` has 32 public methods with 5 critical overlaps
- Naming is inconsistent: `list_*` for some entities, `get_all_*` for others
- CloudAccount has 3 list methods doing similar things with different eager-loading
- `get_vms_by_account()` duplicates `get_all_vms(account_id=...)` functionality
- Some methods are unused in production code (`get_cloud_account()`, `delete_tenant()`, `status` param in `get_all_vms`)
- Goal: consolidate overlaps, unify naming, remove dead code — reduce from 32 to ~26 methods

## Context
- **File:** `src/infraverse/db/repository.py` (554 lines, 32 methods across 6 entities)
- **Tests:** `tests/db/test_repository.py` (~87 test methods)
- **Callers:** cli.py, scheduler.py, web/routes/*, sync/ingest.py, sync/config_sync.py, comparison/engine.py

### Method overlap summary
| Overlap | Methods | Resolution |
|---------|---------|------------|
| CloudAccount lists | `list_cloud_accounts()`, `list_cloud_accounts_with_tenants()`, `list_cloud_accounts_by_tenant()` | Consolidate to 1-2 |
| CloudAccount get | `get_cloud_account()`, `get_cloud_account_with_tenant()` | Keep only `_with_tenant` variant |
| VM lists | `get_vms_by_account()`, `get_all_vms(account_id=...)` | Remove `get_vms_by_account` |
| Naming prefix | `list_*` vs `get_all_*` | Standardize to `list_*` |

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

### Task 1: Consolidate CloudAccount list methods (3 → 2)
- [x] refactor `list_cloud_accounts(tenant_id=None, with_relations=False)` to accept optional params:
  - `tenant_id=None` — filter by tenant (replaces `list_cloud_accounts_by_tenant`)
  - `with_relations=False` — eager-load tenant + VMs (replaces `list_cloud_accounts_with_tenants`)
- [x] update callers:
  - `cli.py`: `list_cloud_accounts_by_tenant(tid)` → `list_cloud_accounts(tenant_id=tid)`
  - `dashboard.py`: conditional `list_cloud_accounts_by_tenant()` / `list_cloud_accounts()` → single `list_cloud_accounts(tenant_id=tid)`
  - `accounts.py`: `list_cloud_accounts_with_tenants(tid)` → `list_cloud_accounts(tenant_id=tid, with_relations=True)`
  - `comparison.py`: `list_cloud_accounts()` → unchanged (default params)
- [x] remove `list_cloud_accounts_by_tenant()` and `list_cloud_accounts_with_tenants()` methods
- [x] verify all tests pass
- [x] update tests that reference removed methods
- [x] run tests — must pass before next task

### Task 2: Consolidate CloudAccount get methods (2 → 1)
- [x] verify `get_cloud_account()` (line 68, no joins) is unused in production code
- [x] rename `get_cloud_account_with_tenant()` → `get_cloud_account()` with eager loading by default
- [x] update all callers (currently only web routes use `_with_tenant` variant)
- [x] verify all tests pass
- [x] update tests that reference old method names
- [x] run tests — must pass before next task

### Task 3: Remove `get_vms_by_account()` duplicate
- [x] verify `get_vms_by_account(account_id)` is equivalent to `get_all_vms(account_id=account_id)`
- [x] check difference: `get_vms_by_account` has no eager loading, `get_all_vms` has joinedload
- [x] update caller `accounts.py:72` to use `get_all_vms(account_id=account_id)`
- [x] remove `get_vms_by_account()` method
- [x] verify all tests pass
- [x] update tests that call removed method
- [x] run tests — must pass before next task

### Task 4: Standardize naming convention to `list_*`
- [x] rename `get_all_vms()` → `list_vms()` (4 callers: vms.py, comparison.py, dashboard.py, ingest.py)
- [x] rename `get_all_monitoring_hosts()` → `list_monitoring_hosts()` (1 caller: comparison.py)
- [x] rename `get_all_netbox_hosts()` → `list_netbox_hosts()` (1 caller: comparison.py)
- [x] update all callers across codebase
- [x] verify all tests pass
- [x] update tests that reference old method names
- [x] run tests — must pass before next task

### Task 5: Remove unused `status` parameter from `list_vms()`
- [ ] verify `status` parameter in `get_all_vms()` / `list_vms()` is never used by any caller
- [ ] remove `status` parameter from method signature
- [ ] remove status filter logic from method body
- [ ] verify all tests pass
- [ ] update any tests that used `status` param
- [ ] run tests — must pass before next task

### Task 6: Add DB indexes for query performance
- [ ] add index on `vms.cloud_account_id` — used in `get_vms_by_account()`, upsert filter
- [ ] add index on `vms.status` — used in `list_vms(status=?)` filter
- [ ] add index on `vms.name` — used for `order_by(VM.name)` in 5+ queries
- [ ] add index on `cloud_accounts.tenant_id` — used in 3+ queries with joins
- [ ] add index on `monitoring_hosts.cloud_account_id` — used in account filtering
- [ ] add index on `monitoring_hosts.name` — used for ordering + `get_monitoring_host_by_name()` case-insensitive search
- [ ] add index on `netbox_hosts.tenant_id` — used in tenant filtering
- [ ] add index on `sync_runs.source` — used in `get_latest_sync_run_by_source()` filter
- [ ] add composite index on `sync_runs(cloud_account_id, started_at)` — used in ordered account history
- [ ] write tests verifying indexes exist after init_db (inspect table indexes)
- [ ] run tests — must pass before next task

### Task 7: Add pagination to repository list methods
- [ ] add `limit: int | None = None` and `offset: int = 0` params to `list_vms()` (renamed `get_all_vms`)
- [ ] add `limit`/`offset` to `list_monitoring_hosts()` and `list_netbox_hosts()`
- [ ] add `count_vms()` method — returns total count with same filters (for UI pagination info)
- [ ] keep default `limit=None` for backward compat (existing callers get all results)
- [ ] write tests for pagination: limit, offset, limit+offset, count
- [ ] run tests — must pass before next task

### Task 8: Add pagination to web routes
- [ ] add `page` and `per_page` query params to `GET /vms` route (default per_page=50)
- [ ] add pagination to `GET /accounts/{id}` VM list
- [ ] add pagination to `GET /comparison` and `/comparison/table`
- [ ] create pagination template partial (page numbers, prev/next links)
- [ ] pass `total_count`, `page`, `per_page` to templates for pagination rendering
- [ ] write tests for web routes with pagination params
- [ ] run tests — must pass before next task

### Task 9: Verify acceptance criteria
- [ ] method count reduced from 32 to ~26-27
- [ ] no `list_cloud_accounts_by_tenant`, `list_cloud_accounts_with_tenants`, `get_vms_by_account` methods
- [ ] consistent naming: `list_*` for collections, `get_*` for single items
- [ ] all callers updated across cli.py, scheduler.py, web routes, sync modules
- [ ] DB indexes present on all frequently queried columns
- [ ] pagination working on `/vms`, `/accounts/{id}`, `/comparison` routes
- [ ] all tests pass: `python3 -m pytest tests/ -v`
- [ ] run linter: `ruff check src/ tests/`

### Task 10: [Final] Update documentation
- [ ] update MEMORY.md with new repository API patterns
- [ ] update this plan with any deviations

## Technical Details

### Method changes summary
```
BEFORE (32 methods)                              AFTER (~26 methods)
─────────────────────────────────────────────────────────────────────
list_cloud_accounts()                      →     list_cloud_accounts(tenant_id=None, with_relations=False)
list_cloud_accounts_with_tenants(tid?)     →     REMOVED (merged above)
list_cloud_accounts_by_tenant(tid)         →     REMOVED (merged above)
get_cloud_account(id)                      →     REMOVED (unused)
get_cloud_account_with_tenant(id)          →     get_cloud_account(id)  [always eager-loads]
get_vms_by_account(account_id)             →     REMOVED (use list_vms(account_id=...))
get_all_vms(tid?, aid?, status?)           →     list_vms(tenant_id=None, account_id=None)
get_all_monitoring_hosts()                 →     list_monitoring_hosts()
get_all_netbox_hosts()                     →     list_netbox_hosts()
```

### Callers to update per method
| Old method | Callers | New call |
|-----------|---------|----------|
| `list_cloud_accounts_by_tenant(tid)` | cli.py, dashboard.py | `list_cloud_accounts(tenant_id=tid)` |
| `list_cloud_accounts_with_tenants(tid)` | accounts.py | `list_cloud_accounts(tenant_id=tid, with_relations=True)` |
| `get_cloud_account_with_tenant(id)` | accounts.py, vms.py | `get_cloud_account(id)` |
| `get_vms_by_account(aid)` | accounts.py | `list_vms(account_id=aid)` |
| `get_all_vms(...)` | vms.py, comparison.py, dashboard.py, ingest.py | `list_vms(...)` |
| `get_all_monitoring_hosts()` | comparison.py | `list_monitoring_hosts()` |
| `get_all_netbox_hosts()` | comparison.py | `list_netbox_hosts()` |

### Files affected
| File | Change |
|------|--------|
| `db/repository.py` | Consolidate methods, rename, remove duplicates |
| `cli.py` | Update method calls |
| `scheduler.py` | Update method calls |
| `web/routes/accounts.py` | Update method calls |
| `web/routes/dashboard.py` | Update method calls |
| `web/routes/vms.py` | Update method calls |
| `web/routes/comparison.py` | Update method calls |
| `sync/ingest.py` | Update method calls |
| `comparison/engine.py` | Update method calls |
| `tests/db/test_repository.py` | Update test method references |
| Multiple web test files | Update mock/assert references |

### DB indexes to add
| Table | Column(s) | Type | Rationale |
|-------|-----------|------|-----------|
| vms | cloud_account_id | Single | FK filter, upsert |
| vms | status | Single | Status filter |
| vms | name | Single | ORDER BY in 5+ queries |
| cloud_accounts | tenant_id | Single | FK filter in 3+ queries |
| monitoring_hosts | cloud_account_id | Single | Account filter |
| monitoring_hosts | name | Single | ORDER BY + case-insensitive search |
| netbox_hosts | tenant_id | Single | Tenant filter |
| sync_runs | source | Single | Source lookup |
| sync_runs | cloud_account_id, started_at | Composite | Ordered account history |

### Pagination parameters
```python
# Repository methods
def list_vms(tenant_id=None, account_id=None, limit=None, offset=0) -> list[VM]
def count_vms(tenant_id=None, account_id=None) -> int

# Web routes
GET /vms?page=1&per_page=50&tenant_id=1&status=RUNNING
GET /accounts/1?page=2&per_page=25
GET /comparison?page=1&per_page=100
```

## Post-Completion
- Consider adding type hints for return types (e.g., `list[CloudAccount]` consistently)
- Monitor for N+1 query issues after changing eager-loading defaults
