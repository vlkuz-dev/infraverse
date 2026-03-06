"""Tests for infraverse.config_file module — YAML config file parser."""

import pytest
import yaml

from infraverse.config_file import (
    CloudAccountConfig,
    InfraverseConfig,
    MonitoringConfig,
    OidcConfig,
    TenantConfig,
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
