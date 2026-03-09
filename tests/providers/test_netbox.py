"""Tests for NetBox client facade (netbox.py)."""

from unittest.mock import patch, MagicMock

from infraverse.providers.netbox import NetBoxClient


class TestImports:
    def test_import_from_module(self):
        from infraverse.providers.netbox import NetBoxClient as NB
        assert NB is NetBoxClient

    def test_client_has_all_mixin_methods(self):
        """Verify the facade exposes all methods from all mixins."""
        expected_methods = [
            # Tags
            "ensure_sync_tag", "_add_tag_to_object",
            # Infrastructure
            "_safe_update_object", "ensure_site", "ensure_cluster_type",
            "ensure_cluster", "ensure_platform",
            # Prefixes
            "ensure_prefix", "update_prefix",
            # VMs
            "fetch_vms", "fetch_all_vms", "create_vm", "update_vm",
            "get_vm_by_name", "get_vm_by_custom_field",
            # Interfaces
            "create_disk", "create_interface", "create_ip", "set_vm_primary_ip",
        ]
        for method in expected_methods:
            assert hasattr(NetBoxClient, method), f"Missing method: {method}"


class TestInit:
    def test_init_creates_caches(self):
        with patch('infraverse.providers.netbox.pynetbox') as mock_pynetbox:
            mock_pynetbox.api.return_value = MagicMock()
            client = NetBoxClient("https://netbox.example.com", "test-token")

            assert client._cluster_type_cache == {}
            assert client._cluster_type_id is None
            assert client._sync_tag_cache == {}
            assert client._sync_tag_id is None
            assert client.dry_run is False

    def test_init_dry_run(self):
        with patch('infraverse.providers.netbox.pynetbox') as mock_pynetbox:
            mock_pynetbox.api.return_value = MagicMock()
            client = NetBoxClient("https://netbox.example.com", "test-token", dry_run=True)

            assert client.dry_run is True
