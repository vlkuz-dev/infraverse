"""Tests for infraverse.config_file module — YAML config file parser."""

import pytest
import yaml

from infraverse.config_file import (
    CloudAccountConfig,
    ExternalLinksConfig,
    InfraverseConfig,
    MonitoringConfig,
    MonitoringExclusionRule,
    NetBoxConfig,
    OidcConfig,
    TenantConfig,
    TimezoneConfig,
    load_config,
)


# ── helpers ──────────────────────────────────────────────────────────


def _write_yaml(tmp_path, data: dict, filename: str = "config.yaml") -> str:
    path = tmp_path / filename
    path.write_text(yaml.dump(data, default_flow_style=False))
    return str(path)


FULL_CONFIG = {
    "tenants": {
        "acme-corp": {
            "description": "ACME Corporation",
            "cloud_accounts": [
                {
                    "name": "acme-yandex-prod",
                    "provider": "yandex_cloud",
                    "token": "yc-token-acme",
                },
                {
                    "name": "acme-vcloud",
                    "provider": "vcloud",
                    "url": "https://vcd.example.com",
                    "username": "admin",
                    "password": "vcd-pass",
                    "org": "acme-org",
                },
            ],
        },
        "beta-inc": {
            "description": "Beta Inc",
            "cloud_accounts": [
                {
                    "name": "beta-yandex",
                    "provider": "yandex_cloud",
                    "token": "yc-token-beta",
                },
            ],
        },
    },
    "monitoring": {
        "zabbix": {
            "url": "https://zabbix.example.com/api_jsonrpc.php",
            "username": "api_user",
            "password": "zabbix-pass",
        },
    },
    "oidc": {
        "provider_url": "https://keycloak.example.com/realms/infraverse",
        "client_id": "infraverse",
        "client_secret": "oidc-secret",
        "required_role": "infraverse-admin",
    },
    "database_url": "sqlite:///custom.db",
    "netbox": {
        "url": "https://netbox.example.com/api",
        "token": "nb-token-123",
    },
    "sync_interval_minutes": 30,
    "external_links": {
        "yc_console_url": "https://console.yandex.cloud/folders/{folder_id}",
        "zabbix_host_url": "{zabbix_url}/hosts.php?hostid={host_id}",
        "netbox_vm_url": "{netbox_url}/vms/{vm_id}/",
    },
    "log_level": "DEBUG",
    "timezone": {
        "offset_hours": 3,
        "label": "MSK",
    },
}

MINIMAL_CONFIG = {
    "tenants": {
        "single": {
            "cloud_accounts": [
                {
                    "name": "my-yc",
                    "provider": "yandex_cloud",
                    "token": "tok",
                },
            ],
        },
    },
}


# ── load_config: valid config ───────────────────────────────────────


class TestLoadConfigValid:
    def test_loads_full_config(self, tmp_path):
        path = _write_yaml(tmp_path, FULL_CONFIG)
        cfg = load_config(path)

        assert isinstance(cfg, InfraverseConfig)
        assert len(cfg.tenants) == 2
        assert "acme-corp" in cfg.tenants
        assert "beta-inc" in cfg.tenants
        assert cfg.database_url == "sqlite:///custom.db"
        assert cfg.netbox is not None
        assert cfg.netbox.url == "https://netbox.example.com/api"
        assert cfg.netbox.token == "nb-token-123"
        assert cfg.sync_interval_minutes == 30
        assert cfg.external_links is not None
        assert cfg.log_level == "DEBUG"
        assert cfg.timezone is not None
        assert cfg.timezone.offset_hours == 3
        assert cfg.timezone.label == "MSK"

    def test_tenant_fields(self, tmp_path):
        path = _write_yaml(tmp_path, FULL_CONFIG)
        cfg = load_config(path)
        acme = cfg.tenants["acme-corp"]

        assert isinstance(acme, TenantConfig)
        assert acme.name == "acme-corp"
        assert acme.description == "ACME Corporation"
        assert len(acme.cloud_accounts) == 2

    def test_cloud_account_yandex(self, tmp_path):
        path = _write_yaml(tmp_path, FULL_CONFIG)
        cfg = load_config(path)
        acme = cfg.tenants["acme-corp"]
        yc = acme.cloud_accounts[0]

        assert isinstance(yc, CloudAccountConfig)
        assert yc.name == "acme-yandex-prod"
        assert yc.provider == "yandex_cloud"
        assert yc.credentials == {"token": "yc-token-acme"}

    def test_cloud_account_vcloud(self, tmp_path):
        path = _write_yaml(tmp_path, FULL_CONFIG)
        cfg = load_config(path)
        acme = cfg.tenants["acme-corp"]
        vcd = acme.cloud_accounts[1]

        assert vcd.name == "acme-vcloud"
        assert vcd.provider == "vcloud"
        assert vcd.credentials == {
            "url": "https://vcd.example.com",
            "username": "admin",
            "password": "vcd-pass",
            "org": "acme-org",
        }

    def test_monitoring_config(self, tmp_path):
        path = _write_yaml(tmp_path, FULL_CONFIG)
        cfg = load_config(path)

        assert cfg.monitoring is not None
        assert isinstance(cfg.monitoring, MonitoringConfig)
        assert cfg.monitoring.zabbix_url == "https://zabbix.example.com/api_jsonrpc.php"
        assert cfg.monitoring.zabbix_username == "api_user"
        assert cfg.monitoring.zabbix_password == "zabbix-pass"

    def test_oidc_config(self, tmp_path):
        path = _write_yaml(tmp_path, FULL_CONFIG)
        cfg = load_config(path)

        assert cfg.oidc is not None
        assert isinstance(cfg.oidc, OidcConfig)
        assert cfg.oidc.provider_url == "https://keycloak.example.com/realms/infraverse"
        assert cfg.oidc.client_id == "infraverse"
        assert cfg.oidc.client_secret == "oidc-secret"
        assert cfg.oidc.required_role == "infraverse-admin"

    def test_minimal_config(self, tmp_path):
        path = _write_yaml(tmp_path, MINIMAL_CONFIG)
        cfg = load_config(path)

        assert len(cfg.tenants) == 1
        assert cfg.monitoring is None
        assert cfg.oidc is None
        tenant = cfg.tenants["single"]
        assert tenant.description is None
        assert len(tenant.cloud_accounts) == 1


class TestLoadConfigMissingFile:
    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_config(str(tmp_path / "nonexistent.yaml"))


# ── env var expansion ───────────────────────────────────────────────


class TestEnvVarExpansion:
    def test_expands_env_vars_in_token(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MY_YC_TOKEN", "expanded-token-value")
        data = {
            "tenants": {
                "t1": {
                    "cloud_accounts": [
                        {
                            "name": "acc1",
                            "provider": "yandex_cloud",
                            "token": "${MY_YC_TOKEN}",
                        },
                    ],
                },
            },
        }
        path = _write_yaml(tmp_path, data)
        cfg = load_config(path)

        acc = cfg.tenants["t1"].cloud_accounts[0]
        assert acc.credentials["token"] == "expanded-token-value"

    def test_expands_env_vars_in_monitoring(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ZABBIX_PASS", "secret-zabbix")
        data = {
            "tenants": {
                "t1": {
                    "cloud_accounts": [
                        {"name": "a", "provider": "yandex_cloud", "token": "tok"},
                    ],
                },
            },
            "monitoring": {
                "zabbix": {
                    "url": "https://zabbix.local",
                    "username": "admin",
                    "password": "${ZABBIX_PASS}",
                },
            },
        }
        path = _write_yaml(tmp_path, data)
        cfg = load_config(path)
        assert cfg.monitoring.zabbix_password == "secret-zabbix"

    def test_expands_env_vars_in_oidc(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OIDC_SECRET", "my-oidc-secret")
        data = {
            "tenants": {
                "t1": {
                    "cloud_accounts": [
                        {"name": "a", "provider": "yandex_cloud", "token": "tok"},
                    ],
                },
            },
            "oidc": {
                "provider_url": "https://idp.example.com",
                "client_id": "app",
                "client_secret": "${OIDC_SECRET}",
                "required_role": "admin",
            },
        }
        path = _write_yaml(tmp_path, data)
        cfg = load_config(path)
        assert cfg.oidc.client_secret == "my-oidc-secret"

    def test_missing_env_var_raises(self, tmp_path, monkeypatch):
        monkeypatch.delenv("NONEXISTENT_VAR_XYZ", raising=False)
        data = {
            "tenants": {
                "t1": {
                    "cloud_accounts": [
                        {
                            "name": "acc1",
                            "provider": "yandex_cloud",
                            "token": "${NONEXISTENT_VAR_XYZ}",
                        },
                    ],
                },
            },
        }
        path = _write_yaml(tmp_path, data)
        with pytest.raises(ValueError, match="NONEXISTENT_VAR_XYZ"):
            load_config(path)

    def test_multiple_env_vars_in_same_string(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOST", "zabbix.local")
        monkeypatch.setenv("PORT", "8080")
        data = {
            "tenants": {
                "t1": {
                    "cloud_accounts": [
                        {"name": "a", "provider": "yandex_cloud", "token": "tok"},
                    ],
                },
            },
            "monitoring": {
                "zabbix": {
                    "url": "https://${HOST}:${PORT}/api",
                    "username": "admin",
                    "password": "pass",
                },
            },
        }
        path = _write_yaml(tmp_path, data)
        cfg = load_config(path)
        assert cfg.monitoring.zabbix_url == "https://zabbix.local:8080/api"

    def test_no_expansion_without_dollar_brace(self, tmp_path):
        data = {
            "tenants": {
                "t1": {
                    "cloud_accounts": [
                        {"name": "a", "provider": "yandex_cloud", "token": "plain-token"},
                    ],
                },
            },
        }
        path = _write_yaml(tmp_path, data)
        cfg = load_config(path)
        assert cfg.tenants["t1"].cloud_accounts[0].credentials["token"] == "plain-token"


# ── edge cases ──────────────────────────────────────────────────────


class TestEdgeCases:
    def test_empty_tenants_raises(self, tmp_path):
        data = {"tenants": {}}
        path = _write_yaml(tmp_path, data)
        with pytest.raises(ValueError, match="[Tt]enant"):
            load_config(path)

    def test_missing_tenants_key_raises(self, tmp_path):
        data = {"monitoring": {"zabbix": {"url": "x", "username": "u", "password": "p"}}}
        path = _write_yaml(tmp_path, data)
        with pytest.raises(ValueError, match="[Tt]enant"):
            load_config(path)

    def test_empty_cloud_accounts_raises(self, tmp_path):
        data = {
            "tenants": {
                "t1": {
                    "cloud_accounts": [],
                },
            },
        }
        path = _write_yaml(tmp_path, data)
        with pytest.raises(ValueError, match="cloud.account"):
            load_config(path)

    def test_missing_cloud_accounts_raises(self, tmp_path):
        data = {
            "tenants": {
                "t1": {
                    "description": "No accounts",
                },
            },
        }
        path = _write_yaml(tmp_path, data)
        with pytest.raises(ValueError, match="cloud.account"):
            load_config(path)

    def test_unknown_provider_type_raises(self, tmp_path):
        data = {
            "tenants": {
                "t1": {
                    "cloud_accounts": [
                        {"name": "a", "provider": "unknown_cloud", "token": "tok"},
                    ],
                },
            },
        }
        path = _write_yaml(tmp_path, data)
        with pytest.raises(ValueError, match="unknown_cloud"):
            load_config(path)

    def test_duplicate_account_names_across_tenants_ok(self, tmp_path):
        data = {
            "tenants": {
                "t1": {
                    "cloud_accounts": [
                        {"name": "shared-name", "provider": "yandex_cloud", "token": "t1"},
                    ],
                },
                "t2": {
                    "cloud_accounts": [
                        {"name": "shared-name", "provider": "yandex_cloud", "token": "t2"},
                    ],
                },
            },
        }
        path = _write_yaml(tmp_path, data)
        cfg = load_config(path)
        assert len(cfg.tenants) == 2

    def test_duplicate_account_names_within_tenant_raises(self, tmp_path):
        data = {
            "tenants": {
                "t1": {
                    "cloud_accounts": [
                        {"name": "dup", "provider": "yandex_cloud", "token": "t1"},
                        {"name": "dup", "provider": "yandex_cloud", "token": "t2"},
                    ],
                },
            },
        }
        path = _write_yaml(tmp_path, data)
        with pytest.raises(ValueError, match="[Dd]uplicate.*dup"):
            load_config(path)

    def test_missing_account_name_raises(self, tmp_path):
        data = {
            "tenants": {
                "t1": {
                    "cloud_accounts": [
                        {"provider": "yandex_cloud", "token": "tok"},
                    ],
                },
            },
        }
        path = _write_yaml(tmp_path, data)
        with pytest.raises(ValueError, match="name"):
            load_config(path)

    def test_missing_provider_raises(self, tmp_path):
        data = {
            "tenants": {
                "t1": {
                    "cloud_accounts": [
                        {"name": "acc1", "token": "tok"},
                    ],
                },
            },
        }
        path = _write_yaml(tmp_path, data)
        with pytest.raises(ValueError, match="provider"):
            load_config(path)

    def test_vcloud_provider_accepted(self, tmp_path):
        data = {
            "tenants": {
                "t1": {
                    "cloud_accounts": [
                        {
                            "name": "vcd",
                            "provider": "vcloud",
                            "url": "https://vcd.local",
                            "username": "admin",
                            "password": "pass",
                        },
                    ],
                },
            },
        }
        path = _write_yaml(tmp_path, data)
        cfg = load_config(path)
        acc = cfg.tenants["t1"].cloud_accounts[0]
        assert acc.provider == "vcloud"


# ── OIDC config validation ───────────────────────────────────────────


def _minimal_with_oidc(oidc_data):
    """Helper: minimal valid config with an oidc section."""
    return {
        "tenants": {
            "t1": {
                "cloud_accounts": [
                    {"name": "a", "provider": "yandex_cloud", "token": "tok"},
                ],
            },
        },
        "oidc": oidc_data,
    }


class TestOidcConfigParsing:
    def test_full_oidc_fields_parsed(self, tmp_path):
        data = _minimal_with_oidc({
            "provider_url": "https://idp.example.com/realms/test",
            "client_id": "my-app",
            "client_secret": "secret-123",
            "required_role": "app-admin",
        })
        path = _write_yaml(tmp_path, data)
        cfg = load_config(path)
        assert cfg.oidc.provider_url == "https://idp.example.com/realms/test"
        assert cfg.oidc.client_id == "my-app"
        assert cfg.oidc.client_secret == "secret-123"
        assert cfg.oidc.required_role == "app-admin"

    def test_missing_provider_url_raises(self, tmp_path):
        data = _minimal_with_oidc({
            "client_id": "app",
            "client_secret": "sec",
            "required_role": "admin",
        })
        path = _write_yaml(tmp_path, data)
        with pytest.raises(ValueError, match="provider_url"):
            load_config(path)

    def test_missing_client_id_raises(self, tmp_path):
        data = _minimal_with_oidc({
            "provider_url": "https://idp.example.com",
            "client_secret": "sec",
            "required_role": "admin",
        })
        path = _write_yaml(tmp_path, data)
        with pytest.raises(ValueError, match="client_id"):
            load_config(path)

    def test_missing_client_secret_raises(self, tmp_path):
        data = _minimal_with_oidc({
            "provider_url": "https://idp.example.com",
            "client_id": "app",
            "required_role": "admin",
        })
        path = _write_yaml(tmp_path, data)
        with pytest.raises(ValueError, match="client_secret"):
            load_config(path)

    def test_missing_required_role_raises(self, tmp_path):
        data = _minimal_with_oidc({
            "provider_url": "https://idp.example.com",
            "client_id": "app",
            "client_secret": "sec",
        })
        path = _write_yaml(tmp_path, data)
        with pytest.raises(ValueError, match="required_role"):
            load_config(path)

    def test_empty_oidc_section_raises(self, tmp_path):
        data = _minimal_with_oidc({})
        path = _write_yaml(tmp_path, data)
        with pytest.raises(ValueError, match="provider_url"):
            load_config(path)

    def test_no_oidc_section_returns_none(self, tmp_path):
        path = _write_yaml(tmp_path, MINIMAL_CONFIG)
        cfg = load_config(path)
        assert cfg.oidc is None


# ── dataclass properties ────────────────────────────────────────────


class TestInfraverseConfigProperties:
    def test_oidc_configured_true(self, tmp_path):
        path = _write_yaml(tmp_path, FULL_CONFIG)
        cfg = load_config(path)
        assert cfg.oidc_configured is True

    def test_oidc_configured_false(self, tmp_path):
        path = _write_yaml(tmp_path, MINIMAL_CONFIG)
        cfg = load_config(path)
        assert cfg.oidc_configured is False

    def test_monitoring_configured_true(self, tmp_path):
        path = _write_yaml(tmp_path, FULL_CONFIG)
        cfg = load_config(path)
        assert cfg.monitoring_configured is True

    def test_monitoring_configured_false(self, tmp_path):
        path = _write_yaml(tmp_path, MINIMAL_CONFIG)
        cfg = load_config(path)
        assert cfg.monitoring_configured is False

    def test_netbox_configured_true(self, tmp_path):
        path = _write_yaml(tmp_path, FULL_CONFIG)
        cfg = load_config(path)
        assert cfg.netbox_configured is True

    def test_netbox_configured_false(self, tmp_path):
        path = _write_yaml(tmp_path, MINIMAL_CONFIG)
        cfg = load_config(path)
        assert cfg.netbox_configured is False


# ── monitoring exclusion rules ──────────────────────────────────────


class TestMonitoringExclusionsParsing:
    def test_parse_valid_exclusion_rules(self, tmp_path):
        data = {
            **MINIMAL_CONFIG,
            "monitoring_exclusions": [
                {"name_pattern": "test-vm-*", "reason": "Test VMs excluded"},
            ],
        }
        path = _write_yaml(tmp_path, data)
        cfg = load_config(path)

        assert len(cfg.monitoring_exclusions) == 1
        rule = cfg.monitoring_exclusions[0]
        assert isinstance(rule, MonitoringExclusionRule)
        assert rule.name_pattern == "test-vm-*"
        assert rule.status is None
        assert rule.reason == "Test VMs excluded"

    def test_parse_status_only_rule(self, tmp_path):
        data = {
            **MINIMAL_CONFIG,
            "monitoring_exclusions": [
                {"status": "STOPPED", "reason": "Stopped VMs not monitored"},
            ],
        }
        path = _write_yaml(tmp_path, data)
        cfg = load_config(path)

        assert len(cfg.monitoring_exclusions) == 1
        rule = cfg.monitoring_exclusions[0]
        assert rule.name_pattern is None
        assert rule.status == "STOPPED"
        assert rule.reason == "Stopped VMs not monitored"

    def test_parse_both_fields(self, tmp_path):
        data = {
            **MINIMAL_CONFIG,
            "monitoring_exclusions": [
                {
                    "name_pattern": "dev-*",
                    "status": "STOPPED",
                    "reason": "Dev stopped VMs",
                },
            ],
        }
        path = _write_yaml(tmp_path, data)
        cfg = load_config(path)

        assert len(cfg.monitoring_exclusions) == 1
        rule = cfg.monitoring_exclusions[0]
        assert rule.name_pattern == "dev-*"
        assert rule.status == "STOPPED"
        assert rule.reason == "Dev stopped VMs"

    def test_parse_missing_reason_raises(self, tmp_path):
        data = {
            **MINIMAL_CONFIG,
            "monitoring_exclusions": [
                {"name_pattern": "test-*"},
            ],
        }
        path = _write_yaml(tmp_path, data)
        with pytest.raises(ValueError, match="reason"):
            load_config(path)

    def test_parse_missing_both_fields_raises(self, tmp_path):
        data = {
            **MINIMAL_CONFIG,
            "monitoring_exclusions": [
                {"reason": "No filter specified"},
            ],
        }
        path = _write_yaml(tmp_path, data)
        with pytest.raises(ValueError, match="name_pattern.*status|status.*name_pattern"):
            load_config(path)

    def test_parse_empty_reason_raises(self, tmp_path):
        data = {
            **MINIMAL_CONFIG,
            "monitoring_exclusions": [
                {"name_pattern": "test-*", "reason": ""},
            ],
        }
        path = _write_yaml(tmp_path, data)
        with pytest.raises(ValueError, match="reason"):
            load_config(path)

    def test_load_config_with_exclusions(self, tmp_path):
        data = {
            **FULL_CONFIG,
            "monitoring_exclusions": [
                {"name_pattern": "tmp-*", "reason": "Temporary VMs"},
                {"status": "STOPPED", "reason": "Stopped instances"},
            ],
        }
        path = _write_yaml(tmp_path, data)
        cfg = load_config(path)

        assert len(cfg.monitoring_exclusions) == 2
        assert cfg.monitoring_exclusions[0].name_pattern == "tmp-*"
        assert cfg.monitoring_exclusions[0].reason == "Temporary VMs"
        assert cfg.monitoring_exclusions[1].status == "STOPPED"
        assert cfg.monitoring_exclusions[1].reason == "Stopped instances"

    def test_load_config_without_exclusions(self, tmp_path):
        path = _write_yaml(tmp_path, MINIMAL_CONFIG)
        cfg = load_config(path)

        assert cfg.monitoring_exclusions == []

    def test_exclusion_env_var_expansion(self, tmp_path, monkeypatch):
        monkeypatch.setenv("EXCLUSION_REASON", "Expanded reason text")
        data = {
            **MINIMAL_CONFIG,
            "monitoring_exclusions": [
                {"name_pattern": "ci-*", "reason": "${EXCLUSION_REASON}"},
            ],
        }
        path = _write_yaml(tmp_path, data)
        cfg = load_config(path)

        assert cfg.monitoring_exclusions[0].reason == "Expanded reason text"


# ── database_url parsing ────────────────────────────────────────────


class TestDatabaseUrlParsing:
    def test_default_database_url(self, tmp_path):
        path = _write_yaml(tmp_path, MINIMAL_CONFIG)
        cfg = load_config(path)
        assert cfg.database_url == "sqlite:///infraverse.db"

    def test_custom_database_url(self, tmp_path):
        data = {**MINIMAL_CONFIG, "database_url": "postgresql://localhost/infraverse"}
        path = _write_yaml(tmp_path, data)
        cfg = load_config(path)
        assert cfg.database_url == "postgresql://localhost/infraverse"

    def test_database_url_env_expansion(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DB_URL", "sqlite:///expanded.db")
        data = {**MINIMAL_CONFIG, "database_url": "${DB_URL}"}
        path = _write_yaml(tmp_path, data)
        cfg = load_config(path)
        assert cfg.database_url == "sqlite:///expanded.db"


# ── netbox config parsing ──────────────────────────────────────────


class TestNetBoxConfigParsing:
    def test_full_netbox_config(self, tmp_path):
        data = {
            **MINIMAL_CONFIG,
            "netbox": {"url": "https://nb.example.com/api", "token": "tok-123"},
        }
        path = _write_yaml(tmp_path, data)
        cfg = load_config(path)
        assert isinstance(cfg.netbox, NetBoxConfig)
        assert cfg.netbox.url == "https://nb.example.com/api"
        assert cfg.netbox.token == "tok-123"

    def test_no_netbox_section(self, tmp_path):
        path = _write_yaml(tmp_path, MINIMAL_CONFIG)
        cfg = load_config(path)
        assert cfg.netbox is None

    def test_missing_url_raises(self, tmp_path):
        data = {**MINIMAL_CONFIG, "netbox": {"token": "tok"}}
        path = _write_yaml(tmp_path, data)
        with pytest.raises(ValueError, match="url"):
            load_config(path)

    def test_missing_token_raises(self, tmp_path):
        data = {**MINIMAL_CONFIG, "netbox": {"url": "https://nb.example.com"}}
        path = _write_yaml(tmp_path, data)
        with pytest.raises(ValueError, match="token"):
            load_config(path)

    def test_env_expansion(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NB_TOKEN", "secret-token")
        data = {
            **MINIMAL_CONFIG,
            "netbox": {"url": "https://nb.example.com/api", "token": "${NB_TOKEN}"},
        }
        path = _write_yaml(tmp_path, data)
        cfg = load_config(path)
        assert cfg.netbox.token == "secret-token"


# ── sync_interval_minutes parsing ──────────────────────────────────


class TestSyncIntervalParsing:
    def test_default_sync_interval(self, tmp_path):
        path = _write_yaml(tmp_path, MINIMAL_CONFIG)
        cfg = load_config(path)
        assert cfg.sync_interval_minutes == 0

    def test_custom_sync_interval(self, tmp_path):
        data = {**MINIMAL_CONFIG, "sync_interval_minutes": 15}
        path = _write_yaml(tmp_path, data)
        cfg = load_config(path)
        assert cfg.sync_interval_minutes == 15

    def test_negative_sync_interval_raises(self, tmp_path):
        data = {**MINIMAL_CONFIG, "sync_interval_minutes": -5}
        path = _write_yaml(tmp_path, data)
        with pytest.raises(ValueError, match="sync_interval_minutes"):
            load_config(path)


# ── external_links parsing ─────────────────────────────────────────


class TestExternalLinksParsing:
    def test_full_external_links(self, tmp_path):
        data = {
            **MINIMAL_CONFIG,
            "external_links": {
                "yc_console_url": "https://console.yandex.cloud/{folder_id}",
                "zabbix_host_url": "{zabbix_url}/hosts/{host_id}",
                "netbox_vm_url": "{netbox_url}/vms/{vm_id}/",
            },
        }
        path = _write_yaml(tmp_path, data)
        cfg = load_config(path)
        assert isinstance(cfg.external_links, ExternalLinksConfig)
        assert cfg.external_links.yc_console_url == "https://console.yandex.cloud/{folder_id}"
        assert cfg.external_links.zabbix_host_url == "{zabbix_url}/hosts/{host_id}"
        assert cfg.external_links.netbox_vm_url == "{netbox_url}/vms/{vm_id}/"

    def test_partial_external_links(self, tmp_path):
        data = {
            **MINIMAL_CONFIG,
            "external_links": {"yc_console_url": "https://example.com"},
        }
        path = _write_yaml(tmp_path, data)
        cfg = load_config(path)
        assert cfg.external_links.yc_console_url == "https://example.com"
        assert cfg.external_links.zabbix_host_url is None
        assert cfg.external_links.netbox_vm_url is None

    def test_no_external_links_section(self, tmp_path):
        path = _write_yaml(tmp_path, MINIMAL_CONFIG)
        cfg = load_config(path)
        assert cfg.external_links is None


# ── log_level parsing ──────────────────────────────────────────────


class TestLogLevelParsing:
    def test_default_log_level(self, tmp_path):
        path = _write_yaml(tmp_path, MINIMAL_CONFIG)
        cfg = load_config(path)
        assert cfg.log_level == "INFO"

    def test_custom_log_level(self, tmp_path):
        data = {**MINIMAL_CONFIG, "log_level": "WARNING"}
        path = _write_yaml(tmp_path, data)
        cfg = load_config(path)
        assert cfg.log_level == "WARNING"


# ── timezone parsing ───────────────────────────────────────────────


class TestTimezoneParsing:
    def test_full_timezone(self, tmp_path):
        data = {**MINIMAL_CONFIG, "timezone": {"offset_hours": 3, "label": "MSK"}}
        path = _write_yaml(tmp_path, data)
        cfg = load_config(path)
        assert isinstance(cfg.timezone, TimezoneConfig)
        assert cfg.timezone.offset_hours == 3
        assert cfg.timezone.label == "MSK"
        assert cfg.timezone.resolved_label == "MSK"

    def test_auto_label_from_offset(self, tmp_path):
        data = {**MINIMAL_CONFIG, "timezone": {"offset_hours": 5}}
        path = _write_yaml(tmp_path, data)
        cfg = load_config(path)
        assert cfg.timezone.label is None
        assert cfg.timezone.resolved_label == "UTC+5"

    def test_zero_offset_utc_label(self, tmp_path):
        data = {**MINIMAL_CONFIG, "timezone": {"offset_hours": 0}}
        path = _write_yaml(tmp_path, data)
        cfg = load_config(path)
        assert cfg.timezone.resolved_label == "UTC"

    def test_negative_offset(self, tmp_path):
        data = {**MINIMAL_CONFIG, "timezone": {"offset_hours": -5}}
        path = _write_yaml(tmp_path, data)
        cfg = load_config(path)
        assert cfg.timezone.resolved_label == "UTC-5"

    def test_no_timezone_section(self, tmp_path):
        path = _write_yaml(tmp_path, MINIMAL_CONFIG)
        cfg = load_config(path)
        assert cfg.timezone is None

    def test_non_int_offset_raises(self, tmp_path):
        data = {**MINIMAL_CONFIG, "timezone": {"offset_hours": "three"}}
        path = _write_yaml(tmp_path, data)
        with pytest.raises(ValueError, match="integer"):
            load_config(path)
