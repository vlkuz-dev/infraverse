# Infraverse v0.0.3: Multi-Tenant, SSO/OIDC, Monitoring Logic

## Overview

Three equally important features for v0.0.3:

1. **Multi-tenant + multi-cloud**: YAML config file defining tenants and cloud accounts with env-var-expandable credentials, DB sync on startup, tenant-scoped web UI
2. **SSO/OIDC**: Basic OIDC authentication with single role check for access (no local user DB, trust the IdP)
3. **Monitoring logic inversion**: Instead of bulk-fetching all Zabbix hosts, query Zabbix per known VM to check monitoring presence

### Problem Statement

- CLI hardcodes a single "Default" tenant (`cli.py:94-97`), making multi-tenant impossible
- Cloud credentials are env-var based (single set), preventing multiple cloud accounts
- Web UI shows all data globally with zero authentication
- Zabbix integration fetches ALL hosts (`providers/zabbix.py:205-229`), most of which aren't VMs
- `MonitoringHost` table has no tenant association (`db/models.py:92-111`)

### Integration

- Config file replaces env-var credential management for clouds
- OIDC wraps all web routes with auth middleware (optional — disabled when not configured)
- Monitoring logic change inverts the data flow: DB VMs drive Zabbix queries instead of vice versa

## Context (from discovery)

**Files/components involved:**
- `src/infraverse/config.py` — current env-var config
- `src/infraverse/db/models.py` — Tenant, CloudAccount, VM, MonitoringHost, SyncRun
- `src/infraverse/db/repository.py` — CRUD operations
- `src/infraverse/sync/ingest.py` — DataIngestor (monitoring ingest)
- `src/infraverse/providers/zabbix.py` — ZabbixClient (bulk fetch)
- `src/infraverse/comparison/engine.py` — ComparisonEngine
- `src/infraverse/web/app.py` — FastAPI app factory (no auth)
- `src/infraverse/web/routes/` — all routes (unprotected)
- `src/infraverse/cli.py` — hardcoded "Default" tenant
- `src/infraverse/scheduler.py` — background ingestion

**Existing patterns:**
- Tenant -> CloudAccount -> VM hierarchy already in DB
- `list_cloud_accounts_by_tenant(tenant_id)` exists in repository
- Zabbix client supports both API versions (user/username param)
- ~795+ tests, all passing in <1s

## Development Approach

- **Testing approach**: TDD (tests first)
- Complete each task fully before moving to the next
- Make small, focused changes
- **CRITICAL: every task MUST include new/updated tests** for code changes in that task
  - tests are not optional — they are a required part of the checklist
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

- **Unit tests**: required for every task
- Test command: `python3 -m pytest tests/ -v`
- Linter: `ruff check src/ tests/`

## Progress Tracking

- Mark completed items with `[x]` immediately when done
- Add newly discovered tasks with + prefix
- Document issues/blockers with ! prefix
- Update plan if implementation deviates from original scope
- Keep plan in sync with actual work done

## What Goes Where

- **Implementation Steps** (`[ ]` checkboxes): tasks achievable within this codebase
- **Post-Completion** (no checkboxes): items requiring external action

## Implementation Steps

---

### Phase 1: YAML Config File + Multi-Tenant

---

### Task 1: YAML config file schema and parser

- [x] write tests for `load_config(path)`: valid config, minimal config, missing file
- [x] write tests for env var expansion: `${VAR}` replaced, missing env var raises error
- [x] create `src/infraverse/config_file.py` with dataclasses: `TenantConfig`, `CloudAccountConfig`, `MonitoringConfig`, `OidcConfig`, `InfraverseConfig`
- [x] implement `load_config(path: str) -> InfraverseConfig` — parse YAML, expand env vars
- [x] write tests for edge cases: duplicate tenant names, unknown provider types, empty accounts list
- [x] run tests — must pass before next task

**Config file format:**
```yaml
tenants:
  acme-corp:
    description: "ACME Corporation"
    cloud_accounts:
      - name: "acme-yandex-prod"
        provider: yandex_cloud
        token: "${YC_TOKEN_ACME}"
      - name: "acme-vcloud"
        provider: vcloud
        url: "https://vcd.example.com"
        username: "admin"
        password: "${VCD_PASSWORD}"
        org: "acme-org"
  beta-inc:
    description: "Beta Inc"
    cloud_accounts:
      - name: "beta-yandex"
        provider: yandex_cloud
        token: "${YC_TOKEN_BETA}"

monitoring:
  zabbix:
    url: "https://zabbix.example.com/api_jsonrpc.php"
    username: "api_user"
    password: "${ZABBIX_PASSWORD}"

oidc:
  provider_url: "https://keycloak.example.com/realms/infraverse"
  client_id: "infraverse"
  client_secret: "${OIDC_CLIENT_SECRET}"
  required_role: "infraverse-admin"
```

### Task 2: Config-to-DB sync on startup

- [x] write tests for `sync_config_to_db()`: new tenants created, existing tenants updated, accounts created/updated
- [x] write tests for idempotency: running sync twice produces same result
- [x] create `src/infraverse/sync/config_sync.py` with `sync_config_to_db(config: InfraverseConfig, session) -> SyncReport`
- [x] create/update Tenant records from config tenant names
- [x] create/update CloudAccount records from config, storing credentials in `config` JSON field
- [x] handle removed tenants/accounts: mark accounts as inactive (add `is_active` field), don't delete data
- [x] write tests for removed account handling: account in DB but not in config gets deactivated
- [x] run tests — must pass before next task

### Task 3: Update CLI to use config file

- [x] write tests for CLI `--config` flag: loads config, builds providers from DB accounts
- [x] add `--config` / `-c` option to `sync` and `serve` CLI commands
- [x] update `_ingest_to_db()` to call `sync_config_to_db()` then build providers from all active CloudAccounts
- [x] write tests for backward compatibility: CLI works without `--config` using current env var behavior
- [x] keep current env var fallback (no config file = existing single-tenant "Default" behavior)
- [x] run tests — must pass before next task

### Task 4: Update scheduler to use config-driven accounts

- [x] write tests for scheduler reading credentials from CloudAccount.config JSON
- [x] update `_build_providers()` to read cloud credentials from `account.config` dict
- [x] update `_build_zabbix_client()` to accept monitoring config (from config file or env vars)
- [x] pass config file path or parsed config to SchedulerService
- [x] write tests for scheduler with multiple tenants and accounts
- [x] run tests — must pass before next task

### Task 5: Tenant-scoped web UI — dashboard and accounts

- [x] write tests for dashboard route with `?tenant_id=` filter parameter
- [x] add tenant selector dropdown to dashboard template
- [x] filter VMs and accounts by selected tenant (or show all if no filter)
- [x] update `accounts_list()` to support `?tenant_id=` query param
- [x] write tests for account list with and without tenant filter
- [x] run tests — must pass before next task

### Task 6: Tenant-scoped web UI — VMs and comparison

- [x] write tests for VM list with tenant/account filtering
- [x] add tenant/account filter to VM list page
- [x] update comparison route to support `?tenant_id=` scoping
- [x] update `_run_comparison()` to filter VMs by tenant when `tenant_id` is provided
- [x] write tests for comparison scoped to tenant vs global comparison
- [x] run tests — must pass before next task

---

### Phase 2: Monitoring Logic Inversion

---

### Task 7: ZabbixClient — add per-VM host search

- [x] write tests for `search_host_by_name(name)`: found, not found, API error
- [x] add `search_host_by_name(name: str) -> ZabbixHost | None` to ZabbixClient
- [x] use Zabbix `host.get` with `filter: {"name": name}` for exact match
- [x] write tests for `search_host_by_ip(ip)`: found, not found
- [x] add `search_host_by_ip(ip: str) -> ZabbixHost | None` as fallback lookup
- [x] run tests — must pass before next task

### Task 8: Add cloud_account_id to MonitoringHost

- [x] write tests for MonitoringHost with cloud_account_id FK
- [x] add `cloud_account_id` nullable FK to `MonitoringHost` model
- [x] update `upsert_monitoring_host()` to accept `cloud_account_id` parameter
- [x] add `get_monitoring_hosts_by_account(cloud_account_id)` repository method
- [x] write Alembic migration or update `init_db()` for new column
- [x] write tests for repository methods with cloud_account_id
- [x] run tests — must pass before next task

### Task 9: Monitoring check per VM

- [x] write tests for `check_vm_monitoring(vm, zabbix_client)`: VM found by name, by IP, not found
- [x] create `src/infraverse/sync/monitoring.py` with `check_vm_monitoring()` function
- [x] query Zabbix by VM name first, fallback to IP addresses
- [x] return monitoring status (found/not found) with host details
- [x] write tests for batch `check_all_vms_monitoring(vms, zabbix_client)`: mixed results
- [x] run tests — must pass before next task

### Task 10: Refactor DataIngestor for new monitoring flow

- [x] write tests for updated `ingest_monitoring_hosts()` that takes VM list and queries per VM
- [x] refactor `DataIngestor.ingest_monitoring_hosts()` to iterate VMs and call `check_vm_monitoring()`
- [x] store results in MonitoringHost with `cloud_account_id` set
- [x] remove bulk `fetch_hosts()` usage from ingest flow
- [x] update `ingest_all()` to pass VMs to new monitoring check
- [x] write tests for full ingest flow: cloud ingest then monitoring check
- [x] run tests — must pass before next task

### Task 11: Update ComparisonEngine for DB-driven monitoring

- [x] write tests for comparison using MonitoringHost records linked to accounts
- [x] update comparison route to load MonitoringHost data per account/tenant
- [x] simplify comparison: monitoring presence comes from MonitoringHost records matching VM names
- [x] remove need to pass raw `zabbix_hosts` list to ComparisonEngine
- [x] write tests for comparison with partial monitoring data (some accounts have monitoring, some don't)
- [x] run tests — must pass before next task

---

### Phase 3: SSO/OIDC Authentication

---

### Task 12: OIDC dependencies and config

- [x] add `authlib` and `itsdangerous` to project dependencies (pyproject.toml)
- [x] write tests for OIDC config parsing from YAML: all fields present, missing fields
- [x] extend `InfraverseConfig` / `OidcConfig` dataclass with validation
- [x] write tests for `oidc_configured` property: True when section present, False when absent
- [x] run tests — must pass before next task

### Task 13: OIDC login and callback routes

- [x] write tests for `/auth/login` redirect: builds correct authorize URL
- [x] create `src/infraverse/web/routes/auth.py` with `login`, `callback`, `logout` routes
- [x] implement OIDC authorization code flow using authlib
- [x] on callback: validate ID token, extract user info (name, email, roles)
- [x] write tests for callback: valid token with role, valid token without required role (403), invalid token
- [x] write tests for logout: clears session, redirects to login
- [x] run tests — must pass before next task

### Task 14: Auth middleware and session management

- [x] write tests for middleware: authenticated request passes through, unauthenticated redirects to login
- [x] create session middleware using `itsdangerous` signed cookies
- [x] store user info (name, email, has_role) in session after successful OIDC callback
- [x] add middleware to FastAPI app — skip for `/auth/*`, `/static/*`, `/health`
- [x] write tests for session expiry: expired cookie redirects to login
- [x] write tests for role check: user with required role gets access, user without gets 403
- [x] run tests — must pass before next task

### Task 15: Optional auth mode + UI user display

- [ ] write tests for app behavior when OIDC is not configured: all routes accessible, no login redirect
- [ ] make auth middleware conditional: if no `oidc` section in config, middleware is not applied
- [ ] add user info display in web UI header template (name/email when authenticated)
- [ ] write tests for UI with and without authentication
- [ ] run tests — must pass before next task

---

### Phase 4: Finalization

---

### Task 16: Verify acceptance criteria

- [ ] verify multi-tenant: create config with 2+ tenants, different cloud accounts, run ingest
- [ ] verify same cloud provider can be used by different tenants (same provider_type, different credentials)
- [ ] verify OIDC: login flow works when configured, app works without OIDC when not configured
- [ ] verify monitoring: only known VMs are checked in Zabbix, no bulk fetch
- [ ] run full test suite (`python3 -m pytest tests/ -v`)
- [ ] run linter (`ruff check src/ tests/`) — all issues must be fixed
- [ ] verify test coverage meets project standard

### Task 17: [Final] Update documentation

- [ ] update README.md with v0.0.3 features (multi-tenant, SSO, monitoring)
- [ ] create `config.example.yaml` with commented examples
- [ ] document OIDC setup instructions (Keycloak, generic provider)
- [ ] update project knowledge docs if new patterns discovered

## Technical Details

### Config File Format

See Task 1 for full YAML schema. Key design decisions:
- **Env var expansion**: `${VAR_NAME}` syntax, expanded at parse time via `os.environ`
- **Error on missing env var**: Fail fast if referenced variable is not set
- **Tenant names are keys**: YAML dict keys become tenant names (must be unique)
- **Provider-specific fields**: Each cloud account has provider-specific config (token for YC, url/username/password/org for vCloud)

### Monitoring Logic Change

```
OLD: ZabbixClient.fetch_hosts() -> ALL hosts -> MonitoringHost table -> ComparisonEngine
NEW: For each VM in DB -> ZabbixClient.search_host_by_name(vm.name) -> store result -> ComparisonEngine reads DB
```

- Per-VM query uses Zabbix `host.get` with `filter` (exact match), not `search` (partial)
- Fallback to IP-based lookup if name doesn't match
- `MonitoringHost` records now scoped to `cloud_account_id`

### OIDC Flow

```
1. User visits any route -> middleware checks session cookie
2. No session -> redirect to /auth/login
3. /auth/login -> redirect to OIDC provider authorize URL
4. User authenticates at IdP -> redirect back to /auth/callback
5. Callback validates ID token, checks required_role in claims
6. Session cookie set -> user redirected to original URL
```

- Single role check: user must have `required_role` claim to access the app
- No local user DB — trust the IdP completely
- Session stored in signed cookie (itsdangerous), no server-side session store

### DB Model Changes

- `MonitoringHost`: add `cloud_account_id` FK (Integer, nullable, FK to cloud_accounts.id)
- `CloudAccount`: add `is_active` field (Boolean, default True) for config sync deactivation
- No new tables for auth (stateless sessions via signed cookies)

### New Dependencies

- `pyyaml` — YAML config file parsing
- `authlib` — OIDC client implementation
- `itsdangerous` — signed cookie sessions

## Post-Completion

**Manual verification:**
- Test OIDC login flow with a real IdP (Keycloak, Google Workspace, etc.)
- Test multi-tenant with 2+ real cloud accounts and different providers
- Verify per-VM Zabbix queries don't cause rate limiting with large VM counts (100+ VMs)
- Performance comparison: per-VM queries vs old bulk fetch

**External system setup:**
- Register OIDC client in identity provider (redirect URI: `https://<host>/auth/callback`)
- Create YAML config file for each deployment environment
- Update deployment scripts/docs for new config file requirement
