"""Tests for NetBox tag management (NetBoxTagsMixin)."""

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


class TestEnsureSyncTag:
    def test_returns_cached_tag(self, nb_client):
        nb_client._sync_tag_id = 42
        result = nb_client.ensure_sync_tag()
        assert result == 42
        nb_client.nb.extras.tags.get.assert_not_called()

    def test_finds_existing_tag_by_name(self, nb_client):
        tag = MockRecord(10, name="synced-from-yc", slug="synced-from-yc")
        nb_client.nb.extras.tags.get.return_value = tag

        result = nb_client.ensure_sync_tag()

        assert result == 10
        assert nb_client._sync_tag_id == 10

    def test_finds_existing_tag_by_slug_fallback(self, nb_client):
        tag = MockRecord(11, name="synced-from-yc", slug="synced-from-yc")

        def get_side_effect(**kwargs):
            if 'name' in kwargs:
                raise Exception("not found")
            return tag

        nb_client.nb.extras.tags.get.side_effect = get_side_effect

        result = nb_client.ensure_sync_tag()

        assert result == 11

    def test_creates_tag_when_not_found(self, nb_client):
        nb_client.nb.extras.tags.get.return_value = None
        new_tag = MockRecord(20, name="synced-from-yc")
        nb_client.nb.extras.tags.create.return_value = new_tag

        result = nb_client.ensure_sync_tag()

        assert result == 20
        nb_client.nb.extras.tags.create.assert_called_once()
        call_args = nb_client.nb.extras.tags.create.call_args[0][0]
        assert call_args["name"] == "synced-from-yc"
        assert call_args["slug"] == "synced-from-yc"

    def test_dry_run_returns_mock_id(self, nb_client_dry_run):
        nb_client_dry_run.nb.extras.tags.get.return_value = None

        result = nb_client_dry_run.ensure_sync_tag()

        assert result >= 1_000_000
        nb_client_dry_run.nb.extras.tags.create.assert_not_called()

    def test_dry_run_unique_ids_per_slug(self, nb_client_dry_run):
        """Different tag slugs get distinct mock IDs in dry-run mode."""
        nb_client_dry_run.nb.extras.tags.get.return_value = None

        id_yc = nb_client_dry_run.ensure_sync_tag(
            tag_name="synced-from-yc", tag_slug="synced-from-yc",
        )
        id_vcloud = nb_client_dry_run.ensure_sync_tag(
            tag_name="synced-from-vcloud", tag_slug="synced-from-vcloud",
        )

        assert id_yc != id_vcloud
        assert id_yc >= 1_000_000
        assert id_vcloud >= 1_000_000

    def test_create_failure_returns_zero(self, nb_client):
        nb_client.nb.extras.tags.get.return_value = None
        nb_client.nb.extras.tags.create.side_effect = Exception("create failed")

        result = nb_client.ensure_sync_tag()

        assert result == 0

    def test_per_slug_cache_hit(self, nb_client):
        """Per-slug cache returns cached ID without API call."""
        nb_client._sync_tag_cache["synced-from-vcloud"] = 55

        result = nb_client.ensure_sync_tag(tag_slug="synced-from-vcloud")

        assert result == 55
        nb_client.nb.extras.tags.get.assert_not_called()

    def test_race_condition_slug_conflict(self, nb_client):
        """400 slug conflict during create falls back to get-by-slug."""
        nb_client.nb.extras.tags.create.side_effect = Exception("400 slug already exists")

        existing = MockRecord(33, name="synced-from-yc", slug="synced-from-yc")

        call_count = 0

        def get_side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            # First call: get-by-name returns None (tag not found)
            # Second call: retry get-by-slug after 400 returns existing tag
            if call_count <= 1:
                return None
            return existing

        nb_client.nb.extras.tags.get.side_effect = get_side_effect

        result = nb_client.ensure_sync_tag()

        assert result == 33


class TestAddTagToObject:
    def test_adds_tag(self, nb_client):
        obj = MockRecord(1, name="test", tags=[])
        result = nb_client._add_tag_to_object(obj, 5)
        assert result is True

    def test_skips_if_already_present(self, nb_client):
        tag = MockRecord(5, name="synced-from-yc")
        obj = MockRecord(1, name="test", tags=[tag])
        result = nb_client._add_tag_to_object(obj, 5)
        assert result is True

    def test_skips_in_dry_run(self, nb_client_dry_run):
        obj = MockRecord(1, name="test", tags=[])
        result = nb_client_dry_run._add_tag_to_object(obj, 5)
        assert result is False

    def test_skips_if_no_tag_id(self, nb_client):
        obj = MockRecord(1, name="test", tags=[])
        result = nb_client._add_tag_to_object(obj, 0)
        assert result is False

    def test_handles_none_tags(self, nb_client):
        """Object with tags=None doesn't crash."""
        obj = MockRecord(1, name="test", tags=None)
        result = nb_client._add_tag_to_object(obj, 5)
        assert result is True

    def test_handles_save_exception(self, nb_client):
        """Exception during save returns False."""
        obj = MockRecord(1, name="test", tags=[])
        obj.save.side_effect = Exception("API error")
        result = nb_client._add_tag_to_object(obj, 5)
        assert result is False


class TestTagMixinIntegration:
    """Verify mixin methods are accessible on NetBoxClient."""

    def test_ensure_sync_tag_is_method(self, nb_client):
        assert hasattr(nb_client, 'ensure_sync_tag')
        assert callable(nb_client.ensure_sync_tag)

    def test_add_tag_to_object_is_method(self, nb_client):
        assert hasattr(nb_client, '_add_tag_to_object')
        assert callable(nb_client._add_tag_to_object)

    def test_mixin_methods_come_from_netbox_tags(self):
        from infraverse.providers.netbox_tags import NetBoxTagsMixin
        assert issubclass(NetBoxClient, NetBoxTagsMixin)
