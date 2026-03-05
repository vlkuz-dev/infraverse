# NetBox Yandex Cloud Sync (v3)

Synchronize multi-cloud infrastructure to NetBox and compare state across clouds, NetBox, and Zabbix monitoring.

## Features

- Synchronize VMs from Yandex Cloud to NetBox
- **Multi-cloud support:** Yandex Cloud and vCloud Director providers via unified CloudProvider interface
- **Zabbix integration:** verify VMs are present in monitoring
- **Comparison engine:** detect discrepancies across cloud, NetBox, and Zabbix
- **Web UI:** FastAPI dashboard with HTMX-powered comparison view, filtering, and refresh
- Map Yandex Cloud structure to NetBox hierarchy (zones -> sites, folders -> clusters)
- Automatic creation of sites, clusters, and prefixes
- Support for multiple clouds, folders, and availability zones
- Two sync modes: optimized batch (default) and standard sequential
- Dry-run mode for previewing changes
- Automatic cleanup of orphaned objects
- Automatic tagging of synced objects with `synced-from-yc`
- Docker support

## Architecture Mapping

| Yandex Cloud | NetBox | Description |
|---|---|---|
| Availability Zone | Site | Each YC zone becomes a NetBox site |
| Folder | Cluster | YC folders are mapped to NetBox clusters |
| Cloud | Cluster Group | Cloud organizations reflected in cluster naming |
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
git clone https://github.com/vlkuz-dev/netbox-yandexcloud-sync.git
cd netbox-yandexcloud-sync
pip install .
```

### Development install

```bash
pip install -e ".[dev]"
```

### Docker

```bash
docker build -t netbox-sync .
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

### Optional: vCloud Director

| Variable | Default | Description |
|---|---|---|
| `VCD_URL` | — | vCloud Director API URL (e.g. `https://vcd.example.com`) |
| `VCD_USER` | — | vCloud Director username |
| `VCD_PASSWORD` | — | vCloud Director password |
| `VCD_ORG` | `System` | vCloud Director organization |

### Optional: Zabbix

| Variable | Default | Description |
|---|---|---|
| `ZABBIX_URL` | — | Zabbix server URL (e.g. `https://zabbix.example.com`) |
| `ZABBIX_USER` | — | Zabbix username |
| `ZABBIX_PASSWORD` | — | Zabbix password |

### Optional: General

| Variable | Default | Description |
|---|---|---|
| `LOG_LEVEL` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |

All vCloud Director and Zabbix variables are optional. The service works with only Yandex Cloud configured (backward compatible).

## Usage

### Sync (default)

```bash
# Full sync
netbox-sync

# Preview changes without applying
netbox-sync --dry-run

# Skip orphaned object cleanup
netbox-sync --no-cleanup

# Use standard (non-batch) sync mode
netbox-sync --standard

# Show version
netbox-sync --version
```

### Web UI

Start the web dashboard to view infrastructure comparison:

```bash
# Start web server on default port 8000
netbox-sync serve

# Custom host and port
netbox-sync serve --host 127.0.0.1 --port 9000
```

The web UI provides:
- **Dashboard** (`/`) — provider status and summary statistics
- **Comparison view** (`/comparison`) — table of all VMs with status columns (cloud, NetBox, Zabbix) and color-coded discrepancies
- HTMX-powered refresh without full page reload
- Filtering by provider, status (all/only discrepancies), and name search

### Python module

```bash
python -m netbox_sync --help
```

### Docker

```bash
# Sync mode (default)
docker run --rm --env-file .env netbox-sync
docker run --rm --env-file .env netbox-sync --dry-run

# Web UI mode
docker run --rm -p 8000:8000 --env-file .env netbox-sync serve --host 0.0.0.0
docker run --rm -p 9000:9000 --env-file .env netbox-sync serve --host 0.0.0.0 --port 9000
```

## Project Structure

```
netbox-sync/
├── pyproject.toml
├── Dockerfile
├── .env.example
├── README.md
├── src/
│   └── netbox_sync/
│       ├── __init__.py           # Package version
│       ├── __main__.py           # python -m support
│       ├── cli.py                # CLI: sync (default) and serve subcommands
│       ├── config.py             # Configuration from env vars (YC, vCD, Zabbix)
│       ├── clients/
│       │   ├── base.py           # CloudProvider Protocol + VMInfo dataclass
│       │   ├── yandex.py         # Yandex Cloud API client
│       │   ├── vcloud.py         # vCloud Director API client
│       │   ├── zabbix.py         # Zabbix JSON-RPC client
│       │   └── netbox.py         # NetBox API wrapper (pynetbox)
│       ├── comparison/
│       │   ├── models.py         # VMState, ComparisonResult dataclasses
│       │   └── engine.py         # ComparisonEngine: cloud vs NetBox vs Zabbix
│       ├── sync/
│       │   ├── engine.py         # Top-level sync orchestrator
│       │   ├── batch.py          # Batch/optimized sync operations
│       │   ├── infrastructure.py # Sites, clusters, prefixes sync
│       │   ├── vms.py            # VM sync logic
│       │   └── cleanup.py        # Orphaned object cleanup
│       ├── web/
│       │   ├── app.py            # FastAPI application factory
│       │   ├── routes.py         # Web routes (dashboard, comparison)
│       │   ├── templates/        # Jinja2 templates
│       │   └── static/           # CSS styles
│       └── ip/
│           ├── classifier.py     # IP classification (private/public)
│           └── utils.py          # CIDR helpers
└── tests/
    ├── conftest.py
    ├── test_config.py
    ├── ip/
    ├── sync/
    └── clients/
```

## Development

### Running tests

```bash
pytest
```

### Debug logging

```bash
LOG_LEVEL=DEBUG netbox-sync --dry-run
```

## How It Works

### Sync Mode

1. Fetches data from Yandex Cloud API (zones, clouds, folders, subnets, VMs)
2. Creates/updates NetBox infrastructure (sites, cluster type, clusters, prefixes)
3. Syncs VMs with resources, interfaces, and IP addresses
4. Cleans up orphaned objects no longer present in Yandex Cloud

All synced objects are tagged with `synced-from-yc` for easy identification.

### Comparison Mode (Web UI)

1. Fetches VMs from configured cloud providers (Yandex Cloud, vCloud Director)
2. Fetches VMs from NetBox
3. Fetches hosts from Zabbix
4. Matches VMs by name (primary) and IP address (secondary fallback)
5. Identifies discrepancies: VMs missing from any system
6. Displays results in an interactive web dashboard

## License

MIT License - see [LICENSE](LICENSE) for details.

## Author

[vlkuz-dev](https://github.com/vlkuz-dev)
