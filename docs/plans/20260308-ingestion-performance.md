# Ingestion Performance Optimization

## Overview
- YC provider makes N+1 sequential API calls for disk/image data: ~500 HTTP calls for 100 VMs with 3 disks each
- Monitoring checks are sequential per-VM with up to 4 Zabbix API calls per VM (name + IP fallbacks)
- Providers are ingested sequentially — no parallelism between accounts
- No retry/backoff policy anywhere in the stack
- Goal: bounded concurrency for API-heavy paths, caching for repeated lookups, retry with backoff

## Context
- **YC disk/image N+1:** `src/infraverse/providers/yandex.py:347-377` — per-VM `fetch_disk()` + `fetch_image()` calls
- **Sequential monitoring:** `src/infraverse/sync/monitoring.py:59-86` — `for vm in vms: check_vm_monitoring(vm)`
- **Zabbix per-VM:** `src/infraverse/providers/zabbix.py:205-274` — name search + per-IP fallback
- **Sequential providers:** `src/infraverse/sync/ingest.py:321-333` — loop over providers
- **No retry anywhere:** all providers catch exceptions and continue silently

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

### Task 1: Cache disk/image lookups in YC provider
- [x] in `YandexCloudClient.fetch_all_data()`, collect all disk IDs across all VMs before per-VM processing
- [x] batch-fetch all disks upfront (single list call with filter or paginated fetch), store in `dict[disk_id, disk]`
- [x] collect all image IDs from boot disks, batch-fetch images into `dict[image_id, image]`
- [x] replace per-VM `fetch_disk()`/`fetch_image()` calls with cache lookups
- [x] keep fallback to individual fetch if ID not found in cache (edge case: disk created mid-sync)
- [x] write tests for cache hit path (no individual API calls)
- [x] write tests for cache miss fallback
- [x] run tests — must pass before next task

### Task 2: Use Zabbix bulk fetch for monitoring checks
- [x] in `check_all_vms_monitoring()`, call `zabbix_client.fetch_hosts()` once to get all hosts
- [x] build lookup dicts: `hosts_by_name: dict[str, ZabbixHost]` and `hosts_by_ip: dict[str, ZabbixHost]`
- [x] replace per-VM `search_host_by_name()` and `search_host_by_ip()` with dict lookups
- [x] keep the existing per-VM fallback path for cases where bulk fetch is unavailable
- [x] write tests for bulk fetch path (single API call + local lookup)
- [x] write tests verifying name-first-then-IP-fallback behavior preserved
- [x] run tests — must pass before next task

### Task 3: Add retry with backoff for provider API calls
- [x] create `src/infraverse/providers/retry.py` with `retry_with_backoff()` decorator/helper
- [x] implement exponential backoff: base=1s, max=30s, max_retries=3, jitter
- [x] retry on: connection errors, 429 (rate limit), 500-503 (server errors)
- [x] do NOT retry on: 400, 401, 403, 404 (client errors)
- [x] apply to `YandexCloudClient` API methods (`_get_json()` helper with retry)
- [x] apply to `ZabbixClient._jsonrpc_request()`
- [x] apply to `VCloudDirectorClient._request()` helper with retry
- [x] write tests for retry behavior: retries on 500, gives up after max_retries, no retry on 400
- [x] write tests for backoff timing (mock sleep)
- [x] run tests — must pass before next task

### Task 4: Parallelize provider ingestion (optional, lower priority)
- [x] evaluate if `ThreadPoolExecutor` is safe with current session/DB usage
- [x] ~~if safe: run independent provider accounts in parallel in `ingest_all()` using bounded pool (max_workers=4)~~ N/A — not safe
- [x] if not safe: document why and skip (SQLite single-writer limitation)
- [x] ~~write tests for parallel execution if implemented~~ N/A — not implemented
- [x] run tests — must pass before next task

### Task 5: Verify acceptance criteria
- [x] verify YC sync with 10+ VMs makes significantly fewer API calls (cache hit rate)
- [x] verify monitoring check does single bulk fetch instead of per-VM calls
- [x] verify retry works on transient failures (mock 500 → 200 sequence)
- [x] run full test suite
- [x] run linter: `ruff check src/ tests/`

### Task 6: [Final] Update documentation
- [x] update MEMORY.md with new patterns (retry, caching)
- [x] update this plan with any deviations

## Technical Details

### Current vs target API call counts (100 VMs, 3 disks each)

| Phase | Current | Target |
|-------|---------|--------|
| YC disk fetch | 300 individual calls | 1-3 paginated list calls |
| YC image fetch | ~100 individual calls | 1-2 paginated list calls |
| Zabbix monitoring | 100-400 calls (name + IP fallbacks) | 1-3 paginated bulk fetch |
| **Total** | **500-800 calls** | **~10 calls** |

### Retry policy
```
attempt 1: immediate
attempt 2: 1s + jitter
attempt 3: 2s + jitter
attempt 4: 4s + jitter (final, then raise)
```

### Files affected
| File | Change |
|------|--------|
| `providers/yandex.py` | Cache disk/image lookups in fetch_all_data() |
| `providers/retry.py` | **NEW** — retry_with_backoff() decorator |
| `sync/monitoring.py` | Use bulk Zabbix fetch + local dict lookup |
| `providers/zabbix.py` | Apply retry decorator to _jsonrpc_request() |
| `providers/vcloud.py` | Apply retry decorator to _authenticated_request() |
| `sync/ingest.py` | Optional: parallel provider ingestion |

## Post-Completion
- Monitor actual API call reduction in production logs
- Consider adding metrics/counters for cache hit rates
- If SQLite write contention becomes an issue with parallelism, evaluate PostgreSQL
