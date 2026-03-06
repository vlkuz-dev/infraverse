"""Tests for external URL link builder."""

from types import SimpleNamespace

from infraverse.web.links import build_account_links, build_vm_links, render_url


# --- render_url tests ---


class TestRenderUrl:
    def test_renders_simple_template(self):
        url = render_url("https://example.com/{id}", {"id": "42"})
        assert url == "https://example.com/42"

    def test_renders_multiple_placeholders(self):
        url = render_url(
            "https://console.yandex.cloud/folders/{folder_id}/compute/instances/{vm_id}",
            {"folder_id": "abc123", "vm_id": "vm-001"},
        )
        assert url == "https://console.yandex.cloud/folders/abc123/compute/instances/vm-001"

    def test_returns_none_for_none_template(self):
        assert render_url(None, {"id": "42"}) is None

    def test_returns_none_for_empty_template(self):
        assert render_url("", {"id": "42"}) is None

    def test_returns_none_for_missing_key(self):
        assert render_url("https://example.com/{id}", {}) is None

    def test_returns_none_for_empty_value(self):
        assert render_url("https://example.com/{id}", {"id": ""}) is None

    def test_returns_none_for_partial_data(self):
        url = render_url(
            "https://example.com/{a}/{b}",
            {"a": "foo"},
        )
        assert url is None

    def test_extra_data_ignored(self):
        url = render_url("https://example.com/{id}", {"id": "42", "extra": "ignored"})
        assert url == "https://example.com/42"

    def test_no_placeholders(self):
        url = render_url("https://example.com/static", {})
        assert url == "https://example.com/static"


# --- build_vm_links tests ---


def _make_config(**kwargs):
    defaults = {
        "yc_console_url": None,
        "zabbix_host_url": None,
        "netbox_vm_url": None,
        "zabbix_url": None,
        "netbox_url": None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class TestBuildVmLinks:
    def test_returns_empty_when_no_config(self):
        vm_data = {"external_id": "vm-001"}
        assert build_vm_links(vm_data, None, None) == []

    def test_returns_empty_when_no_templates_configured(self):
        config = _make_config()
        vm_data = {"external_id": "vm-001"}
        assert build_vm_links(vm_data, None, config) == []

    def test_yc_console_link(self):
        config = _make_config(
            yc_console_url="https://console.yandex.cloud/folders/{folder_id}/compute/instances/{vm_id}",
        )
        vm_data = {"external_id": "vm-001"}
        account_data = {"config": {"folder_id": "abc123"}}
        links = build_vm_links(vm_data, account_data, config)
        assert len(links) == 1
        assert links[0]["label"] == "Cloud Console"
        assert links[0]["url"] == "https://console.yandex.cloud/folders/abc123/compute/instances/vm-001"
        assert links[0]["icon"] == "cloud"

    def test_netbox_link(self):
        config = _make_config(
            netbox_url="https://netbox.example.com",
            netbox_vm_url="{netbox_url}/virtualization/virtual-machines/{vm_id}/",
        )
        vm_data = {"external_id": "vm-001"}
        links = build_vm_links(vm_data, None, config)
        assert len(links) == 1
        assert links[0]["label"] == "NetBox"
        assert links[0]["url"] == "https://netbox.example.com/virtualization/virtual-machines/vm-001/"

    def test_zabbix_link(self):
        config = _make_config(
            zabbix_url="https://zabbix.example.com",
            zabbix_host_url="{zabbix_url}/hosts.php?form=update&hostid={host_id}",
        )
        vm_data = {"external_id": "vm-001", "monitoring_host_id": "12345"}
        links = build_vm_links(vm_data, None, config)
        assert len(links) == 1
        assert links[0]["label"] == "Zabbix"
        assert links[0]["url"] == "https://zabbix.example.com/hosts.php?form=update&hostid=12345"

    def test_multiple_links(self):
        config = _make_config(
            yc_console_url="https://console.yandex.cloud/folders/{folder_id}/compute/instances/{vm_id}",
            netbox_url="https://netbox.example.com",
            netbox_vm_url="{netbox_url}/virtualization/virtual-machines/{vm_id}/",
        )
        vm_data = {"external_id": "vm-001"}
        account_data = {"config": {"folder_id": "abc123"}}
        links = build_vm_links(vm_data, account_data, config)
        assert len(links) == 2
        labels = [link["label"] for link in links]
        assert "Cloud Console" in labels
        assert "NetBox" in labels

    def test_yc_link_missing_folder_id(self):
        config = _make_config(
            yc_console_url="https://console.yandex.cloud/folders/{folder_id}/compute/instances/{vm_id}",
        )
        vm_data = {"external_id": "vm-001"}
        account_data = {"config": {}}
        links = build_vm_links(vm_data, account_data, config)
        assert len(links) == 0

    def test_yc_link_missing_external_id(self):
        config = _make_config(
            yc_console_url="https://console.yandex.cloud/folders/{folder_id}/compute/instances/{vm_id}",
        )
        vm_data = {}
        account_data = {"config": {"folder_id": "abc123"}}
        links = build_vm_links(vm_data, account_data, config)
        assert len(links) == 0

    def test_zabbix_link_missing_host_id(self):
        config = _make_config(
            zabbix_url="https://zabbix.example.com",
            zabbix_host_url="{zabbix_url}/hosts.php?form=update&hostid={host_id}",
        )
        vm_data = {"external_id": "vm-001"}
        links = build_vm_links(vm_data, None, config)
        assert len(links) == 0

    def test_netbox_url_trailing_slash_stripped(self):
        config = _make_config(
            netbox_url="https://netbox.example.com/",
            netbox_vm_url="{netbox_url}/virtualization/virtual-machines/{vm_id}/",
        )
        vm_data = {"external_id": "vm-001"}
        links = build_vm_links(vm_data, None, config)
        assert len(links) == 1
        assert links[0]["url"] == "https://netbox.example.com/virtualization/virtual-machines/vm-001/"

    def test_account_data_none_config(self):
        config = _make_config(
            yc_console_url="https://console.yandex.cloud/folders/{folder_id}/compute/instances/{vm_id}",
        )
        vm_data = {"external_id": "vm-001"}
        account_data = {"config": None}
        links = build_vm_links(vm_data, account_data, config)
        assert len(links) == 0


# --- build_account_links tests ---


class TestBuildAccountLinks:
    def test_returns_empty_when_no_config(self):
        account_data = {"provider_type": "yandex_cloud", "config": {"folder_id": "abc123"}}
        assert build_account_links(account_data, None) == []

    def test_returns_empty_when_not_yandex_cloud(self):
        config = _make_config(
            yc_console_url="https://console.yandex.cloud/folders/{folder_id}/compute/instances/{vm_id}",
        )
        account_data = {"provider_type": "vcloud", "config": {"folder_id": "abc123"}}
        assert build_account_links(account_data, config) == []

    def test_yandex_cloud_folder_link(self):
        config = _make_config(
            yc_console_url="https://console.yandex.cloud/folders/{folder_id}/compute/instances/{vm_id}",
        )
        account_data = {"provider_type": "yandex_cloud", "config": {"folder_id": "abc123"}}
        links = build_account_links(account_data, config)
        assert len(links) == 1
        assert links[0]["label"] == "Cloud Console"
        assert links[0]["url"] == "https://console.yandex.cloud/folders/abc123"
        assert links[0]["icon"] == "cloud"

    def test_missing_folder_id(self):
        config = _make_config(
            yc_console_url="https://console.yandex.cloud/folders/{folder_id}/compute/instances/{vm_id}",
        )
        account_data = {"provider_type": "yandex_cloud", "config": {}}
        links = build_account_links(account_data, config)
        assert len(links) == 0

    def test_no_yc_console_url_configured(self):
        config = _make_config()
        account_data = {"provider_type": "yandex_cloud", "config": {"folder_id": "abc123"}}
        links = build_account_links(account_data, config)
        assert len(links) == 0

    def test_none_config_in_account(self):
        config = _make_config(
            yc_console_url="https://console.yandex.cloud/folders/{folder_id}/compute/instances/{vm_id}",
        )
        account_data = {"provider_type": "yandex_cloud", "config": None}
        links = build_account_links(account_data, config)
        assert len(links) == 0
