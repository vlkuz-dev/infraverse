# Refactor batch.py: Split Large Functions

## Overview
- `process_vm_updates()` (326 lines) and `apply_batch_updates()` (260 lines) are the two largest functions in the codebase
- They mix multiple concerns: VM params, disks, interfaces, IPs, primary IP selection, batch apply steps
- Goal: break into small, independently testable functions while preserving existing behavior
- All 80+ existing tests in `test_batch.py` must continue passing after each change

## Context
- **Primary file:** `src/infraverse/sync/batch.py` (835 lines, 6 functions)
- **Test file:** `tests/sync/test_batch.py` (1,805 lines, 80+ tests)
- **Callers:** `sync/engine.py` and `scheduler.py` import only `sync_vms_optimized()` — internal functions are module-private
- **Data structure:** `NetBoxCache` dataclass holds both read cache and update queues
- **Dependencies:** `sync/vms.py` (parse_memory_mb, parse_cores, detect_platform_id), `ip/` module

## Development Approach
- **Testing approach**: Regular (code first, then tests)
- Complete each task fully before moving to the next
- Make small, focused changes — extract one logical block at a time
- **CRITICAL: every task MUST include new/updated tests** for code changes in that task
- **CRITICAL: all tests must pass before starting next task**
- **CRITICAL: update this plan file when scope changes during implementation**
- Run `python3 -m pytest tests/sync/test_batch.py -v` after each change

## Progress Tracking
- Mark completed items with `[x]` immediately when done
- Add newly discovered tasks with ➕ prefix
- Document issues/blockers with ⚠️ prefix

## Implementation Steps

### Task 1: Extract VM parameter update logic from `process_vm_updates()`
- [x] create `_process_vm_parameters(vm, yc_vm, cache, id_mapping, netbox, provider_profile) -> bool` function
- [x] move lines 113-186 (memory, CPU, status, cluster, site, platform, comments checks) into new function
- [x] call `_process_vm_parameters()` from `process_vm_updates()` in place of extracted code
- [x] verify all existing tests pass without modification
- [x] write tests for `_process_vm_parameters()` directly (memory change, CPU change, status change, no changes case)
- [x] run tests — must pass before next task

### Task 2: Extract disk synchronization logic from `process_vm_updates()`
- [x] create `_process_vm_disks(vm_id, yc_vm, cache) -> bool` function
- [x] move lines 188-226 (disk size parsing, create/update/delete queueing) into new function
- [x] call `_process_vm_disks()` from `process_vm_updates()` in place of extracted code
- [x] verify all existing tests pass without modification
- [x] write tests for `_process_vm_disks()` directly (new disk, updated size, orphaned disk removal, no disks)
- [x] run tests — must pass before next task

### Task 3: Extract IP address handling from `process_vm_updates()`
- [x] create `_process_vm_ips(vm, yc_vm, cache) -> bool` function covering lines 228-332 (interface loop + IP processing)
- [x] create `_select_primary_ip(vm, cache, private_candidate, public_candidate) -> None` covering lines 334-420 (primary IP selection algorithm)
- [x] call both from `process_vm_updates()` in place of extracted code
- [x] `process_vm_updates()` should now be ~30-40 lines: param setup, call 3 helpers, return result
- [x] verify all existing tests pass without modification
- [x] write tests for `_select_primary_ip()` directly (prefer private, keep valid current, switch public→private, pending case)
- [x] run tests — must pass before next task

### Task 4: Extract batch apply steps from `apply_batch_updates()`
- [x] create `_step_unset_primary_ips(cache, netbox) -> int` (lines 468-481)
- [x] create `_step_delete_disks(cache) -> int` (lines 483-492)
- [x] create `_step_create_interfaces(cache, netbox) -> dict` (lines 494-508) — returns created_interfaces map
- [x] create `_step_update_ips(cache, netbox, created_interfaces) -> int` (lines 510-534) — includes pending reassignment resolution
- [x] create `_step_create_ips(cache, netbox, created_interfaces) -> tuple[int, dict]` (lines 536-560) — returns count + created_ips map
- [x] create `_step_manage_disks(cache, netbox) -> tuple[int, int]` (lines 593-616) — create + update disks
- [x] create `_step_update_vms(cache, netbox) -> int` (lines 618-630)
- [x] create `_step_set_primary_ips(cache, netbox, created_ips) -> int` (lines 562-591 + 632-686) — resolve pending + set primary
- [x] refactor `apply_batch_updates()` to call steps in sequence (~40 lines)
- [x] verify all existing tests pass without modification
- [x] write tests for 2-3 individual step functions (e.g., `_step_create_interfaces`, `_step_set_primary_ips`)
- [x] run tests — must pass before next task

### Task 5: Verify acceptance criteria
- [ ] `process_vm_updates()` is ≤50 lines (was 326)
- [ ] `apply_batch_updates()` is ≤50 lines (was 260)
- [ ] no function in batch.py exceeds 80 lines
- [ ] all 80+ existing tests pass unchanged
- [ ] new tests cover extracted functions
- [ ] run full test suite: `python3 -m pytest tests/ -v`
- [ ] run linter: `ruff check src/infraverse/sync/batch.py`

### Task 6: [Final] Update documentation
- [ ] update MEMORY.md if new patterns discovered
- [ ] update this plan with any deviations from original scope

## Technical Details

### Current function structure
```
batch.py (835 lines):
├── _normalize_comments()          # 5 lines — OK
├── NetBoxCache                    # 25 lines — OK
├── load_netbox_data()             # 52 lines — OK
├── process_vm_updates()           # 326 lines — SPLIT into 4 functions
│   ├── _process_vm_parameters()   # ~75 lines (memory, CPU, status, cluster, site, platform, comments)
│   ├── _process_vm_disks()        # ~40 lines (parse, create, update, delete)
│   ├── _process_vm_ips()          # ~105 lines (interface loop + IP processing)
│   └── _select_primary_ip()       # ~87 lines (prefer private, fallback logic)
├── apply_batch_updates()          # 260 lines — SPLIT into 8 step functions
│   ├── _step_unset_primary_ips()
│   ├── _step_delete_disks()
│   ├── _step_create_interfaces()
│   ├── _step_update_ips()
│   ├── _step_create_ips()
│   ├── _step_manage_disks()
│   ├── _step_update_vms()
│   └── _step_set_primary_ips()
└── sync_vms_optimized()           # 143 lines — unchanged
```

### Key constraint: execution order in `apply_batch_updates()`
Steps must execute in this exact order due to data dependencies:
1. Unset primary IPs (before deleting anything)
2. Delete disks
3. Create interfaces (needed for IP assignment)
4. Update/reassign IPs (needs created interface IDs)
5. Create new IPs (needs created interface IDs)
6. Create/update disks
7. Update VM parameters
8. Set primary IPs (needs created IP IDs from step 5)

## Post-Completion
- Consider whether `sync_vms_optimized()` (143 lines) also needs splitting in a future plan
- Monitor test execution time — should remain under 10 seconds
