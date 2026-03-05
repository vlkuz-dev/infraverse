# Multi-Cloud Comparison: vCloud Director + Zabbix + Frontend

## Overview
Расширение netbox-yandexcloud-sync из CLI-инструмента синхронизации Yandex Cloud в полноценный сервис сравнения инфраструктуры:
- Добавление vCloud Director как второго облачного провайдера
- Интеграция с Zabbix для проверки наличия ВМ в мониторинге
- Движок сравнения: облако vs NetBox vs Zabbix
- Веб-интерфейс на FastAPI + Jinja2 + HTMX для просмотра и управления

**Проблема:** Сейчас нет единой картины — ВМ могут быть в облаке, но не в NetBox и не в мониторинге, или наоборот. Ручная проверка трёх систем трудоёмка и ненадёжна.

**Решение:** Единый сервис, который автоматически собирает данные из всех источников и показывает расхождения.

## Context (from discovery)
- **Текущий проект:** ~2500 строк Python, CLI-only, YC → NetBox синхронизация
- **Клиенты:** `clients/yandex.py` (httpx), `clients/netbox.py` (pynetbox)
- **Sync:** `sync/engine.py` → `sync/infrastructure.py` → `sync/batch.py` → `sync/cleanup.py`
- **Нет:** фронтенда, БД, веб-API, мониторинга, абстракции провайдеров
- **Зависимости:** httpx, pynetbox, python-dotenv, pytest, ruff
- **Python 3.10+**, Docker-ready

## Development Approach
- **Testing approach**: Regular (code first, then tests)
- Complete each task fully before moving to the next
- Make small, focused changes
- **CRITICAL: every task MUST include new/updated tests** for code changes in that task
- **CRITICAL: all tests must pass before starting next task**
- **CRITICAL: update this plan file when scope changes during implementation**
- Run tests after each change
- Maintain backward compatibility — существующая CLI-синхронизация должна продолжать работать

## Testing Strategy
- **Unit tests**: required for every task
- **Существующие ~300 тестов** должны проходить на каждом этапе
- Новые клиенты тестируются с моками (как существующие тесты YC/NetBox)
- Web-слой: тестирование через `httpx.AsyncClient` (TestClient FastAPI)

## Progress Tracking
- Mark completed items with `[x]` immediately when done
- Add newly discovered tasks with + prefix
- Document issues/blockers with ! prefix
- Update plan if implementation deviates from original scope

## Target Architecture

```
src/netbox_sync/
  clients/
    base.py              # CloudProvider Protocol + VMInfo dataclass
    yandex.py            # YandexCloudClient (refactored to implement CloudProvider)
    vcloud.py            # VCloudDirectorClient (new, implements CloudProvider)
    netbox.py            # NetBoxClient (existing, extended with read methods)
    zabbix.py            # ZabbixClient (new)
  sync/                  # Existing sync logic (unchanged)
    engine.py
    infrastructure.py
    batch.py
    cleanup.py
    vms.py
  comparison/
    engine.py            # ComparisonEngine: cloud vs NetBox vs Zabbix
    models.py            # ComparisonResult, VMState, Discrepancy dataclasses
  web/
    app.py               # FastAPI application factory
    routes.py            # Web routes (dashboard, comparison, settings)
    templates/           # Jinja2 templates
      base.html
      dashboard.html
      comparison.html
    static/
      style.css
  config.py              # Extended config (vCD, Zabbix credentials)
  cli.py                 # Extended CLI (add `serve` command)
```

## Implementation Steps

### Task 1: Cloud Provider abstraction and VMInfo model
- [x] create `src/netbox_sync/clients/base.py` with `CloudProvider` Protocol defining `fetch_vms() -> list[VMInfo]` and `get_provider_name() -> str`
- [x] define `VMInfo` dataclass: `name`, `id`, `status`, `ip_addresses: list[str]`, `vcpus`, `memory_mb`, `provider`, `cloud_name`, `folder_name`
- [x] write tests for VMInfo dataclass creation and field validation
- [x] run tests — must pass before next task

### Task 2: Refactor YandexCloudClient to implement CloudProvider
- [x] add `fetch_vms() -> list[VMInfo]` method to `YandexCloudClient` that wraps existing `fetch_all_data()` and converts YC VM dicts to `VMInfo` objects
- [x] add `get_provider_name() -> str` returning `"yandex-cloud"`
- [x] ensure existing sync logic (`engine.py`, `batch.py`) continues to use `fetch_all_data()` — no breaking changes
- [x] write tests for `fetch_vms()` conversion: verify VMInfo fields from mock YC data
- [x] verify all existing ~300 tests still pass
- [x] run tests — must pass before next task

### Task 3: Add VCloudDirectorClient
- [x] create `src/netbox_sync/clients/vcloud.py` with `VCloudDirectorClient` class implementing `CloudProvider`
- [x] implement authentication: vCD API session login (`POST /api/sessions` or `/cloudapi/1.0.0/sessions/provider`)
- [x] implement `fetch_vms()`: list all VMs across all vDCs/orgs via vCD API (`/api/query?type=vm` or `/cloudapi/1.0.0/vms`)
- [x] convert vCD VM data to `VMInfo`: name, id (href/urn), status mapping (POWERED_ON→active, etc.), IPs, resources
- [x] implement `get_provider_name() -> str` returning `"vcloud-director"`
- [x] handle pagination for large vCD deployments
- [x] write tests with mocked HTTP responses for auth flow
- [x] write tests with mocked HTTP responses for VM listing (single page, paginated, empty)
- [x] write tests for vCD status → VMInfo status mapping
- [x] run tests — must pass before next task

### Task 4: Add ZabbixClient
- [x] create `src/netbox_sync/clients/zabbix.py` with `ZabbixClient` class
- [x] implement Zabbix JSON-RPC authentication (`user.login`)
- [x] implement `fetch_hosts() -> list[ZabbixHost]` via `host.get` with relevant properties (name, status, interfaces/IPs, hostid)
- [x] define `ZabbixHost` dataclass: `name`, `hostid`, `status` (enabled/disabled), `ip_addresses: list[str]`
- [x] handle Zabbix API pagination and error responses
- [x] write tests with mocked JSON-RPC responses for auth
- [x] write tests for host listing (active, disabled, no hosts)
- [x] write tests for error handling (auth failure, API error)
- [x] run tests — must pass before next task

### Task 5: Extend configuration for vCloud Director and Zabbix
- [x] add new env vars to `config.py`: `VCD_URL`, `VCD_USER`, `VCD_PASSWORD`, `VCD_ORG` (all optional)
- [x] add new env vars: `ZABBIX_URL`, `ZABBIX_USER`, `ZABBIX_PASSWORD` (all optional)
- [x] make these optional — service starts even if only YC is configured (backward compatible)
- [x] update `.env.example` with new variables and comments
- [x] write tests for config with all providers, with only YC, with partial configs
- [x] run tests — must pass before next task

### Task 6: Build ComparisonEngine
- [x] create `src/netbox_sync/comparison/models.py` with dataclasses: `VMState` (vm_name, in_cloud: bool, in_netbox: bool, in_monitoring: bool, cloud_provider: str|None, discrepancies: list), `ComparisonResult` (all_vms: list[VMState], summary: dict)
- [x] create `src/netbox_sync/comparison/engine.py` with `ComparisonEngine` class
- [x] implement `compare()` method: takes cloud VMs (from all providers), NetBox VMs, Zabbix hosts → returns `ComparisonResult`
- [x] matching logic: match by VM name (primary) and IP address (secondary fallback)
- [x] detect discrepancies: "in cloud but not in NetBox", "in NetBox but not in cloud", "in cloud but not in monitoring", "in monitoring but not in cloud", "in NetBox but not in monitoring"
- [x] write tests for comparison with all VMs matching across all three systems
- [x] write tests for VMs missing from one system
- [x] write tests for VMs with IP-based matching when names differ
- [x] write tests for empty data from one or more sources
- [x] run tests — must pass before next task

### Task 7: Extend NetBoxClient with read methods for comparison
- [x] add `fetch_all_vms() -> list[VMInfo]` method to `NetBoxClient` that returns all VMs (or tagged VMs) as VMInfo objects
- [x] reuse existing pynetbox `.filter()` / `.all()` patterns
- [x] write tests for `fetch_all_vms()` with mock pynetbox records
- [x] run tests — must pass before next task

### Task 8: Add FastAPI web application
- [ ] add `fastapi`, `jinja2`, `uvicorn` to project dependencies in `pyproject.toml`
- [ ] create `src/netbox_sync/web/app.py` with FastAPI application factory (`create_app()`)
- [ ] create `src/netbox_sync/web/templates/base.html` — base layout (minimal CSS, HTMX CDN)
- [ ] create `src/netbox_sync/web/templates/dashboard.html` — main page showing provider status and summary stats
- [ ] create `src/netbox_sync/web/routes.py` with `GET /` route rendering dashboard
- [ ] write tests: app creation, dashboard route returns 200, template renders
- [ ] run tests — must pass before next task

### Task 9: Add comparison view to frontend
- [ ] add `GET /comparison` route that runs ComparisonEngine and renders results
- [ ] create `src/netbox_sync/web/templates/comparison.html` — table of all VMs with status columns (cloud, NetBox, Zabbix) and color-coded discrepancies
- [ ] add HTMX-powered refresh button to re-run comparison without full page reload
- [ ] add filtering: by provider, by status (all/only discrepancies), by name search
- [ ] write tests for comparison route with mocked data sources
- [ ] write tests for filtering parameters
- [ ] run tests — must pass before next task

### Task 10: Add CLI `serve` command
- [ ] extend `cli.py` argparse with `serve` subcommand: `netbox-sync serve --host 0.0.0.0 --port 8000`
- [ ] keep existing default behavior (sync) when no subcommand given — backward compatible
- [ ] `serve` starts uvicorn with the FastAPI app
- [ ] write tests for CLI argument parsing with `serve` subcommand
- [ ] write tests for backward compatibility (no subcommand = sync mode)
- [ ] run tests — must pass before next task

### Task 11: Verify acceptance criteria
- [ ] verify vCloud Director client can list VMs (with mocked API)
- [ ] verify Zabbix client can list hosts (with mocked API)
- [ ] verify comparison engine correctly identifies discrepancies across all three sources
- [ ] verify web dashboard renders and shows comparison data
- [ ] verify existing CLI sync mode still works unchanged
- [ ] run full test suite (unit tests)
- [ ] run linter (`ruff check src/ tests/`) — all issues must be fixed

### Task 12: [Final] Update documentation
- [ ] update README.md with new features: vCloud Director, Zabbix, web UI
- [ ] add configuration section for new env vars
- [ ] add usage examples for `serve` command
- [ ] update Dockerfile if needed (expose port, add serve as default cmd option)

## Technical Details

### Cloud Provider Protocol
```python
from typing import Protocol
from dataclasses import dataclass

@dataclass
class VMInfo:
    name: str
    id: str
    status: str  # "active" | "offline" | "unknown"
    ip_addresses: list[str]
    vcpus: int
    memory_mb: int
    provider: str
    cloud_name: str
    folder_name: str

class CloudProvider(Protocol):
    def fetch_vms(self) -> list[VMInfo]: ...
    def get_provider_name(self) -> str: ...
```

### Comparison Matching Strategy
1. **Primary match:** Exact VM name (case-insensitive)
2. **Secondary match:** Shared IP address (when names differ between systems)
3. **Result:** Per-VM state across all three systems with list of discrepancies

### vCloud Director API
- Auth: `POST /api/sessions` with Basic Auth → `x-vcloud-authorization` token
- VMs: `GET /api/query?type=vm&pageSize=128&page=N` → XML/JSON with VM records
- Status codes: 4=POWERED_ON, 8=POWERED_OFF, 3=SUSPENDED → map to active/offline
- Using `httpx` (same as YC client) for HTTP requests

### Zabbix API
- JSON-RPC 2.0 over HTTP: `POST /api_jsonrpc.php`
- Auth: `user.login` → auth token used in subsequent requests
- Hosts: `host.get` with `output: [host, name, status]`, `selectInterfaces: [ip]`
- Status: 0=enabled (monitored), 1=disabled → map to active/offline

### Frontend Stack
- **FastAPI** — async web framework, API + template rendering
- **Jinja2** — server-side templates
- **HTMX** — dynamic updates without JS framework (comparison refresh, filtering)
- **Minimal CSS** — simple, functional styling (no heavy frameworks)

## Post-Completion

**Manual verification:**
- Test with real vCloud Director instance (credentials needed)
- Test with real Zabbix instance (credentials needed)
- Verify comparison accuracy with known discrepancies
- Check web UI usability on different screen sizes

**Deployment updates:**
- Update Docker image to optionally expose port 8000
- Add `serve` mode documentation to deployment guides
- Consider adding docker-compose.yml for web mode
