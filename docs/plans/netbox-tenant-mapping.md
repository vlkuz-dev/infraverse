# NetBox Tenant Mapping

## Overview
- Map Infraverse tenants to NetBox VMs during forward sync (DB → NetBox)
- Currently, VMs are created/updated in NetBox without tenant assignment, despite tenant data being available through the VM → CloudAccount → Tenant chain
- The reverse direction (NetBox → DB) already extracts tenant — this closes the gap in the forward direction
- Uses config key (TenantConfig.name) as both NetBox tenant name and slug
- TenantConfig.description → NetBox tenant description (if set)
- No new config fields needed — existing tenant name/description are sufficient
- Auto-creates tenant in NetBox if it doesn't exist (following ensure_* pattern)

## Context (from discovery)
- Files involved:
  - `src/infraverse/providers/netbox_infrastructure.py` — add `ensure_tenant()` method
  - `src/infraverse/providers/netbox.py` — add `_tenant_cache` init
  - `src/infraverse/sync/providers.py` — thread tenant_name through `build_providers_from_accounts()`
  - `src/infraverse/sync/engine.py` — accept and pass tenant_name in SyncEngine
  - `src/infraverse/sync/vms.py` — add tenant to `prepare_vm_data()`, `update_vm_parameters()`, `sync_vms()`
  - `src/infraverse/sync/batch.py` — add tenant to `_process_vm_parameters()`, `sync_vms_optimized()`
  - `src/infraverse/cli.py` — adapt to new 3-tuple provider format
- Patterns: `ensure_*` methods use per-slug caching, dry_run support, sync tag assignment, `_safe_update_object()` for updates
- Dependencies: pynetbox `nb.tenancy.tenants` API, existing ensure_* method pattern

## Design Decisions

### Name vs Slug
- **NetBox tenant name** = TenantConfig.name (config YAML key, e.g. "acme-corp")
- **NetBox tenant slug** = TenantConfig.name (same value — config keys are already slug-safe)
- **NetBox tenant description** = TenantConfig.description (e.g. "ACME Corporation")
- No extra config fields needed

### Tenant info threading
- `build_providers_from_accounts()` returns `List[Tuple[CloudClient, ProviderProfile, str | None]]` (3-tuple with tenant_name)
- `build_provider()` stays unchanged (returns 2-tuple); tenant_name is added in `build_providers_from_accounts()`
- `SyncEngine.__init__` accepts the new 3-tuple format
- tenant_name flows: SyncEngine → _sync_provider → sync_vms_optimized / sync_vms → prepare_vm_data / _process_vm_parameters

### Scope
- Both sync paths: batch (`sync_vms_optimized`) and sequential (`sync_vms`)
- Config: no changes needed (TenantConfig already has name + description)
- DB model: no changes needed (Tenant model already has name + description)

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
- **CRITICAL: all tests must pass before starting next task** — no exceptions
- **CRITICAL: update this plan file when scope changes during implementation**
- Run tests after each change
- Maintain backward compatibility

## Testing Strategy
- **Unit tests**: required for every task (see Development Approach above)
- Mock pynetbox API calls for ensure_tenant() tests
- Test tenant threading through all sync path functions
- Test backward compat: all existing tests pass without tenant_name (default None)

## Progress Tracking
- Mark completed items with `[x]` immediately when done
- Add newly discovered tasks with ➕ prefix
- Document issues/blockers with ⚠️ prefix
- Update plan if implementation deviates from original scope
- Keep plan in sync with actual work done

## What Goes Where
- **Implementation Steps** (`[ ]` checkboxes): tasks achievable within this codebase — code changes, tests, documentation updates
- **Post-Completion** (no checkboxes): items requiring external action — manual testing, deployment

## Implementation Steps

### Task 1: Add `ensure_tenant()` to NetBox infrastructure mixin
- [x] Add `_tenant_cache: Dict[str, int] = {}` initialization in `NetBoxClient.__init__()` (`netbox.py`)
- [x] Implement `ensure_tenant(name, slug=None, description=None) -> int` in `netbox_infrastructure.py` following ensure_cluster_type() pattern:
  - Slug defaults to `name` (config keys are already slug-safe)
  - Check `_tenant_cache` by slug
  - Try `nb.tenancy.tenants.get(name=name)`, then by slug
  - If found: update description if changed via `_safe_update_object()`, add sync tag, cache and return ID
  - If dry_run: return mock ID, cache
  - If not found: create via `nb.tenancy.tenants.create(name, slug, description, tags)`, cache and return ID
  - Handle duplicate slug error (retry fetch, like other ensure_* methods)
- [x] Write tests for ensure_tenant() — success cases (found by name, found by slug, created new, dry_run, cached)
- [x] Write tests for ensure_tenant() — error/edge cases (duplicate slug retry, description update)
- [x] Run tests — must pass before next task

### Task 2: Thread tenant_name through providers and SyncEngine
- [ ] Update `build_providers_from_accounts()` in `sync/providers.py` to return `List[Tuple[CloudClient, ProviderProfile, str | None]]` — extract `account.tenant.name` (need eager-load tenant; use `list_cloud_accounts(with_relations=True)`)
- [ ] Update `SyncEngine.__init__()` in `sync/engine.py` — change providers type to accept 3-tuples
- [ ] Update `SyncEngine.run()` to unpack `(client, profile, tenant_name)` from `self._providers`
- [ ] Update `SyncEngine._sync_provider()` to accept and pass `tenant_name` to both `sync_vms_optimized()` and `sync_vms()`
- [ ] Update `cli.py:cmd_sync()` — use `list_cloud_accounts(with_relations=True)` so tenant is loaded
- [ ] Write tests for build_providers_from_accounts() returning 3-tuple with tenant_name
- [ ] Write tests for SyncEngine accepting and threading tenant_name
- [ ] Run tests — must pass before next task

### Task 3: Add tenant to `prepare_vm_data()` and `sync_vms()` (sequential path)
- [ ] Add `tenant_name: str | None = None` parameter to `prepare_vm_data()` in `sync/vms.py`
- [ ] If tenant_name is provided, call `netbox.ensure_tenant(name=tenant_name, description=...)` and add `"tenant": tenant_id` to returned vm_data dict
- [ ] Add `tenant_name` parameter to `update_vm_parameters()` — pass to `prepare_vm_data()` and check tenant field in update logic
- [ ] Add `tenant_name` parameter to `sync_vms()` — pass to `prepare_vm_data()` and `update_vm_parameters()` calls
- [ ] Write tests for prepare_vm_data() with tenant_name (set and None)
- [ ] Write tests for update_vm_parameters() tenant comparison (changed, unchanged, None)
- [ ] Write tests for sync_vms() passing tenant_name through
- [ ] Run tests — must pass before next task

### Task 4: Add tenant to `_process_vm_parameters()` and `sync_vms_optimized()` (batch path)
- [ ] Add `tenant_name: str | None = None` parameter to `_process_vm_parameters()` in `sync/batch.py`
- [ ] If tenant_name is provided, call `netbox.ensure_tenant(tenant_name)` to get tenant_id
- [ ] Compare current VM tenant with resolved tenant_id, queue update in cache if different
- [ ] Add `tenant_name: str | None = None` to `sync_vms_optimized()` signature, pass to `prepare_vm_data()` and through `process_vm_updates()` → `_process_vm_parameters()`
- [ ] Write tests for _process_vm_parameters() with tenant update (changed, unchanged, None)
- [ ] Write tests for sync_vms_optimized() passing tenant_name through
- [ ] Run tests — must pass before next task

### Task 5: Verify acceptance criteria
- [ ] Verify: VM creation in NetBox includes tenant field (both paths)
- [ ] Verify: VM update in NetBox checks and updates tenant field (both paths)
- [ ] Verify: ensure_tenant() auto-creates tenant in NetBox when missing
- [ ] Verify: tenant_name=None is handled gracefully (backward compat, no tenant set)
- [ ] Verify: dry_run mode works with tenant mapping
- [ ] Verify: description from TenantConfig flows to NetBox tenant
- [ ] Run full test suite (`python3 -m pytest tests/ -v`)
- [ ] Run linter (`ruff check src/ tests/`) — all issues must be fixed

### Task 6: [Final] Update documentation
- [ ] Update README.md if needed (mention tenant mapping in sync description)
- [ ] Update project knowledge docs if new patterns discovered

*Note: ralphex automatically moves completed plans to `docs/plans/completed/`*

## Technical Details

### Config → NetBox Mapping
```
Config YAML:
  tenants:
    acme-corp:                        # TenantConfig.name
      description: "ACME Corporation" # TenantConfig.description

NetBox tenant:
  name: "acme-corp"                   # = TenantConfig.name
  slug: "acme-corp"                   # = TenantConfig.name (same)
  description: "ACME Corporation"     # = TenantConfig.description
```

### Data Flow (after implementation)
```
cli.py:cmd_sync()
  ├── accounts = repo.list_cloud_accounts(with_relations=True)
  ├── providers = build_providers_from_accounts(accounts)
  │     └── returns [(client, profile, "acme-corp"), (client, profile, "beta-inc")]
  └── SyncEngine(netbox, providers)
        └── _sync_provider(client, profile, tenant_name="acme-corp")
              ├── sync_vms_optimized(..., tenant_name="acme-corp")
              │     ├── prepare_vm_data(..., tenant_name="acme-corp")
              │     │     └── netbox.ensure_tenant("acme-corp", description="ACME Corporation")
              │     │     └── vm_data["tenant"] = tenant_id
              │     └── _process_vm_parameters(..., tenant_name="acme-corp")
              │           └── if vm.tenant != tenant_id: queue update
              └── sync_vms(..., tenant_name="acme-corp")  # --no-batch path
                    ├── prepare_vm_data(..., tenant_name="acme-corp")
                    └── update_vm_parameters(..., tenant_name="acme-corp")
```

### ensure_tenant() signature
```python
def ensure_tenant(self, name: str, slug: str | None = None, description: str | None = None) -> int:
```
- `name` = config key (e.g. "acme-corp")
- `slug` defaults to `name` if not provided
- `description` = TenantConfig.description (e.g. "ACME Corporation")
- Caches by slug in `self._tenant_cache`
- Follows same pattern as `ensure_cluster_type()`

### NetBox API
- Tenants endpoint: `nb.tenancy.tenants`
- VM tenant field: integer ID (tenant object reference)
- Tenant create fields: `name`, `slug`, `description`, `tags`

### Description threading
- `prepare_vm_data()` only has `tenant_name` — no description available at this level
- Option A: Pass description separately (adds another parameter everywhere)
- Option B: Let `ensure_tenant()` create without description, update on next sync when called with description from higher level
- **Chosen: pass tenant_description alongside tenant_name** or resolve from config where available. Implementation detail to be decided during Task 2-3.

## Post-Completion

**Manual verification:**
- Run sync against real NetBox instance and verify tenants appear on VMs
- Check tenant is created in NetBox if it didn't exist before
- Verify VMs from different tenants get different tenant assignments
- Verify tenant description matches config description
