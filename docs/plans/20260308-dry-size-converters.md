# DRY: Extract Size Conversion Utilities

## Overview
- Memory, CPU, and disk size conversion logic is duplicated 5+ times across `vms.py`, `batch.py`, `yandex.py`
- The canonical pattern `round(int(size) / (1024 ** 3) * 1000)` appears 4 times inline for disk conversion
- `parse_memory_mb()` and `parse_cores()` exist in `vms.py` but disk has no shared function
- Magic numbers (1024**3, 1000) scattered across code and tests
- Goal: single source of truth for all size conversions

## Context
- **Existing parsers:** `src/infraverse/sync/vms.py` lines 16-77 (`parse_memory_mb`, `parse_cores`)
- **Disk duplicates:** `vms.py` (3×: lines 402, 434, 961), `batch.py` (1×: line 200)
- **Memory inline:** `providers/yandex.py` line 467 uses `int(memory_bytes) // (1024 * 1024)` — different formula
- **vCloud:** `providers/vcloud.py` line 212 uses `memory_mb * 1024 * 1024` (inverse conversion)
- **Test magic numbers:** `test_vms.py`, `test_batch.py`, `test_yandex.py` use raw byte constants

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

### Task 1: Create size converter module with disk parser
- [x] create `src/infraverse/sync/size_converters.py` with constants:
  - `BYTES_PER_GIB = 1024 ** 3`
  - `NETBOX_MB_PER_GIB = 1000` (NetBox uses decimal MB display for GiB values)
- [x] add `parse_disk_size_mb(size_bytes: int | float | str) -> int` function
  - formula: `round(int(size_bytes) / BYTES_PER_GIB * NETBOX_MB_PER_GIB)`
  - handle string/int/float input types (same as `parse_memory_mb`)
- [x] write tests for `parse_disk_size_mb()` — various inputs, edge cases (0, negative, string, float)
- [x] run tests — must pass before next task

### Task 2: Move `parse_memory_mb` and `parse_cores` to size_converters
- [x] move `parse_memory_mb()` from `vms.py:16-55` to `size_converters.py`
- [x] move `parse_cores()` from `vms.py:58-77` to `size_converters.py`
- [x] refactor `parse_memory_mb()` to use `BYTES_PER_GIB` and `NETBOX_MB_PER_GIB` constants
- [x] add re-exports in `vms.py`: `from infraverse.sync.size_converters import parse_memory_mb, parse_cores`
- [x] update `batch.py` import: change `from infraverse.sync.vms import parse_memory_mb, parse_cores` to `from infraverse.sync.size_converters import ...`
- [x] verify all existing tests pass without modification (re-exports preserve API)
- [x] run tests — must pass before next task

### Task 3: Replace inline disk conversions with `parse_disk_size_mb()`
- [x] replace `vms.py` line ~402: `size_mb = round(int(size) / (1024 ** 3) * 1000)` → `size_mb = parse_disk_size_mb(size)`
- [x] replace `vms.py` line ~434: inline dict `"size": round(...)` → `"size": parse_disk_size_mb(size)`
- [x] replace `vms.py` line ~961: inline dict `"size": round(...)` → `"size": parse_disk_size_mb(size)`
- [x] replace `batch.py` line ~200: `size_mb = round(int(raw_size) / (1024 ** 3) * 1000)` → `size_mb = parse_disk_size_mb(raw_size)`
- [x] add import `from infraverse.sync.size_converters import parse_disk_size_mb` in both files
- [x] verify all existing tests pass
- [x] run tests — must pass before next task

### Task 4: Align yandex.py memory conversion (review only)
- [x] review `providers/yandex.py` line 467: `memory_mb = int(memory_bytes) // (1024 * 1024)` — this is a raw byte→MB conversion (not NetBox scaling), used differently from `parse_memory_mb`
- [x] if conversion serves different purpose (raw MB for vCloud pipeline compatibility), document with comment and leave as-is
- [x] if it should use NetBox scaling, replace with `parse_memory_mb(memory_bytes)`
- [x] review `providers/vcloud.py` line 212: inverse conversion `memory_mb * 1024 * 1024` — document purpose
- [x] run tests — must pass before next task

### Task 5: Verify acceptance criteria
- [ ] no inline `1024 ** 3` or `1024**3` in `vms.py` or `batch.py`
- [ ] `parse_memory_mb`, `parse_cores`, `parse_disk_size_mb` all live in `size_converters.py`
- [ ] re-exports in `vms.py` preserve backward compatibility
- [ ] all tests pass: `python3 -m pytest tests/ -v`
- [ ] run linter: `ruff check src/ tests/`

### Task 6: [Final] Update documentation
- [ ] update MEMORY.md with new module path
- [ ] update this plan with any deviations

## Technical Details

### Conversion formulas
```python
# NetBox memory: bytes → GiB → "decimal MB" (NetBox displays GiB as *1000 MB)
parse_memory_mb(bytes) = int(bytes) / (1024**3) * 1000  # 4 GiB → 4000 MB

# NetBox disk: bytes → GiB → "decimal MB" (same scaling)
parse_disk_size_mb(bytes) = round(int(bytes) / (1024**3) * 1000)  # 10 GiB → 10000 MB

# Raw conversion (yandex.py): bytes → actual MiB (for vCloud pipeline compatibility)
raw_mb = int(bytes) // (1024 * 1024)  # 4 GiB → 4096 MiB — DIFFERENT purpose
```

### Files affected
| File | Change |
|------|--------|
| `sync/size_converters.py` | **NEW** — constants + 3 functions |
| `sync/vms.py` | Remove function defs, add re-exports, replace 3 inline conversions |
| `sync/batch.py` | Update import, replace 1 inline conversion |
| `providers/yandex.py` | Review + document (likely no change) |
| `providers/vcloud.py` | Review + document (likely no change) |
| `tests/sync/test_size_converters.py` | **NEW** — tests for parse_disk_size_mb |

## Post-Completion
- Consider adding test helper constants (`TEST_4_GIB_BYTES = 4294967296`) in a future cleanup
- Monitor if other conversion patterns emerge in new providers
