"""Tests for infraverse.config module."""

import logging

import pytest

from infraverse.config import Config


class TestConfigInit:
    def test_stores_all_fields(self):
        cfg = Config(
            yc_token="tok-yc",
            netbox_url="https://nb.example.com",
            netbox_token="tok-nb",
            dry_run=True,
        )
        assert cfg.yc_token == "tok-yc"
        assert cfg.netbox_url == "https://nb.example.com"
        assert cfg.netbox_token == "tok-nb"
        assert cfg.dry_run is True

    def test_dry_run_defaults_false(self):
        cfg = Config(yc_token="a", netbox_url="b", netbox_token="c")
        assert cfg.dry_run is False

    def test_database_url_default(self):
        cfg = Config(yc_token="a", netbox_url="b", netbox_token="c")
        assert cfg.database_url == "sqlite:///infraverse.db"

    def test_database_url_custom(self):
        cfg = Config(
            yc_token="a",
            netbox_url="b",
            netbox_token="c",
            database_url="sqlite:///custom.db",
        )
        assert cfg.database_url == "sqlite:///custom.db"


class TestFromEnv:
    def test_loads_all_env_vars(self, monkeypatch):
        monkeypatch.setenv("YC_TOKEN", "yc-secret")
        monkeypatch.setenv("NETBOX_URL", "https://netbox.local")
        monkeypatch.setenv("NETBOX_TOKEN", "nb-secret")

        cfg = Config.from_env()
        assert cfg.yc_token == "yc-secret"
        assert cfg.netbox_url == "https://netbox.local"
        assert cfg.netbox_token == "nb-secret"
        assert cfg.dry_run is False

    def test_passes_dry_run(self, monkeypatch):
        monkeypatch.setenv("YC_TOKEN", "a")
        monkeypatch.setenv("NETBOX_URL", "b")
        monkeypatch.setenv("NETBOX_TOKEN", "c")

        cfg = Config.from_env(dry_run=True)
        assert cfg.dry_run is True

    def test_raises_when_all_missing(self, monkeypatch):
        monkeypatch.delenv("YC_TOKEN", raising=False)
        monkeypatch.delenv("NETBOX_URL", raising=False)
        monkeypatch.delenv("NETBOX_TOKEN", raising=False)

        with pytest.raises(ValueError, match="YC_TOKEN"):
            Config.from_env()

    def test_raises_lists_all_missing(self, monkeypatch):
        monkeypatch.delenv("YC_TOKEN", raising=False)
        monkeypatch.delenv("NETBOX_URL", raising=False)
        monkeypatch.delenv("NETBOX_TOKEN", raising=False)

        with pytest.raises(ValueError) as exc_info:
            Config.from_env()

        msg = str(exc_info.value)
        assert "YC_TOKEN" in msg
        assert "NETBOX_URL" in msg
        assert "NETBOX_TOKEN" in msg

    def test_raises_when_one_missing(self, monkeypatch):
        monkeypatch.setenv("YC_TOKEN", "a")
        monkeypatch.setenv("NETBOX_URL", "b")
        monkeypatch.delenv("NETBOX_TOKEN", raising=False)

        with pytest.raises(ValueError, match="NETBOX_TOKEN"):
            Config.from_env()

    def test_empty_string_treated_as_missing(self, monkeypatch):
        monkeypatch.setenv("YC_TOKEN", "")
        monkeypatch.setenv("NETBOX_URL", "b")
        monkeypatch.setenv("NETBOX_TOKEN", "c")

        with pytest.raises(ValueError, match="YC_TOKEN"):
            Config.from_env()

    def test_database_url_default_from_env(self, monkeypatch):
        monkeypatch.setenv("YC_TOKEN", "a")
        monkeypatch.setenv("NETBOX_URL", "b")
        monkeypatch.setenv("NETBOX_TOKEN", "c")
        monkeypatch.delenv("DATABASE_URL", raising=False)

        cfg = Config.from_env()
        assert cfg.database_url == "sqlite:///infraverse.db"

    def test_database_url_from_env(self, monkeypatch):
        monkeypatch.setenv("YC_TOKEN", "a")
        monkeypatch.setenv("NETBOX_URL", "b")
        monkeypatch.setenv("NETBOX_TOKEN", "c")
        monkeypatch.setenv("DATABASE_URL", "sqlite:///custom.db")

        cfg = Config.from_env()
        assert cfg.database_url == "sqlite:///custom.db"

    def test_database_url_postgres(self, monkeypatch):
        monkeypatch.setenv("YC_TOKEN", "a")
        monkeypatch.setenv("NETBOX_URL", "b")
        monkeypatch.setenv("NETBOX_TOKEN", "c")
        monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/infraverse")

        cfg = Config.from_env()
        assert cfg.database_url == "postgresql://user:pass@localhost/infraverse"


class TestSetupLogging:
    def test_configures_default_info_level(self, monkeypatch):
        monkeypatch.delenv("LOG_LEVEL", raising=False)
        cfg = Config(yc_token="a", netbox_url="b", netbox_token="c")

        root = logging.getLogger()
        root.handlers.clear()

        cfg.setup_logging()
        assert root.level == logging.INFO

    def test_configures_debug_level(self, monkeypatch):
        monkeypatch.setenv("LOG_LEVEL", "debug")
        cfg = Config(yc_token="a", netbox_url="b", netbox_token="c")

        root = logging.getLogger()
        root.handlers.clear()

        cfg.setup_logging()
        assert root.level == logging.DEBUG

    def test_silences_third_party_loggers(self, monkeypatch):
        monkeypatch.delenv("LOG_LEVEL", raising=False)
        cfg = Config(yc_token="a", netbox_url="b", netbox_token="c")

        root = logging.getLogger()
        root.handlers.clear()

        cfg.setup_logging()
        for name in ("httpx", "httpcore", "pynetbox", "urllib3", "requests"):
            assert logging.getLogger(name).level == logging.WARNING


class TestRepr:
    def test_masks_long_tokens(self):
        cfg = Config(
            yc_token="abcdefghijklmnop",
            netbox_url="https://nb.example.com",
            netbox_token="1234567890abcdef",
        )
        r = repr(cfg)
        assert "abcdefghijklmnop" not in r
        assert "1234567890abcdef" not in r
        assert "abcd***mnop" in r
        assert "1234***cdef" in r
        assert "https://nb.example.com" in r
        assert "dry_run=False" in r

    def test_masks_short_tokens(self):
        cfg = Config(
            yc_token="short",
            netbox_url="https://nb.example.com",
            netbox_token="tiny",
        )
        r = repr(cfg)
        assert "short" not in r
        assert "tiny" not in r
        assert "***" in r

    def test_shows_dry_run_true(self):
        cfg = Config(
            yc_token="abcdefghijklmnop",
            netbox_url="https://nb.example.com",
            netbox_token="1234567890abcdef",
            dry_run=True,
        )
        assert "dry_run=True" in repr(cfg)


class TestVcdConfig:
    def _base_cfg(self, **kwargs):
        defaults = dict(yc_token="a", netbox_url="b", netbox_token="c")
        defaults.update(kwargs)
        return Config(**defaults)

    def test_vcd_defaults_none(self):
        cfg = self._base_cfg()
        assert cfg.vcd_url is None
        assert cfg.vcd_user is None
        assert cfg.vcd_password is None
        assert cfg.vcd_org is None

    def test_vcd_configured_when_all_set(self):
        cfg = self._base_cfg(
            vcd_url="https://vcd.example.com",
            vcd_user="admin",
            vcd_password="secret",
        )
        assert cfg.vcd_configured is True

    def test_vcd_not_configured_when_partial(self):
        cfg = self._base_cfg(vcd_url="https://vcd.example.com")
        assert cfg.vcd_configured is False

    def test_vcd_not_configured_when_none(self):
        cfg = self._base_cfg()
        assert cfg.vcd_configured is False

    def test_vcd_org_optional_for_configured(self):
        cfg = self._base_cfg(
            vcd_url="https://vcd.example.com",
            vcd_user="admin",
            vcd_password="secret",
            vcd_org="MyOrg",
        )
        assert cfg.vcd_configured is True
        assert cfg.vcd_org == "MyOrg"

    def test_from_env_reads_vcd_vars(self, monkeypatch):
        monkeypatch.setenv("YC_TOKEN", "yc")
        monkeypatch.setenv("NETBOX_URL", "nb")
        monkeypatch.setenv("NETBOX_TOKEN", "nbt")
        monkeypatch.setenv("VCD_URL", "https://vcd.example.com")
        monkeypatch.setenv("VCD_USER", "admin")
        monkeypatch.setenv("VCD_PASSWORD", "secret")
        monkeypatch.setenv("VCD_ORG", "MyOrg")

        cfg = Config.from_env()
        assert cfg.vcd_url == "https://vcd.example.com"
        assert cfg.vcd_user == "admin"
        assert cfg.vcd_password == "secret"
        assert cfg.vcd_org == "MyOrg"
        assert cfg.vcd_configured is True

    def test_from_env_vcd_absent(self, monkeypatch):
        monkeypatch.setenv("YC_TOKEN", "yc")
        monkeypatch.setenv("NETBOX_URL", "nb")
        monkeypatch.setenv("NETBOX_TOKEN", "nbt")
        monkeypatch.delenv("VCD_URL", raising=False)
        monkeypatch.delenv("VCD_USER", raising=False)
        monkeypatch.delenv("VCD_PASSWORD", raising=False)
        monkeypatch.delenv("VCD_ORG", raising=False)

        cfg = Config.from_env()
        assert cfg.vcd_url is None
        assert cfg.vcd_configured is False


class TestZabbixConfig:
    def _base_cfg(self, **kwargs):
        defaults = dict(yc_token="a", netbox_url="b", netbox_token="c")
        defaults.update(kwargs)
        return Config(**defaults)

    def test_zabbix_defaults_none(self):
        cfg = self._base_cfg()
        assert cfg.zabbix_url is None
        assert cfg.zabbix_user is None
        assert cfg.zabbix_password is None

    def test_zabbix_configured_when_all_set(self):
        cfg = self._base_cfg(
            zabbix_url="https://zabbix.example.com",
            zabbix_user="Admin",
            zabbix_password="zabbix",
        )
        assert cfg.zabbix_configured is True

    def test_zabbix_not_configured_when_partial(self):
        cfg = self._base_cfg(zabbix_url="https://zabbix.example.com")
        assert cfg.zabbix_configured is False

    def test_zabbix_not_configured_when_none(self):
        cfg = self._base_cfg()
        assert cfg.zabbix_configured is False

    def test_from_env_reads_zabbix_vars(self, monkeypatch):
        monkeypatch.setenv("YC_TOKEN", "yc")
        monkeypatch.setenv("NETBOX_URL", "nb")
        monkeypatch.setenv("NETBOX_TOKEN", "nbt")
        monkeypatch.setenv("ZABBIX_URL", "https://zabbix.example.com")
        monkeypatch.setenv("ZABBIX_USER", "Admin")
        monkeypatch.setenv("ZABBIX_PASSWORD", "zabbix")

        cfg = Config.from_env()
        assert cfg.zabbix_url == "https://zabbix.example.com"
        assert cfg.zabbix_user == "Admin"
        assert cfg.zabbix_password == "zabbix"
        assert cfg.zabbix_configured is True

    def test_from_env_zabbix_absent(self, monkeypatch):
        monkeypatch.setenv("YC_TOKEN", "yc")
        monkeypatch.setenv("NETBOX_URL", "nb")
        monkeypatch.setenv("NETBOX_TOKEN", "nbt")
        monkeypatch.delenv("ZABBIX_URL", raising=False)
        monkeypatch.delenv("ZABBIX_USER", raising=False)
        monkeypatch.delenv("ZABBIX_PASSWORD", raising=False)

        cfg = Config.from_env()
        assert cfg.zabbix_url is None
        assert cfg.zabbix_configured is False


class TestSyncIntervalConfig:
    def _base_cfg(self, **kwargs):
        defaults = dict(yc_token="a", netbox_url="b", netbox_token="c")
        defaults.update(kwargs)
        return Config(**defaults)

    def test_sync_interval_defaults_zero(self):
        cfg = self._base_cfg()
        assert cfg.sync_interval_minutes == 0

    def test_sync_interval_custom_value(self):
        cfg = self._base_cfg(sync_interval_minutes=30)
        assert cfg.sync_interval_minutes == 30

    def test_sync_interval_large_value(self):
        cfg = self._base_cfg(sync_interval_minutes=1440)
        assert cfg.sync_interval_minutes == 1440

    def test_from_env_default_zero(self, monkeypatch):
        monkeypatch.setenv("YC_TOKEN", "yc")
        monkeypatch.setenv("NETBOX_URL", "nb")
        monkeypatch.setenv("NETBOX_TOKEN", "nbt")
        monkeypatch.delenv("SYNC_INTERVAL_MINUTES", raising=False)

        cfg = Config.from_env()
        assert cfg.sync_interval_minutes == 0

    def test_from_env_reads_sync_interval(self, monkeypatch):
        monkeypatch.setenv("YC_TOKEN", "yc")
        monkeypatch.setenv("NETBOX_URL", "nb")
        monkeypatch.setenv("NETBOX_TOKEN", "nbt")
        monkeypatch.setenv("SYNC_INTERVAL_MINUTES", "30")

        cfg = Config.from_env()
        assert cfg.sync_interval_minutes == 30

    def test_from_env_sync_interval_custom(self, monkeypatch):
        monkeypatch.setenv("YC_TOKEN", "yc")
        monkeypatch.setenv("NETBOX_URL", "nb")
        monkeypatch.setenv("NETBOX_TOKEN", "nbt")
        monkeypatch.setenv("SYNC_INTERVAL_MINUTES", "120")

        cfg = Config.from_env()
        assert cfg.sync_interval_minutes == 120

    def test_from_env_sync_interval_non_integer_defaults_zero(self, monkeypatch):
        monkeypatch.setenv("YC_TOKEN", "yc")
        monkeypatch.setenv("NETBOX_URL", "nb")
        monkeypatch.setenv("NETBOX_TOKEN", "nbt")
        monkeypatch.setenv("SYNC_INTERVAL_MINUTES", "abc")

        cfg = Config.from_env()
        assert cfg.sync_interval_minutes == 0

    def test_from_env_sync_interval_negative_defaults_zero(self, monkeypatch):
        monkeypatch.setenv("YC_TOKEN", "yc")
        monkeypatch.setenv("NETBOX_URL", "nb")
        monkeypatch.setenv("NETBOX_TOKEN", "nbt")
        monkeypatch.setenv("SYNC_INTERVAL_MINUTES", "-5")

        cfg = Config.from_env()
        assert cfg.sync_interval_minutes == 0

    def test_from_env_sync_interval_float_defaults_zero(self, monkeypatch):
        monkeypatch.setenv("YC_TOKEN", "yc")
        monkeypatch.setenv("NETBOX_URL", "nb")
        monkeypatch.setenv("NETBOX_TOKEN", "nbt")
        monkeypatch.setenv("SYNC_INTERVAL_MINUTES", "30.5")

        cfg = Config.from_env()
        assert cfg.sync_interval_minutes == 0


class TestExternalLinksConfig:
    def _base_cfg(self, **kwargs):
        defaults = dict(yc_token="a", netbox_url="b", netbox_token="c")
        defaults.update(kwargs)
        return Config(**defaults)

    def test_external_links_default_none(self):
        cfg = self._base_cfg()
        assert cfg.yc_console_url is None
        assert cfg.zabbix_host_url is None
        assert cfg.netbox_vm_url is None

    def test_external_links_custom_values(self):
        cfg = self._base_cfg(
            yc_console_url="https://console.yandex.cloud/folders/{folder_id}/compute/instances/{vm_id}",
            zabbix_host_url="{zabbix_url}/hosts.php?form=update&hostid={host_id}",
            netbox_vm_url="{netbox_url}/virtualization/virtual-machines/{vm_id}/",
        )
        assert cfg.yc_console_url == "https://console.yandex.cloud/folders/{folder_id}/compute/instances/{vm_id}"
        assert cfg.zabbix_host_url == "{zabbix_url}/hosts.php?form=update&hostid={host_id}"
        assert cfg.netbox_vm_url == "{netbox_url}/virtualization/virtual-machines/{vm_id}/"

    def test_from_env_reads_external_link_vars(self, monkeypatch):
        monkeypatch.setenv("YC_TOKEN", "yc")
        monkeypatch.setenv("NETBOX_URL", "nb")
        monkeypatch.setenv("NETBOX_TOKEN", "nbt")
        monkeypatch.setenv("YC_CONSOLE_URL", "https://console.yandex.cloud/folders/{folder_id}/compute/instances/{vm_id}")
        monkeypatch.setenv("ZABBIX_HOST_URL", "{zabbix_url}/hosts.php?form=update&hostid={host_id}")
        monkeypatch.setenv("NETBOX_VM_URL", "{netbox_url}/virtualization/virtual-machines/{vm_id}/")

        cfg = Config.from_env()
        assert cfg.yc_console_url == "https://console.yandex.cloud/folders/{folder_id}/compute/instances/{vm_id}"
        assert cfg.zabbix_host_url == "{zabbix_url}/hosts.php?form=update&hostid={host_id}"
        assert cfg.netbox_vm_url == "{netbox_url}/virtualization/virtual-machines/{vm_id}/"

    def test_from_env_external_links_absent(self, monkeypatch):
        monkeypatch.setenv("YC_TOKEN", "yc")
        monkeypatch.setenv("NETBOX_URL", "nb")
        monkeypatch.setenv("NETBOX_TOKEN", "nbt")
        monkeypatch.delenv("YC_CONSOLE_URL", raising=False)
        monkeypatch.delenv("ZABBIX_HOST_URL", raising=False)
        monkeypatch.delenv("NETBOX_VM_URL", raising=False)

        cfg = Config.from_env()
        assert cfg.yc_console_url is None
        assert cfg.zabbix_host_url is None
        assert cfg.netbox_vm_url is None

    def test_from_env_empty_string_treated_as_none(self, monkeypatch):
        monkeypatch.setenv("YC_TOKEN", "yc")
        monkeypatch.setenv("NETBOX_URL", "nb")
        monkeypatch.setenv("NETBOX_TOKEN", "nbt")
        monkeypatch.setenv("YC_CONSOLE_URL", "")
        monkeypatch.setenv("ZABBIX_HOST_URL", "")
        monkeypatch.setenv("NETBOX_VM_URL", "")

        cfg = Config.from_env()
        assert cfg.yc_console_url is None
        assert cfg.zabbix_host_url is None
        assert cfg.netbox_vm_url is None


class TestAllProvidersConfig:
    def test_from_env_all_providers(self, monkeypatch):
        monkeypatch.setenv("YC_TOKEN", "yc")
        monkeypatch.setenv("NETBOX_URL", "nb")
        monkeypatch.setenv("NETBOX_TOKEN", "nbt")
        monkeypatch.setenv("VCD_URL", "https://vcd.example.com")
        monkeypatch.setenv("VCD_USER", "admin")
        monkeypatch.setenv("VCD_PASSWORD", "secret")
        monkeypatch.setenv("ZABBIX_URL", "https://zabbix.example.com")
        monkeypatch.setenv("ZABBIX_USER", "Admin")
        monkeypatch.setenv("ZABBIX_PASSWORD", "zabbix")

        cfg = Config.from_env()
        assert cfg.vcd_configured is True
        assert cfg.zabbix_configured is True
        assert cfg.yc_token == "yc"

    def test_from_env_only_yc(self, monkeypatch):
        monkeypatch.setenv("YC_TOKEN", "yc")
        monkeypatch.setenv("NETBOX_URL", "nb")
        monkeypatch.setenv("NETBOX_TOKEN", "nbt")
        monkeypatch.delenv("VCD_URL", raising=False)
        monkeypatch.delenv("VCD_USER", raising=False)
        monkeypatch.delenv("VCD_PASSWORD", raising=False)
        monkeypatch.delenv("VCD_ORG", raising=False)
        monkeypatch.delenv("ZABBIX_URL", raising=False)
        monkeypatch.delenv("ZABBIX_USER", raising=False)
        monkeypatch.delenv("ZABBIX_PASSWORD", raising=False)

        cfg = Config.from_env()
        assert cfg.vcd_configured is False
        assert cfg.zabbix_configured is False
        assert cfg.yc_token == "yc"

    def test_empty_env_string_treated_as_none(self, monkeypatch):
        monkeypatch.setenv("YC_TOKEN", "yc")
        monkeypatch.setenv("NETBOX_URL", "nb")
        monkeypatch.setenv("NETBOX_TOKEN", "nbt")
        monkeypatch.setenv("VCD_URL", "")
        monkeypatch.setenv("ZABBIX_URL", "")

        cfg = Config.from_env()
        assert cfg.vcd_url is None
        assert cfg.zabbix_url is None
        assert cfg.vcd_configured is False
        assert cfg.zabbix_configured is False
