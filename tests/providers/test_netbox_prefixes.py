"""Tests for NetBox prefix management (NetBoxPrefixesMixin)."""

import pytest
from unittest.mock import MagicMock, patch

from infraverse.providers.netbox import NetBoxClient


class MockRecord:
    """Mock pynetbox Record object."""

    def __init__(self, id, name=None, slug=None, **kwargs):
        self.id = id
        self.name = name
        self.slug = slug
        self.save = MagicMock(return_value=True)
        self.delete = MagicMock(return_value=True)
        for k, v in kwargs.items():
            setattr(self, k, v)

    def __str__(self):
        return self.name or str(self.id)

    def keys(self):
        return [k for k in self.__dict__ if not k.startswith('_')]

    def __getitem__(self, key):
        return getattr(self, key)


@pytest.fixture
def nb_client():
    """Create a NetBoxClient with mocked pynetbox API."""
    with patch('infraverse.providers.netbox.pynetbox') as mock_pynetbox:
        mock_api = MagicMock()
        mock_pynetbox.api.return_value = mock_api

        client = NetBoxClient("https://netbox.example.com", "test-token", dry_run=False)
        client._mock_api = mock_api
        return client


@pytest.fixture
def nb_client_dry_run():
    """Create a NetBoxClient in dry-run mode."""
    with patch('infraverse.providers.netbox.pynetbox') as mock_pynetbox:
        mock_api = MagicMock()
        mock_pynetbox.api.return_value = mock_api

        client = NetBoxClient("https://netbox.example.com", "test-token", dry_run=True)
        client._mock_api = mock_api
        return client


class TestEnsurePrefix:
    def test_returns_existing_prefix(self, nb_client):
        nb_client._sync_tag_id = 1
        existing = MockRecord(10, prefix="10.0.0.0/24", tags=[])
        nb_client.nb.ipam.prefixes.get.return_value = existing

        result = nb_client.ensure_prefix("10.0.0.0/24", "my-vpc")

        assert result.id == 10

    def test_creates_new_prefix(self, nb_client):
        nb_client._sync_tag_id = 1
        nb_client.nb.ipam.prefixes.get.return_value = None
        created = MockRecord(20, prefix="10.1.0.0/24")
        nb_client.nb.ipam.prefixes.create.return_value = created

        result = nb_client.ensure_prefix("10.1.0.0/24", "my-vpc")

        assert result.id == 20
        call_args = nb_client.nb.ipam.prefixes.create.call_args[0][0]
        assert call_args["prefix"] == "10.1.0.0/24"
        assert call_args["status"] == "active"
        assert "VPC: my-vpc" in call_args["description"]
        assert call_args["tags"] == [1]

    def test_creates_prefix_with_site_scope(self, nb_client):
        nb_client._sync_tag_id = 1
        nb_client.nb.ipam.prefixes.get.return_value = None
        created = MockRecord(21, prefix="10.2.0.0/24")
        nb_client.nb.ipam.prefixes.create.return_value = created

        result = nb_client.ensure_prefix("10.2.0.0/24", "my-vpc", site_id=5)

        assert result.id == 21
        call_args = nb_client.nb.ipam.prefixes.create.call_args[0][0]
        assert call_args["scope_type"] == "dcim.site"
        assert call_args["scope_id"] == 5

    def test_creates_prefix_without_site_when_none(self, nb_client):
        nb_client._sync_tag_id = 1
        nb_client.nb.ipam.prefixes.get.return_value = None
        created = MockRecord(22, prefix="10.3.0.0/24")
        nb_client.nb.ipam.prefixes.create.return_value = created

        nb_client.ensure_prefix("10.3.0.0/24", "my-vpc", site_id=None)

        call_args = nb_client.nb.ipam.prefixes.create.call_args[0][0]
        assert "scope_type" not in call_args
        assert "scope_id" not in call_args

    def test_treats_site_id_zero_as_none(self, nb_client):
        nb_client._sync_tag_id = 1
        nb_client.nb.ipam.prefixes.get.return_value = None
        created = MockRecord(23, prefix="10.4.0.0/24")
        nb_client.nb.ipam.prefixes.create.return_value = created

        nb_client.ensure_prefix("10.4.0.0/24", "my-vpc", site_id=0)

        call_args = nb_client.nb.ipam.prefixes.create.call_args[0][0]
        assert "scope_type" not in call_args

    def test_dry_run_returns_none(self, nb_client_dry_run):
        nb_client_dry_run.nb.ipam.prefixes.get.return_value = None

        result = nb_client_dry_run.ensure_prefix("10.0.0.0/24", "my-vpc")

        assert result is None
        nb_client_dry_run.nb.ipam.prefixes.create.assert_not_called()

    def test_lookup_error_returns_none(self, nb_client):
        nb_client.nb.ipam.prefixes.get.side_effect = Exception("API error")

        result = nb_client.ensure_prefix("10.0.0.0/24", "my-vpc")

        assert result is None

    def test_create_error_returns_none(self, nb_client):
        nb_client._sync_tag_id = 1
        nb_client.nb.ipam.prefixes.get.return_value = None
        nb_client.nb.ipam.prefixes.create.side_effect = Exception("create failed")

        result = nb_client.ensure_prefix("10.0.0.0/24", "my-vpc")

        assert result is None

    def test_fallback_to_legacy_site_on_scope_error(self, nb_client):
        nb_client._sync_tag_id = 1
        nb_client.nb.ipam.prefixes.get.return_value = None

        # First create with scope fields fails, second with site field succeeds
        created = MockRecord(24, prefix="10.5.0.0/24")
        nb_client.nb.ipam.prefixes.create.side_effect = [
            Exception("scope_type is not a valid field"),
            created,
        ]

        result = nb_client.ensure_prefix("10.5.0.0/24", "my-vpc", site_id=5)

        assert result.id == 24
        # Second call should use legacy site field
        second_call = nb_client.nb.ipam.prefixes.create.call_args_list[1][0][0]
        assert second_call["site"] == 5
        assert "scope_type" not in second_call

    def test_adds_description(self, nb_client):
        nb_client._sync_tag_id = 1
        nb_client.nb.ipam.prefixes.get.return_value = None
        created = MockRecord(25, prefix="10.6.0.0/24")
        nb_client.nb.ipam.prefixes.create.return_value = created

        nb_client.ensure_prefix("10.6.0.0/24", "my-vpc", description="Prod network")

        call_args = nb_client.nb.ipam.prefixes.create.call_args[0][0]
        assert "VPC: my-vpc" in call_args["description"]
        assert "Prod network" in call_args["description"]

    def test_existing_prefix_updates_scope_when_different(self, nb_client):
        nb_client._sync_tag_id = 1
        existing = MockRecord(
            10, prefix="10.0.0.0/24", tags=[],
            scope_type="dcim.site", scope_id=3,
        )
        nb_client.nb.ipam.prefixes.get.side_effect = [
            existing,  # initial lookup
            existing,  # update_prefix refetch
        ]
        existing.save.return_value = True

        result = nb_client.ensure_prefix("10.0.0.0/24", "my-vpc", site_id=5)

        assert result.id == 10
        # update_prefix should have been called (save on the refetched object)
        assert existing.save.called

    def test_existing_prefix_skips_update_in_dry_run(self, nb_client_dry_run):
        nb_client_dry_run._sync_tag_id = 1
        existing = MockRecord(
            10, prefix="10.0.0.0/24", tags=[],
            scope_type="dcim.site", scope_id=3,
        )
        nb_client_dry_run.nb.ipam.prefixes.get.return_value = existing

        result = nb_client_dry_run.ensure_prefix("10.0.0.0/24", "my-vpc", site_id=5)

        assert result.id == 10
        # Should not try to update in dry run
        existing.save.assert_not_called()


class TestUpdatePrefix:
    def test_update_success_via_save(self, nb_client):
        prefix_obj = MockRecord(10, prefix="10.0.0.0/24")
        prefix_obj.save.return_value = True
        nb_client.nb.ipam.prefixes.get.return_value = prefix_obj

        result = nb_client.update_prefix(10, {"description": "updated"})

        assert result is True
        assert prefix_obj.description == "updated"

    def test_update_dry_run(self, nb_client_dry_run):
        result = nb_client_dry_run.update_prefix(10, {"description": "updated"})

        assert result is True
        nb_client_dry_run.nb.ipam.prefixes.get.assert_not_called()

    def test_update_prefix_not_found(self, nb_client):
        nb_client.nb.ipam.prefixes.get.return_value = None

        result = nb_client.update_prefix(999, {"description": "x"})

        assert result is False

    def test_update_sets_scope_fields(self, nb_client):
        prefix_obj = MockRecord(10, prefix="10.0.0.0/24")
        prefix_obj.save.return_value = True
        nb_client.nb.ipam.prefixes.get.return_value = prefix_obj

        result = nb_client.update_prefix(10, {"scope_type": "dcim.site", "scope_id": 5})

        assert result is True
        assert prefix_obj.scope_type == "dcim.site"
        assert prefix_obj.scope_id == 5

    def test_update_clears_legacy_site_none(self, nb_client):
        prefix_obj = MockRecord(10, prefix="10.0.0.0/24", site=MockRecord(1, name="old-site"))
        prefix_obj.save.return_value = True
        nb_client.nb.ipam.prefixes.get.return_value = prefix_obj

        result = nb_client.update_prefix(10, {"site": None})

        assert result is True
        assert prefix_obj.site is None

    def test_fallback_to_update_method(self, nb_client):
        prefix_obj = MockRecord(10, prefix="10.0.0.0/24")
        prefix_obj.save.return_value = False  # save fails
        prefix_obj.update = MagicMock()
        nb_client.nb.ipam.prefixes.get.return_value = prefix_obj

        result = nb_client.update_prefix(10, {"description": "x"})

        assert result is True
        prefix_obj.update.assert_called_once_with({"description": "x"})

    def test_fallback_to_direct_api(self, nb_client):
        prefix_obj = MockRecord(10, prefix="10.0.0.0/24")
        prefix_obj.save.return_value = False
        # MockRecord has no update method by default, so hasattr returns False
        nb_client.nb.ipam.prefixes.get.return_value = prefix_obj

        # Mock the direct API call
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        nb_client.nb.http_session.patch.return_value = mock_response
        nb_client.nb.base_url = "https://netbox.example.com/api"
        nb_client.nb.token = "test-token"

        result = nb_client.update_prefix(10, {"description": "x"})

        assert result is True
        nb_client.nb.http_session.patch.assert_called_once()

    def test_all_methods_fail_returns_false(self, nb_client):
        prefix_obj = MockRecord(10, prefix="10.0.0.0/24")
        prefix_obj.save.return_value = False
        nb_client.nb.ipam.prefixes.get.return_value = prefix_obj

        # Direct API also fails
        nb_client.nb.http_session.patch.side_effect = Exception("network error")
        nb_client.nb.base_url = "https://netbox.example.com/api"
        nb_client.nb.token = "test-token"

        result = nb_client.update_prefix(10, {"description": "x"})

        assert result is False

    def test_permission_error_returns_false(self, nb_client):
        prefix_obj = MockRecord(10, prefix="10.0.0.0/24")
        prefix_obj.save.side_effect = Exception("403 Forbidden")
        nb_client.nb.ipam.prefixes.get.return_value = prefix_obj

        nb_client.nb.http_session.patch.side_effect = Exception("403 Forbidden")
        nb_client.nb.base_url = "https://netbox.example.com/api"
        nb_client.nb.token = "test-token"

        result = nb_client.update_prefix(10, {"description": "x"})

        assert result is False

    def test_general_exception_returns_false(self, nb_client):
        nb_client.nb.ipam.prefixes.get.side_effect = Exception("connection failed")

        result = nb_client.update_prefix(10, {"description": "x"})

        assert result is False
