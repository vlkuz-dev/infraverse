# Split Large Modules by Bounded Context

## Overview
- `providers/netbox.py` (1331 lines) — monolithic class with 18 methods covering tags, sites, clusters, prefixes, VMs, interfaces
- `sync/vms.py` (966 lines) — 8 functions covering platform detection, VM prep, params, disks, networking, orchestration
- `sync/batch.py` (936 lines) — recently refactored, well-structured — skip further splitting
- Goal: split netbox.py and vms.py into focused modules by bounded context

## Context
- **netbox.py:** `src/infraverse/providers/netbox.py` — single `NetBoxClient` class, all methods share `self.nb` and `self.dry_run`
- **vms.py:** `src/infraverse/sync/vms.py` — standalone functions, all depend on `NetBoxClient` + shared IP utilities
- **batch.py:** Already split into phases (queue/apply/orchestrate) — no further action needed
- **Tests:** `tests/providers/test_netbox.py`, `tests/sync/test_vms.py`

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

### Task 1: Split netbox.py — extract tag management
- [x] create `src/infraverse/providers/netbox_tags.py` with tag-related methods:
  - `ensure_sync_tag()` (lines 47-126)
  - `_add_tag_to_object()` (lines 127-162)
- [x] keep methods on NetBoxClient — use mixin or delegate pattern to avoid breaking callers
- [x] update imports in all callers (if class interface changes)
- [x] move corresponding tests to `tests/providers/test_netbox_tags.py`
- [x] run tests — must pass before next task

### Task 2: Split netbox.py — extract infrastructure (sites, clusters, platforms)
- [x] create `src/infraverse/providers/netbox_infrastructure.py` with:
  - `ensure_site()` (lines 209-319)
  - `ensure_cluster_type()` (lines 320-446)
  - `ensure_cluster()` (lines 447-610)
  - `ensure_platform()` (lines 611-654)
- [x] extract `_safe_update_object()` (lines 163-208) to shared base/utils — used by multiple modules
- [x] update imports in callers
- [x] move corresponding tests to `tests/providers/test_netbox_infrastructure.py`
- [x] run tests — must pass before next task

### Task 3: Split netbox.py — extract prefix management
- [ ] create `src/infraverse/providers/netbox_prefixes.py` with:
  - `ensure_prefix()` (lines 655-812)
  - `update_prefix()` (lines 813-928)
- [ ] update imports in callers
- [ ] move corresponding tests to `tests/providers/test_netbox_prefixes.py`
- [ ] run tests — must pass before next task

### Task 4: Split netbox.py — extract VM and interface CRUD
- [ ] create `src/infraverse/providers/netbox_vms.py` with:
  - `fetch_vms()`, `fetch_all_vms()` (lines 929-995)
  - `create_vm()`, `update_vm()` (lines 996-1043, 1188-1229)
  - `get_vm_by_name()`, `get_vm_by_custom_field()` (lines 1296-1331)
- [ ] create `src/infraverse/providers/netbox_interfaces.py` with:
  - `create_disk()` (lines 1044-1070)
  - `create_interface()` (lines 1071-1103)
  - `create_ip()` (lines 1104-1187)
  - `set_vm_primary_ip()` (lines 1230-1295)
- [ ] keep `netbox.py` as facade: import and re-export `NetBoxClient` with all methods
- [ ] update imports in callers if needed
- [ ] split tests accordingly
- [ ] run tests — must pass before next task

### Task 5: Split vms.py — extract by concern
- [ ] create `src/infraverse/sync/vms_platform.py`:
  - `detect_platform_slug()` (lines 17-70)
  - `detect_platform_id()` (lines 72-82)
- [ ] create `src/infraverse/sync/vms_disks.py`:
  - `sync_vm_disks()` (lines 278-415)
- [ ] create `src/infraverse/sync/vms_networking.py`:
  - `update_vm_primary_ip()` (lines 417-543)
  - `sync_vm_interfaces()` (lines 545-779)
- [ ] keep in `vms.py` (as orchestrator):
  - `prepare_vm_data()` (lines 84-177)
  - `update_vm_parameters()` (lines 179-276)
  - `sync_vms()` (lines 781-967) — imports from new modules
- [ ] update all imports across codebase
- [ ] split tests into corresponding test files
- [ ] run tests — must pass before next task

### Task 6: Verify acceptance criteria
- [ ] no single file exceeds ~500 lines
- [ ] all existing tests pass with new file structure
- [ ] imports are clean — no circular dependencies
- [ ] `NetBoxClient` public API unchanged (facade re-exports)
- [ ] run full test suite: `python3 -m pytest tests/ -v`
- [ ] run linter: `ruff check src/ tests/`

### Task 7: [Final] Update documentation
- [ ] update MEMORY.md with new module paths
- [ ] update this plan with any deviations

## Technical Details

### netbox.py split target
```
BEFORE: providers/netbox.py (1331 lines, 18 methods)

AFTER:
  providers/netbox.py           (~50 lines)   — facade: NetBoxClient with __init__, imports/delegates
  providers/netbox_tags.py      (~120 lines)  — ensure_sync_tag, _add_tag_to_object
  providers/netbox_infra.py     (~450 lines)  — ensure_site/cluster_type/cluster/platform, _safe_update_object
  providers/netbox_prefixes.py  (~280 lines)  — ensure_prefix, update_prefix
  providers/netbox_vms.py       (~220 lines)  — VM CRUD: create/update/fetch/get
  providers/netbox_interfaces.py(~220 lines)  — create_disk/interface/ip, set_primary_ip
```

### vms.py split target
```
BEFORE: sync/vms.py (966 lines, 8 functions)

AFTER:
  sync/vms.py               (~460 lines)  — prepare_vm_data, update_vm_parameters, sync_vms orchestrator
  sync/vms_platform.py       (~70 lines)  — detect_platform_slug, detect_platform_id
  sync/vms_disks.py          (~140 lines) — sync_vm_disks
  sync/vms_networking.py     (~300 lines) — sync_vm_interfaces, update_vm_primary_ip
```

### Design decision: mixin vs delegation vs facade
- **Facade (chosen for netbox.py):** `NetBoxClient` stays as the public class, imports methods from submodules. Callers don't change.
- **Direct functions (chosen for vms.py):** Functions are already standalone, just move to new files. Update imports.

### Shared dependencies
- `_safe_update_object()` used by infra + prefixes → put in base/infra module
- Tag cache (`self._tag_slugs_cache`) used by tags + VM creation → keep on NetBoxClient instance
- `self.nb` (pynetbox API) used everywhere → stays on NetBoxClient, passed to submodule functions

## Post-Completion
- Consider splitting test files to match source structure if they become large
- batch.py is fine at 936 lines — revisit only if it grows significantly
