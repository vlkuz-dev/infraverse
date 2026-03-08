# Per-account NetBox Sync

## Overview
- SyncEngine currently uses a single global YC token from `Config` class. When YAML config is used, CLI passes `yc_token=""` which causes `Bearer ''` errors
- Switch SyncEngine to build providers from per-account credentials stored in CloudAccount.config (same pattern as DataIngestor and Scheduler)
- Each CloudAccount gets its own full sync cycle: fetch data → sync infrastructure → sync VMs → cleanup
- Drop legacy env-var Config mode from cmd_sync — require YAML config

## Context (from discovery)
- **Files involved**: `sync/engine.py`, `cli.py`, `config.py`
- **Existing pattern**: `_build_provider_from_account()` in cli.py (line 97-116), Scheduler._build_providers()
- **Provider profiles**: `YC_PROFILE` (key="yandex_cloud"), `VCLOUD_PROFILE` (key="vcloud") map to CloudAccount.provider_type
- **DB model**: CloudAccount has `.config` JSON dict with provider-specific credentials, `.provider_type` string
- **Cleanup scoping**: Already implemented — `_extract_cloud_names()` from yc_data folders

## Development Approach
- **Testing approach**: Regular (code first, then tests)
- Complete each task fully before moving to the next
- Make small, focused changes
- **CRITICAL: every task MUST include new/updated tests**
- **CRITICAL: all tests must pass before starting next task**
- **CRITICAL: update this plan file when scope changes during implementation**
- Run tests after each change
- Maintain backward compatibility for `infraverse serve` (which still uses Config)

## Testing Strategy
- **Unit tests**: Mock CloudAccount objects with `.config` dicts, verify SyncEngine builds correct providers
- **Integration**: Existing sync tests should still pass (they use mock NetBox clients)

## Progress Tracking
- Mark completed items with `[x]` immediately when done
- Add newly discovered tasks with ➕ prefix
- Document issues/blockers with ⚠️ prefix

## Implementation Steps

### Task 1: Refactor SyncEngine to accept pre-built providers

**Files:**
- Modify: `src/infraverse/sync/engine.py`
- Create: `tests/sync/test_engine.py`

- [ ] Change SyncEngine.__init__ to accept `netbox: NetBoxClient` and `providers: list[tuple[client, ProviderProfile]]` instead of `Config`
- [ ] Remove provider construction logic from __init__ (lines 29-50 that create YC/vCD clients)
- [ ] Keep `self.nb` and `self._providers` as instance attributes, keep `run()` and `_sync_provider()` unchanged
- [ ] Store `dry_run` flag directly (passed from caller)
- [ ] Write tests: SyncEngine with mock providers runs sync cycle correctly
- [ ] Write tests: SyncEngine with empty providers list returns empty stats
- [ ] Run tests — must pass before next task

### Task 2: Add provider builder utility

**Files:**
- Create: `src/infraverse/sync/providers.py`
- Create: `tests/sync/test_providers.py`

- [ ] Create `build_provider(account: CloudAccount) -> tuple[client, ProviderProfile]` function
- [ ] Reuse existing `_build_provider_from_account()` logic from cli.py for client creation
- [ ] Map `account.provider_type` to ProviderProfile (`yandex_cloud` → YC_PROFILE, `vcloud` → VCLOUD_PROFILE)
- [ ] Create `build_providers_from_db(session) -> list[tuple[client, ProviderProfile]]` that queries active CloudAccounts
- [ ] Write tests: build_provider creates YC client from sa_key_file credentials
- [ ] Write tests: build_provider creates vCloud client from url/username/password credentials
- [ ] Write tests: build_provider raises on unknown provider_type
- [ ] Write tests: build_providers_from_db skips inactive accounts
- [ ] Run tests — must pass before next task

### Task 3: Update CLI cmd_sync to use per-account sync

**Files:**
- Modify: `src/infraverse/cli.py`

- [ ] In cmd_sync YAML path (lines 289-306): replace `Config(yc_token="")` + `SyncEngine(config)` with:
  - Build NetBoxClient directly from `infraverse_config.netbox`
  - Build providers via `build_providers_from_db(session)`
  - Create `SyncEngine(netbox, providers, dry_run=args.dry_run)`
- [ ] Remove legacy env-var Config path from cmd_sync (the `elif config:` block, lines 307-318)
- [ ] Keep Config.from_env() usage only where still needed (e.g., `infraverse serve` if applicable)
- [ ] Remove now-unused `_build_provider_from_account()` from cli.py (moved to sync/providers.py)
- [ ] Run tests — must pass before next task

### Task 4: Clean up Config class

**Files:**
- Modify: `src/infraverse/config.py`
- Modify: `src/infraverse/cli.py`

- [ ] Remove `yc_token`, `yc_sa_key_file`, `vcd_*` fields from Config if no longer used by any caller
- [ ] If `infraverse serve` or Scheduler still uses Config, keep what's needed but document what's legacy
- [ ] Update Config.from_env() validation — don't require YC_TOKEN if not used
- [ ] Run tests — must pass before next task

### Task 5: Verify acceptance criteria

- [ ] Verify: `infraverse sync --dry-run --config config.yaml` works with per-account YC credentials
- [ ] Verify: each account gets its own sync cycle in logs (separate fetch + sync per account)
- [ ] Verify: cleanup scoping by cloud_name works (our earlier fix)
- [ ] Run full test suite: `python3 -m pytest tests/ -v`
- [ ] Run linter: `ruff check src/ tests/`

### Task 6: [Final] Update documentation

- [ ] Update CLAUDE.md memory if new patterns discovered
- [ ] Move this plan to `docs/plans/completed/`

## Technical Details

### Current flow (broken)
```
YAML config → cmd_sync → Config(yc_token="") → SyncEngine(config)
  → YandexCloudClient(token="") → Bearer '' → API errors
```

### Target flow
```
YAML config → cmd_sync → build_providers_from_db(session)
  → [(YCClient(account1_creds), YC_PROFILE), (YCClient(account2_creds), YC_PROFILE), ...]
  → SyncEngine(netbox_client, providers, dry_run)
  → per-account: fetch_all_data → sync_infrastructure → sync_vms → cleanup
```

### SyncEngine new signature
```python
class SyncEngine:
    def __init__(self, netbox: NetBoxClient, providers: list, dry_run: bool = False):
        self.nb = netbox
        self._providers = providers  # list of (client, ProviderProfile)
        self.dry_run = dry_run
```

### Provider builder
```python
def build_provider(account: CloudAccount) -> tuple:
    """Build (cloud_client, ProviderProfile) from a CloudAccount."""
    creds = account.config or {}
    if account.provider_type == "yandex_cloud":
        client = YandexCloudClient(token_provider=resolve_token_provider(creds))
        return (client, YC_PROFILE)
    elif account.provider_type == "vcloud":
        client = VCloudDirectorClient(url=creds["url"], ...)
        return (client, VCLOUD_PROFILE)
```

## Post-Completion

**Manual verification:**
- Run `infraverse sync --config config.yaml` (non-dry-run) against real NetBox
- Verify element-yandex syncs only its 1 folder/16 VMs
- Verify gt-yandex syncs its 43 folders/298 VMs
- Verify gt-vcloud syncs its 41 VMs
- Verify cleanup doesn't cross-delete between accounts
