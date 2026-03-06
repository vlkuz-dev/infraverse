# Infraverse

Infrastructure visibility platform - sync multi-cloud infrastructure to NetBox and compare state across clouds, NetBox, and Zabbix monitoring.

## Features

- **Multi-cloud support:** Yandex Cloud and vCloud Director providers via unified CloudProvider interface
- **SQLite database:** persistent storage for VMs, monitoring hosts, sync runs, and tenant/account hierarchy
- **Tenant & CloudAccount model:** multi-customer, multi-cloud support (one tenant = one customer, many cloud accounts)
- **Zabbix integration:** verify VMs are present in monitoring
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

MonitoringHost (Zabbix hosts, independent of cloud accounts)
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

Copy and configure environment variables:

```bash
cp .env.example .env
# Edit .env with your credentials
```

### Required

| Variable | Description |
|---|---|
| `YC_TOKEN` | Yandex Cloud OAuth token |
| `NETBOX_URL` | NetBox API URL (must include `/api` suffix, e.g. `https://netbox.example.com/api`) |
| `NETBOX_TOKEN` | NetBox API token with write permissions |

### Database

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite:///infraverse.db` | SQLAlchemy database URL |

### Optional: vCloud Director

| Variable | Default | Description |
|---|---|---|
| `VCD_URL` | -- | vCloud Director API URL (e.g. `https://vcd.example.com`) |
| `VCD_USER` | -- | vCloud Director username |
| `VCD_PASSWORD` | -- | vCloud Director password |
| `VCD_ORG` | `System` | vCloud Director organization |

### Optional: Zabbix

| Variable | Default | Description |
|---|---|---|
| `ZABBIX_URL` | -- | Zabbix server URL (e.g. `https://zabbix.example.com`) |
| `ZABBIX_USER` | -- | Zabbix username |
| `ZABBIX_PASSWORD` | -- | Zabbix password |

### Optional: Scheduler

| Variable | Default | Description |
|---|---|---|
| `SYNC_INTERVAL_MINUTES` | `0` (disabled) | Background data ingestion interval in minutes. Set to a positive value (e.g. `30`) to enable automatic fetching. |

### Optional: External Links

URL templates for linking detail pages to external systems. Use `{placeholder}` syntax for dynamic values.

| Variable | Default | Description |
|---|---|---|
| `YC_CONSOLE_URL` | -- | Yandex Cloud console URL template, e.g. `https://console.yandex.cloud/folders/{folder_id}/compute/instances/{vm_id}` |
| `ZABBIX_HOST_URL` | -- | Zabbix host URL template, e.g. `{zabbix_url}/hosts.php?form=update&hostid={host_id}` |
| `NETBOX_VM_URL` | -- | NetBox VM URL template, e.g. `{netbox_url}/virtualization/virtual-machines/{vm_id}/` |

### Optional: General

| Variable | Default | Description |
|---|---|---|
| `LOG_LEVEL` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |

## Usage

### Database setup

Initialize the database and create a default tenant before first use:

```bash
# Create database tables
infraverse db init

# Create default tenant
infraverse db seed
```

### Sync to NetBox

```bash
# Full sync
infraverse sync

# Preview changes without applying
infraverse sync --dry-run

# Skip orphaned object cleanup
infraverse sync --no-cleanup

# Use standard (non-batch) sync mode
infraverse sync --no-batch
```

### Web UI

Start the web dashboard to view infrastructure comparison:

```bash
# Start web server on default port 8000
infraverse serve

# Custom host and port
infraverse serve --host 127.0.0.1 --port 9000

# Enable automatic data fetching every 30 minutes
SYNC_INTERVAL_MINUTES=30 infraverse serve
```

The web UI provides:
- **Dashboard** (`/`) -- tenant overview, provider status, last sync timestamps, summary stats, "Fetch Now" button, scheduler status
- **Comparison view** (`/comparison`) -- table of all VMs with status columns (cloud, NetBox, Zabbix), color-coded discrepancies, quick-filter buttons (all / with issues / in sync)
- **VM detail** (`/vms/{id}`) -- individual VM page with resources, IPs, comparison status, and external links to cloud console / NetBox / Zabbix
- **Cloud accounts** (`/accounts`) -- list of all cloud accounts grouped by tenant
- **Account detail** (`/accounts/{id}`) -- account info, VM list, sync history, external links
- HTMX-powered refresh without full page reload
- Filtering by provider, status, and name search

### Docker

```bash
# Sync mode
docker run --rm --env-file .env infraverse sync
docker run --rm --env-file .env infraverse sync --dry-run

# Web UI mode
docker run --rm -p 8000:8000 --env-file .env infraverse serve --host 0.0.0.0
```

## Project Structure

```
src/infraverse/
  __init__.py              # Package version
  __main__.py              # python -m support
  cli.py                   # CLI: sync, serve, db init, db seed
  config.py                # Configuration from env vars
  scheduler.py             # APScheduler-based background ingestion
  db/
    engine.py              # SQLAlchemy engine, session factory
    models.py              # ORM models: Tenant, CloudAccount, VM, MonitoringHost, SyncRun
    repository.py          # Data access layer (CRUD operations)
  providers/
    base.py                # CloudProvider Protocol + VMInfo dataclass
    yandex.py              # Yandex Cloud API client
    vcloud.py              # vCloud Director API client
    zabbix.py              # Zabbix JSON-RPC client
    netbox.py              # NetBox API wrapper (pynetbox)
  sync/
    engine.py              # Top-level sync orchestrator
    ingest.py              # DataIngestor: providers -> DB
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
    routes/
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
LOG_LEVEL=DEBUG infraverse sync --dry-run
```

## How It Works

### Data Ingestion

1. `infraverse db init` creates the SQLite database with all tables
2. `infraverse db seed` creates a default tenant
3. Cloud accounts are configured per tenant in the database
4. DataIngestor fetches VMs from each cloud account and stores them in DB
5. Monitoring hosts are fetched from Zabbix and stored in DB
6. Each ingestion creates a SyncRun record tracking status and item counts

### Sync to NetBox

1. Fetches data from Yandex Cloud API (zones, clouds, folders, subnets, VMs)
2. Creates/updates NetBox infrastructure (sites, cluster type, clusters, prefixes)
3. Syncs VMs with resources, interfaces, and IP addresses
4. Cleans up orphaned objects no longer present in Yandex Cloud

All synced objects are tagged with `synced-from-yc` for easy identification.

### Comparison (Web UI)

1. Reads VMs from DB (previously ingested from cloud providers)
2. Reads monitoring hosts from DB (previously ingested from Zabbix)
3. Matches VMs by name (primary) and IP address (secondary fallback)
4. Identifies discrepancies: VMs missing from any system
5. Displays results in an interactive web dashboard

## License

MIT License - see [LICENSE](LICENSE) for details.

## Author

[vlkuz-dev](https://github.com/vlkuz-dev)
