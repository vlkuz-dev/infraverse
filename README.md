# Infraverse

Infrastructure visibility platform - sync multi-cloud infrastructure to NetBox and compare state across clouds, NetBox, and Zabbix monitoring.

## Features

- **Multi-tenant YAML config:** define tenants and cloud accounts in a single config file with `${ENV_VAR}` expansion for credentials
- **Multi-cloud support:** Yandex Cloud and vCloud Director providers via unified CloudProvider interface
- **SSO/OIDC authentication:** optional OpenID Connect login with role-based access control (works with Keycloak, Google Workspace, Azure AD, etc.)
- **CSRF protection:** automatic per-session CSRF tokens validated on all mutating requests (POST/PUT/DELETE/PATCH) when OIDC is enabled
- **Bulk monitoring check:** fetch all Zabbix hosts once per ingestion, then match VMs locally by name and IP (falls back to per-VM queries if bulk fetch fails)
- **Automatic retry with backoff:** transient API errors (429, 500-503, connection failures) are retried with exponential backoff across all cloud and monitoring providers
- **SQLite database:** persistent storage for VMs, monitoring hosts, sync runs, and tenant/account hierarchy
- **Tenant & CloudAccount model:** multi-customer, multi-cloud support (one tenant = one customer, many cloud accounts)
- **Tenant-scoped web UI:** filter dashboard, VM list, and comparison by tenant
- **Comparison engine:** detect discrepancies across cloud, NetBox, and Zabbix (reads from DB)
- **Web UI:** FastAPI dashboard with Tabler admin template, HTMX-powered comparison view, filtering, and refresh
- **Scheduled data fetching:** APScheduler-based background ingestion at configurable intervals
- **Manual "Fetch Now" button:** trigger on-demand data ingestion from the dashboard
- **Detail pages:** dedicated pages for individual VMs and cloud accounts with external resource links
- **Quick-filter buttons:** filter comparison results by status (all / with issues / in sync)
- **External resource links:** configurable URL templates linking to Yandex Cloud console, Zabbix, and NetBox
- **NetBox sync:** map cloud structure to NetBox hierarchy (zones -> sites, folders -> clusters)
- Automatic creation of sites, clusters, and prefixes
- Two sync modes: optimized batch (default) and standard sequential
- Dry-run mode for previewing changes
- Automatic cleanup of orphaned objects
- Docker support

## Architecture

```
Provider APIs -> DataIngestor -> SQLite DB -> Web UI (read from DB)
                                           -> ComparisonEngine (read from DB)
                                           -> SyncEngine -> NetBox API
```

### Data Model

```
Tenant (customer/organization)
  -> CloudAccount (one cloud connection, e.g. "YC Russia", "vCloud@Dataspace")
       -> VM (virtual machines from that account)
       -> MonitoringHost (Zabbix hosts linked to cloud account)

SyncRun (tracks each ingestion run per account)
```

### Cloud-to-NetBox Mapping

| Cloud Concept | NetBox | Description |
|---|---|---|
| Availability Zone | Site | Each zone becomes a NetBox site |
| Folder | Cluster | Folders mapped to NetBox clusters |
| Cloud | Cluster Group | Cloud organizations in cluster naming |
| Cluster Type | `yandex-cloud` | All clusters use the unified type |
| VPC/Subnet | Prefix | Network prefixes assigned to zone sites |
| VM | Virtual Machine | VMs assigned to clusters and sites |

## Requirements

- Python 3.10+
- NetBox 3.0+
- Yandex Cloud account with OAuth token
- (Optional) vCloud Director instance
- (Optional) Zabbix server

## Installation

### From source

```bash
git clone https://github.com/vlkuz-dev/infraverse.git
cd infraverse
pip install .
```

### Development install

```bash
pip install -e ".[dev]"
```

### Docker

```bash
docker build -t infraverse .
```

## Configuration

Infraverse supports two configuration modes:

1. **YAML config file** (recommended for multi-tenant) -- define all tenants, cloud accounts, monitoring, and OIDC in a single file
2. **Environment variables** (legacy single-tenant) -- configure a single tenant via `.env` file

### YAML Config File (recommended)

Create a config file (see `config.example.yaml` for a full example):

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
    url: "https://zabbix.example.com"
    username: "api_user"
    password: "${ZABBIX_PASSWORD}"

oidc:
  provider_url: "https://keycloak.example.com/realms/infraverse"
  client_id: "infraverse"
  client_secret: "${OIDC_CLIENT_SECRET}"
  required_role: "infraverse-admin"
```

Use the config file with `--config` / `-c` flag:

```bash
infraverse sync --config config.yaml
infraverse serve --config config.yaml
```

Credentials use `${VAR_NAME}` syntax and are expanded from environment variables at load time. Missing env vars cause an immediate error.

**Note:** The YAML config file manages tenants, cloud accounts, monitoring, and OIDC. The following settings remain environment variables even in YAML config mode:

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Database connection (default: `sqlite:///infraverse.db`) |
| `NETBOX_URL`, `NETBOX_TOKEN` | Required only if syncing to NetBox |
| `SYNC_INTERVAL_MINUTES` | Background ingestion interval (default: `0` = disabled) |
| `LOG_LEVEL` | Logging level (default: `INFO`) |
| `YC_CONSOLE_URL`, `ZABBIX_HOST_URL`, `NETBOX_VM_URL` | External link URL templates for detail pages |
| `SESSION_SECRET` | Dedicated secret for signing session cookies (overrides `oidc.session_secret` config) |
| `INFRAVERSE_DEBUG` | Set to `1` to relax secure cookie flags for local HTTP dev (`https_only=False`, `same_site=lax`) |

### Environment Variables (legacy single-tenant)

For single-tenant setups without a YAML config file:

```bash
cp .env.example .env
# Edit .env with your credentials
```

#### Required (for NetBox sync)

| Variable | Description |
|---|---|
| `YC_TOKEN` | Yandex Cloud OAuth token |
| `NETBOX_URL` | NetBox API URL (must include `/api` suffix, e.g. `https://netbox.example.com/api`) |
| `NETBOX_TOKEN` | NetBox API token with write permissions |

#### Database

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite:///infraverse.db` | SQLAlchemy database URL |

#### Optional: vCloud Director

| Variable | Default | Description |
|---|---|---|
| `VCD_URL` | -- | vCloud Director API URL (e.g. `https://vcd.example.com`) |
| `VCD_USER` | -- | vCloud Director username |
| `VCD_PASSWORD` | -- | vCloud Director password |
| `VCD_ORG` | `System` | vCloud Director organization |

#### Optional: Zabbix

| Variable | Default | Description |
|---|---|---|
| `ZABBIX_URL` | -- | Zabbix server URL (e.g. `https://zabbix.example.com`) |
| `ZABBIX_USER` | -- | Zabbix username |
| `ZABBIX_PASSWORD` | -- | Zabbix password |

#### Optional: Scheduler

| Variable | Default | Description |
|---|---|---|
| `SYNC_INTERVAL_MINUTES` | `0` (disabled) | Background data ingestion interval in minutes. Set to a positive value (e.g. `30`) to enable automatic fetching. |

#### Optional: External Links

URL templates for linking detail pages to external systems. Use `{placeholder}` syntax for dynamic values.

| Variable | Default | Description |
|---|---|---|
| `YC_CONSOLE_URL` | -- | Yandex Cloud console URL template, e.g. `https://console.yandex.cloud/folders/{folder_id}/compute/instances/{vm_id}` |
| `ZABBIX_HOST_URL` | -- | Zabbix host URL template, e.g. `{zabbix_url}/hosts.php?form=update&hostid={host_id}` |
| `NETBOX_VM_URL` | -- | NetBox VM URL template, e.g. `{netbox_url}/virtualization/virtual-machines/{vm_id}/` |

#### Optional: General

| Variable | Default | Description |
|---|---|---|
| `LOG_LEVEL` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |

## Usage

### Database setup

Initialize the database and create a default tenant before first use:

```bash
# Create database tables (applies all Alembic migrations)
infraverse db init

# Create default tenant (only needed for env-var mode without YAML config)
infraverse db seed
```

When using a YAML config file, tenants and cloud accounts are synced to the database automatically on startup.

### Database migrations

Schema changes are managed with [Alembic](https://alembic.sqlalchemy.org/). Use the built-in CLI commands:

```bash
# Apply all pending migrations
infraverse db upgrade

# Roll back the last migration
infraverse db downgrade

# Generate a new migration from model changes
infraverse db migrate -m "add_new_column"
```

### Sync to NetBox

The `sync` command requires a YAML config file (`--config`):

```bash
# Full sync
infraverse sync --config config.yaml

# Preview changes without applying
infraverse sync --config config.yaml --dry-run

# Skip orphaned object cleanup
infraverse sync --config config.yaml --no-cleanup

# Use standard (non-batch) sync mode
infraverse sync --config config.yaml --no-batch
```

### Web UI

Start the web dashboard to view infrastructure comparison:

```bash
# Start with YAML config (multi-tenant, optional OIDC)
infraverse serve --config config.yaml

# Start with env vars (legacy)
infraverse serve

# Custom host and port
infraverse serve --config config.yaml --host 127.0.0.1 --port 9000

# Enable automatic data fetching every 30 minutes
SYNC_INTERVAL_MINUTES=30 infraverse serve --config config.yaml
```

The web UI provides:
- **Dashboard** (`/`) -- tenant overview, provider status, last sync timestamps, summary stats, "Fetch Now" button, scheduler status
- **Tenant filtering** -- dropdown to scope dashboard, VM list, and comparison to a specific tenant
- **Comparison view** (`/comparison`) -- table of all VMs with status columns (cloud, NetBox, Zabbix), color-coded discrepancies, quick-filter buttons (all / with issues / in sync)
- **VM detail** (`/vms/{id}`) -- individual VM page with resources, IPs, comparison status, and external links to cloud console / NetBox / Zabbix
- **Cloud accounts** (`/accounts`) -- list of all cloud accounts grouped by tenant
- **Account detail** (`/accounts/{id}`) -- account info, VM list, sync history, external links
- **User info display** -- shows authenticated user name/email in the header when OIDC is enabled
- HTMX-powered refresh without full page reload
- Filtering by provider, status, and name search

### Docker

```bash
# With YAML config
docker run --rm -v ./config.yaml:/app/config.yaml --env-file .env infraverse sync --config /app/config.yaml
docker run --rm -p 8000:8000 -v ./config.yaml:/app/config.yaml --env-file .env infraverse serve --config /app/config.yaml --host 0.0.0.0

# With env vars (legacy, serve only — sync requires --config)
docker run --rm -p 8000:8000 --env-file .env infraverse serve --host 0.0.0.0
```

## Project Structure

```
src/infraverse/
  __init__.py              # Package version
  __main__.py              # python -m support
  cli.py                   # CLI: sync, serve, db init/seed/migrate/upgrade/downgrade
  config.py                # Configuration from env vars (legacy)
  config_file.py           # YAML config file parser (multi-tenant)
  scheduler.py             # APScheduler-based background ingestion
  db/
    engine.py              # SQLAlchemy engine, session factory
    models.py              # ORM models: Tenant, CloudAccount, VM, MonitoringHost, SyncRun
    repository.py          # Data access layer (CRUD operations)
    migrate.py             # Alembic programmatic helpers (upgrade, downgrade, generate)
    migrations/            # Alembic migration environment and version scripts
  providers/
    base.py                # CloudProvider Protocol + VMInfo dataclass
    yandex.py              # Yandex Cloud API client
    vcloud.py              # vCloud Director API client
    zabbix.py              # Zabbix JSON-RPC client
    retry.py               # Retry with exponential backoff decorator
    netbox.py              # NetBox API wrapper (pynetbox)
  sync/
    engine.py              # Top-level sync orchestrator
    orchestrator.py        # Shared ingestion cycle for CLI + scheduler
    providers.py           # Cloud client + Zabbix client builders
    provider_profile.py    # ProviderProfile dataclass + per-provider constants
    ingest.py              # DataIngestor: providers -> DB
    config_sync.py         # YAML config to DB sync (tenants, accounts)
    monitoring.py          # Bulk Zabbix monitoring check (with per-VM fallback)
    size_converters.py     # Size conversion utilities (bytes -> NetBox MB)
    infrastructure.py      # Sites, clusters, prefixes sync
    vms.py                 # VM sync logic
    batch.py               # Optimized batch operations
    cleanup.py             # Orphaned object cleanup
  comparison/
    engine.py              # Cross-system matching
    models.py              # VMState, ComparisonResult
  ip/
    classifier.py          # Private IP detection
    utils.py               # CIDR helpers
  web/
    app.py                 # FastAPI app factory with scheduler lifespan
    links.py               # External URL template helper
    csrf.py                # CSRF protection middleware
    middleware.py           # OIDC auth middleware and session management
    routes/
      auth.py              # OIDC login, callback, logout routes
      dashboard.py         # Dashboard routes
      comparison.py        # Comparison routes with quick-filters
      sync.py              # Fetch-now and scheduler status endpoints
      vms.py               # VM detail route
      accounts.py          # Cloud account list and detail routes
    templates/             # Jinja2 + Tabler templates
    static/                # CSS overrides
tests/
  conftest.py
  db/                      # DB model and repository tests
  providers/               # Provider client tests
  sync/                    # Sync engine tests
  web/                     # Web route tests
```

## Development

### Running tests

```bash
python3 -m pytest tests/ -v
```

### Linting

```bash
ruff check src/ tests/
```

### Debug logging

```bash
LOG_LEVEL=DEBUG infraverse sync --config config.yaml --dry-run
```

## How It Works

### Data Ingestion

1. `infraverse db init` creates the SQLite database with all tables
2. With YAML config: `sync_config_to_db()` creates/updates tenants and cloud accounts from the config file
3. Without config: `infraverse db seed` creates a default tenant, cloud accounts come from env vars
4. DataIngestor fetches VMs from each active cloud account and stores them in DB
5. All Zabbix hosts are bulk-fetched once, then each VM is matched locally by name (then IP fallback); falls back to per-VM API queries if bulk fetch fails
6. Each ingestion creates a SyncRun record tracking status and item counts

### Monitoring Check

Infraverse bulk-fetches all hosts from Zabbix once per ingestion cycle, then matches VMs locally:

```
1. Fetch all Zabbix hosts (single paginated API call)
2. Build lookup dicts by name and IP address
3. For each VM in DB:
   a. Look up by VM name (exact match in local dict)
   b. If not found, look up by VM's IP addresses
   c. Store result in MonitoringHost table (linked to cloud account)
```

Falls back to per-VM Zabbix API queries if the bulk fetch fails.

### Sync to NetBox

1. Fetches data from Yandex Cloud API (zones, clouds, folders, subnets, VMs)
2. Creates/updates NetBox infrastructure (sites, cluster type, clusters, prefixes)
3. Syncs VMs with resources, interfaces, and IP addresses
4. Cleans up orphaned objects no longer present in Yandex Cloud

All synced objects are tagged with `synced-from-yc` for easy identification.

### Comparison (Web UI)

1. Reads VMs from DB (previously ingested from cloud providers)
2. Reads MonitoringHost records from DB (linked to cloud accounts)
3. Matches VMs by name (primary) and IP address (secondary fallback)
4. Identifies discrepancies: VMs missing from any system
5. Displays results in an interactive web dashboard, filterable by tenant

### SSO/OIDC Authentication

When the `oidc` section is present in the config file:

1. All web routes (except `/auth/*`, `/static/*`, `/health`) require authentication
2. Unauthenticated users are redirected to `/auth/login` -> OIDC provider
3. After authentication, the ID token is validated and the user's roles are checked
4. Users must have the `required_role` claim to access the app (otherwise 403)
5. Sessions are stored in signed cookies (no server-side session store) with `https_only=True` and `same_site=lax`
6. All mutating requests (POST, PUT, DELETE, PATCH) require a valid CSRF token via the `X-CSRF-Token` header
7. When OIDC is not configured, all routes are accessible without authentication

For local development over plain HTTP, set `INFRAVERSE_DEBUG=1` to relax cookie flags (`https_only=False`).

## OIDC Setup

Infraverse supports OpenID Connect authentication with any OIDC-compliant identity provider.

### General Setup

1. Register a new client/application in your identity provider
2. Set the redirect URI to: `https://<your-infraverse-host>/auth/callback`
3. Note the client ID, client secret, and provider URL (issuer URL)
4. Add the `oidc` section to your config file:

```yaml
oidc:
  provider_url: "https://your-idp.example.com/realms/your-realm"
  client_id: "infraverse"
  client_secret: "${OIDC_CLIENT_SECRET}"
  required_role: "infraverse-admin"
```

### Keycloak

1. Create a new client in Keycloak with "Client authentication" enabled
2. Set "Valid redirect URIs" to `https://<host>/auth/callback`
3. The `provider_url` is `https://<keycloak>/realms/<realm-name>`
4. Create a role (e.g. `infraverse-admin`) and assign it to users who should have access
5. Ensure the role appears in the ID token claims (Keycloak includes realm roles by default)

### Google Workspace

1. Create OAuth 2.0 credentials in Google Cloud Console
2. Set authorized redirect URI to `https://<host>/auth/callback`
3. The `provider_url` is `https://accounts.google.com`
4. For `required_role`, use a Google Workspace group or custom claim

### Disabling OIDC

Simply omit the `oidc` section from your config file. All routes will be accessible without authentication.

## License

MIT License - see [LICENSE](LICENSE) for details.

## Author

[vlkuz-dev](https://github.com/vlkuz-dev)
