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
class OidcConfig:
    provider_url: str
    client_id: str
    client_secret: str
    required_role: str


@dataclass
class InfraverseConfig:
    tenants: dict[str, TenantConfig] = field(default_factory=dict)
    monitoring: MonitoringConfig | None = None
    oidc: OidcConfig | None = None

    @property
    def oidc_configured(self) -> bool:
        return self.oidc is not None

    @property
    def monitoring_configured(self) -> bool:
        return self.monitoring is not None


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


def _parse_monitoring(raw: dict) -> MonitoringConfig:
    zabbix = raw.get("zabbix", {})
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
    )


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

    return InfraverseConfig(
        tenants=tenants,
        monitoring=monitoring,
        oidc=oidc,
    )
