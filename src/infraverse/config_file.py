"""YAML configuration file parser for Infraverse multi-tenant setup."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

import yaml

SUPPORTED_PROVIDERS = {"yandex_cloud", "vcloud"}
_ACCOUNT_KNOWN_KEYS = {"name", "provider"}
_ENV_VAR_PATTERN = re.compile(r"\$\{([^}]+)\}")


@dataclass
class CloudAccountConfig:
    name: str
    provider: str
    credentials: dict[str, str] = field(default_factory=dict)


@dataclass
class TenantConfig:
    name: str
    description: str | None = None
    cloud_accounts: list[CloudAccountConfig] = field(default_factory=list)


@dataclass
class MonitoringConfig:
    zabbix_url: str
    zabbix_username: str
    zabbix_password: str


@dataclass
class MonitoringExclusionRule:
    name_pattern: str | None = None
    status: str | None = None
    reason: str = ""


@dataclass
class OidcConfig:
    provider_url: str
    client_id: str
    client_secret: str
    required_role: str
    session_secret: str | None = None


@dataclass
class NetBoxConfig:
    url: str
    token: str


@dataclass
class ExternalLinksConfig:
    yc_console_url: str | None = None
    zabbix_host_url: str | None = None
    netbox_vm_url: str | None = None


@dataclass
class TimezoneConfig:
    offset_hours: int = 0
    label: str | None = None

    @property
    def resolved_label(self) -> str:
        if self.label:
            return self.label
        if self.offset_hours:
            return f"UTC{self.offset_hours:+d}"
        return "UTC"


@dataclass
class InfraverseConfig:
    tenants: dict[str, TenantConfig] = field(default_factory=dict)
    monitoring: MonitoringConfig | None = None
    oidc: OidcConfig | None = None
    monitoring_exclusions: list[MonitoringExclusionRule] = field(default_factory=list)
    database_url: str = "sqlite:///infraverse.db"
    netbox: NetBoxConfig | None = None
    sync_interval_minutes: int = 0
    external_links: ExternalLinksConfig | None = None
    log_level: str = "INFO"
    timezone: TimezoneConfig | None = None

    @property
    def oidc_configured(self) -> bool:
        return self.oidc is not None

    @property
    def monitoring_configured(self) -> bool:
        return self.monitoring is not None

    @property
    def netbox_configured(self) -> bool:
        return self.netbox is not None


def _expand_env_vars(value: str) -> str:
    """Replace ${VAR} references with environment variable values."""

    def _replace(match: re.Match) -> str:
        var_name = match.group(1)
        val = os.environ.get(var_name)
        if val is None:
            raise ValueError(
                f"Environment variable '{var_name}' referenced in config is not set"
            )
        return val

    return _ENV_VAR_PATTERN.sub(_replace, value)


def _expand_recursive(obj):
    """Recursively expand env vars in all string values."""
    if isinstance(obj, str):
        return _expand_env_vars(obj)
    if isinstance(obj, dict):
        return {k: _expand_recursive(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand_recursive(item) for item in obj]
    return obj


def _parse_cloud_account(raw: dict, tenant_name: str) -> CloudAccountConfig:
    if "name" not in raw:
        raise ValueError(
            f"Cloud account in tenant '{tenant_name}' is missing required field 'name'"
        )
    if "provider" not in raw:
        raise ValueError(
            f"Cloud account '{raw['name']}' in tenant '{tenant_name}' "
            f"is missing required field 'provider'"
        )
    provider = raw["provider"]
    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError(
            f"Unsupported provider '{provider}' in account '{raw['name']}' "
            f"(tenant '{tenant_name}'). Supported: {sorted(SUPPORTED_PROVIDERS)}"
        )
    credentials = {k: v for k, v in raw.items() if k not in _ACCOUNT_KNOWN_KEYS}
    return CloudAccountConfig(
        name=raw["name"],
        provider=provider,
        credentials=credentials,
    )


def _parse_tenant(name: str, raw: dict) -> TenantConfig:
    accounts_raw = raw.get("cloud_accounts")
    if not accounts_raw:
        raise ValueError(
            f"Tenant '{name}' must have at least one cloud_account"
        )

    accounts = [_parse_cloud_account(acc, name) for acc in accounts_raw]

    seen_names = set()
    for acc in accounts:
        if acc.name in seen_names:
            raise ValueError(
                f"Duplicate cloud account name '{acc.name}' in tenant '{name}'"
            )
        seen_names.add(acc.name)

    return TenantConfig(
        name=name,
        description=raw.get("description"),
        cloud_accounts=accounts,
    )


_MONITORING_REQUIRED_FIELDS = ("url", "username", "password")


def _parse_monitoring(raw: dict) -> MonitoringConfig:
    zabbix = raw.get("zabbix")
    if not zabbix or not isinstance(zabbix, dict):
        raise ValueError(
            "Monitoring config must have a 'zabbix' section"
        )
    for field_name in _MONITORING_REQUIRED_FIELDS:
        if field_name not in zabbix:
            raise ValueError(
                f"Monitoring zabbix config is missing required field '{field_name}'"
            )
    return MonitoringConfig(
        zabbix_url=zabbix["url"],
        zabbix_username=zabbix["username"],
        zabbix_password=zabbix["password"],
    )


_OIDC_REQUIRED_FIELDS = ("provider_url", "client_id", "client_secret", "required_role")


def _parse_oidc(raw: dict) -> OidcConfig:
    for field_name in _OIDC_REQUIRED_FIELDS:
        if field_name not in raw:
            raise ValueError(
                f"OIDC config is missing required field '{field_name}'"
            )
    return OidcConfig(
        provider_url=raw["provider_url"],
        client_id=raw["client_id"],
        client_secret=raw["client_secret"],
        required_role=raw["required_role"],
        session_secret=raw.get("session_secret"),
    )


def _parse_netbox(raw: dict) -> NetBoxConfig:
    if "url" not in raw:
        raise ValueError("NetBox config is missing required field 'url'")
    if "token" not in raw:
        raise ValueError("NetBox config is missing required field 'token'")
    return NetBoxConfig(url=raw["url"], token=raw["token"])


def _parse_external_links(raw: dict) -> ExternalLinksConfig:
    return ExternalLinksConfig(
        yc_console_url=raw.get("yc_console_url"),
        zabbix_host_url=raw.get("zabbix_host_url"),
        netbox_vm_url=raw.get("netbox_vm_url"),
    )


def _parse_timezone(raw: dict) -> TimezoneConfig:
    offset = raw.get("offset_hours", 0)
    if not isinstance(offset, int):
        raise ValueError(
            f"timezone.offset_hours must be an integer, got {type(offset).__name__}"
        )
    return TimezoneConfig(
        offset_hours=offset,
        label=raw.get("label"),
    )


def _parse_monitoring_exclusions(raw: list[dict]) -> list[MonitoringExclusionRule]:
    rules: list[MonitoringExclusionRule] = []
    for i, entry in enumerate(raw):
        name_pattern = entry.get("name_pattern")
        status = entry.get("status")
        reason = entry.get("reason", "")

        if not name_pattern and not status:
            raise ValueError(
                f"Monitoring exclusion rule #{i + 1} must have at least "
                f"'name_pattern' or 'status'"
            )
        if not reason:
            raise ValueError(
                f"Monitoring exclusion rule #{i + 1} is missing required field 'reason'"
            )
        rules.append(MonitoringExclusionRule(
            name_pattern=name_pattern,
            status=status,
            reason=reason,
        ))
    return rules


def load_config(path: str) -> InfraverseConfig:
    """Load and parse YAML config file, expanding ${VAR} env var references.

    Raises:
        FileNotFoundError: If config file does not exist.
        ValueError: If config is invalid (missing tenants, bad provider, etc.).
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path) as f:
        raw = yaml.safe_load(f)

    if not raw or not isinstance(raw, dict):
        raise ValueError("Config file is empty or invalid")

    # Expand env vars in all string values before parsing
    raw = _expand_recursive(raw)

    tenants_raw = raw.get("tenants")
    if not tenants_raw:
        raise ValueError("Config must define at least one tenant under 'tenants' key")

    tenants = {name: _parse_tenant(name, data) for name, data in tenants_raw.items()}

    monitoring = None
    if "monitoring" in raw:
        monitoring = _parse_monitoring(raw["monitoring"])

    oidc = None
    if "oidc" in raw:
        oidc = _parse_oidc(raw["oidc"])

    monitoring_exclusions: list[MonitoringExclusionRule] = []
    if "monitoring_exclusions" in raw:
        monitoring_exclusions = _parse_monitoring_exclusions(raw["monitoring_exclusions"])

    database_url = raw.get("database_url", "sqlite:///infraverse.db")

    netbox = None
    if "netbox" in raw:
        netbox = _parse_netbox(raw["netbox"])

    sync_interval_minutes = raw.get("sync_interval_minutes", 0)
    if not isinstance(sync_interval_minutes, int) or sync_interval_minutes < 0:
        raise ValueError(
            f"sync_interval_minutes must be a non-negative integer, got {sync_interval_minutes!r}"
        )

    external_links = None
    if "external_links" in raw:
        external_links = _parse_external_links(raw["external_links"])

    log_level = raw.get("log_level", "INFO")

    timezone = None
    if "timezone" in raw:
        timezone = _parse_timezone(raw["timezone"])

    return InfraverseConfig(
        tenants=tenants,
        monitoring=monitoring,
        oidc=oidc,
        monitoring_exclusions=monitoring_exclusions,
        database_url=database_url,
        netbox=netbox,
        sync_interval_minutes=sync_interval_minutes,
        external_links=external_links,
        log_level=log_level,
        timezone=timezone,
    )
