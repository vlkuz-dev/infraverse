"""Tests for NetBox infrastructure management (sites, clusters, platforms)."""

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


class TestSafeUpdateObject:
    def test_updates_changed_fields(self, nb_client):
        obj = MockRecord(1, name="old-name", status="inactive")
        result = nb_client._safe_update_object(obj, {"name": "new-name", "status": "active"})
        assert result is True
        assert obj.name == "new-name"
        obj.save.assert_called_once()

    def test_no_update_when_same(self, nb_client):
        obj = MockRecord(1, name="same")
        result = nb_client._safe_update_object(obj, {"name": "same"})
        assert result is False
        obj.save.assert_not_called()

    def test_empty_updates_returns_false(self, nb_client):
        obj = MockRecord(1, name="test")
        result = nb_client._safe_update_object(obj, {})
        assert result is False

    def test_dry_run_returns_false(self, nb_client_dry_run):
        obj = MockRecord(1, name="old")
        result = nb_client_dry_run._safe_update_object(obj, {"name": "new"})
        assert result is False

    def test_handles_choice_item_comparison(self, nb_client):
        """ChoiceItem objects (e.g., status) are compared by .value."""
        class MockChoiceItem:
            def __init__(self, value):
                self.value = value
        obj = MockRecord(1, name="test", status=MockChoiceItem("active"))
        result = nb_client._safe_update_object(obj, {"status": "active"})
        assert result is False
        obj.save.assert_not_called()

    def test_updates_choice_item_when_different(self, nb_client):
        """ChoiceItem objects trigger update when value differs."""
        class MockChoiceItem:
            def __init__(self, value):
                self.value = value
        obj = MockRecord(1, name="test", status=MockChoiceItem("planned"))
        result = nb_client._safe_update_object(obj, {"status": "active"})
        assert result is True
        obj.save.assert_called_once()

    def test_handles_object_with_id(self, nb_client):
        """Objects with .id attribute are compared by id."""
        ref = MockRecord(5, name="ref")
        obj = MockRecord(1, name="test", site=ref)
        result = nb_client._safe_update_object(obj, {"site": 5})
        assert result is False
        obj.save.assert_not_called()

    def test_updates_object_with_different_id(self, nb_client):
        """Objects with .id attribute trigger update when id differs."""
        ref = MockRecord(5, name="ref")
        obj = MockRecord(1, name="test", site=ref)
        result = nb_client._safe_update_object(obj, {"site": 10})
        assert result is True
        obj.save.assert_called_once()

    def test_save_exception_returns_false(self, nb_client):
        """If save() raises, return False gracefully."""
        obj = MockRecord(1, name="old")
        obj.save.side_effect = Exception("save failed")
        result = nb_client._safe_update_object(obj, {"name": "new"})
        assert result is False


class TestEnsureSite:
    def test_finds_existing_site_by_name(self, nb_client):
        nb_client._sync_tag_id = 1
        site = MockRecord(5, name="ru-central1-a", slug="ru-central1-a",
                          description="old", status="active", tags=[])
        nb_client.nb.dcim.sites.get.return_value = site

        result = nb_client.ensure_site("ru-central1-a")

        assert result == 5

    def test_creates_site_when_not_found(self, nb_client):
        nb_client._sync_tag_id = 1
        nb_client.nb.dcim.sites.get.return_value = None
        new_site = MockRecord(6, name="ru-central1-a")
        nb_client.nb.dcim.sites.create.return_value = new_site

        result = nb_client.ensure_site("ru-central1-a")

        assert result == 6
        call_args = nb_client.nb.dcim.sites.create.call_args[0][0]
        assert call_args["name"] == "ru-central1-a"
        assert call_args["slug"] == "ru-central1-a"
        assert call_args["status"] == "active"
        assert call_args["tags"] == [1]

    def test_uses_zone_name_when_provided(self, nb_client):
        nb_client._sync_tag_id = 1
        nb_client.nb.dcim.sites.get.return_value = None
        new_site = MockRecord(7, name="Zone A")
        nb_client.nb.dcim.sites.create.return_value = new_site

        result = nb_client.ensure_site("ru-central1-a", zone_name="Zone A")

        assert result == 7
        call_args = nb_client.nb.dcim.sites.create.call_args[0][0]
        assert call_args["name"] == "Zone A"
        # slug still derived from zone_id
        assert call_args["slug"] == "ru-central1-a"

    def test_dry_run_returns_mock_id(self, nb_client_dry_run):
        nb_client_dry_run.nb.dcim.sites.get.return_value = None

        result = nb_client_dry_run.ensure_site("ru-central1-a")

        assert result == 1
        nb_client_dry_run.nb.dcim.sites.create.assert_not_called()

    def test_handles_duplicate_slug_error(self, nb_client):
        nb_client._sync_tag_id = 1
        # First get returns None, create throws duplicate slug error
        nb_client.nb.dcim.sites.get.side_effect = [None, None, MockRecord(8, name="ru-central1-a")]
        nb_client.nb.dcim.sites.create.side_effect = Exception("400 slug already exists")

        result = nb_client.ensure_site("ru-central1-a")

        assert result == 8

    def test_custom_description_prefix(self, nb_client):
        nb_client._sync_tag_id = 1
        nb_client.nb.dcim.sites.get.return_value = None
        new_site = MockRecord(9, name="zone-a")
        nb_client.nb.dcim.sites.create.return_value = new_site

        result = nb_client.ensure_site("zone-a", description_prefix="vCloud Zone")

        assert result == 9
        call_args = nb_client.nb.dcim.sites.create.call_args[0][0]
        assert call_args["description"] == "vCloud Zone: zone-a"


class TestEnsureClusterType:
    def test_returns_cached_type(self, nb_client):
        nb_client._cluster_type_id = 99
        result = nb_client.ensure_cluster_type()
        assert result == 99

    def test_returns_per_slug_cached_type(self, nb_client):
        nb_client._cluster_type_cache["vcloud"] = 42
        result = nb_client.ensure_cluster_type(slug="vcloud")
        assert result == 42

    def test_finds_existing_by_name(self, nb_client):
        nb_client._sync_tag_id = 1
        ct = MockRecord(3, name="yandex-cloud", slug="yandex-cloud",
                        description="Yandex Cloud Platform", tags=[])
        nb_client.nb.virtualization.cluster_types.get.return_value = ct

        result = nb_client.ensure_cluster_type()

        assert result == 3
        assert nb_client._cluster_type_id == 3

    def test_creates_when_not_found(self, nb_client):
        nb_client._sync_tag_id = 1
        nb_client.nb.virtualization.cluster_types.get.return_value = None
        new_ct = MockRecord(4, name="yandex-cloud")
        nb_client.nb.virtualization.cluster_types.create.return_value = new_ct

        result = nb_client.ensure_cluster_type()

        assert result == 4

    def test_dry_run_returns_mock_id(self, nb_client_dry_run):
        nb_client_dry_run.nb.virtualization.cluster_types.get.return_value = None

        result = nb_client_dry_run.ensure_cluster_type()

        assert result == 1_000_000
        nb_client_dry_run.nb.virtualization.cluster_types.create.assert_not_called()

    def test_custom_slug_cached_separately(self, nb_client):
        nb_client._sync_tag_id = 1
        ct = MockRecord(10, name="vcloud", slug="vcloud",
                        description="vCloud", tags=[])
        nb_client.nb.virtualization.cluster_types.get.return_value = ct

        result = nb_client.ensure_cluster_type(name="vcloud", slug="vcloud", description="vCloud")

        assert result == 10
        assert nb_client._cluster_type_cache["vcloud"] == 10
        # Should NOT set the backward compat scalar
        assert nb_client._cluster_type_id is None


class TestEnsureCluster:
    def test_finds_existing_cluster_by_new_name(self, nb_client):
        """Cluster found by new name format (cloud/folder) -- no migration."""
        nb_client._sync_tag_id = 1
        nb_client._cluster_type_id = 2
        cluster = MockRecord(10, name="my-cloud/prod", tags=[],
                             type=MockRecord(2), site=None,
                             comments="Folder ID: folder1")
        nb_client.nb.virtualization.clusters.get.return_value = cluster

        result = nb_client.ensure_cluster("prod", "folder1", "my-cloud")

        assert result == 10

    def test_finds_existing_cluster_by_old_name_and_migrates(self, nb_client):
        """Cluster found by old name (folder only) via filter() -- renamed to new format."""
        nb_client._sync_tag_id = 1
        nb_client._cluster_type_id = 2
        old_cluster = MockRecord(15, name="prod-devops", tags=[],
                                 type=MockRecord(2), site=None, comments="")

        def get_side_effect(**kwargs):
            return None

        nb_client.nb.virtualization.clusters.get.side_effect = get_side_effect
        nb_client.nb.virtualization.clusters.filter.return_value = [old_cluster]

        result = nb_client.ensure_cluster("prod-devops", "b1gn93aeri4145duf1qt", "grand-trade")

        assert result == 15
        assert old_cluster.name == "grand-trade/prod-devops"
        assert old_cluster.slug == "grand-trade-prod-devops"
        old_cluster.save.assert_called()
        nb_client.nb.virtualization.clusters.filter.assert_called_with(name="prod-devops")

    def test_finds_existing_cluster_by_slug(self, nb_client):
        """Cluster found by slug when name lookup fails."""
        nb_client._sync_tag_id = 1
        nb_client._cluster_type_id = 2
        cluster = MockRecord(20, name="grand-trade/infra", slug="grand-trade-infra",
                             tags=[], type=MockRecord(2), site=None, comments="")

        def get_side_effect(**kwargs):
            if kwargs.get("name") == "grand-trade/infra":
                return None
            if kwargs.get("slug") == "grand-trade-infra":
                return cluster
            return None

        nb_client.nb.virtualization.clusters.get.side_effect = get_side_effect

        result = nb_client.ensure_cluster("infra", "folder-id", "grand-trade")

        assert result == 20

    def test_creates_cluster_when_not_found(self, nb_client):
        nb_client._sync_tag_id = 1
        nb_client._cluster_type_id = 2
        nb_client.nb.virtualization.clusters.get.return_value = None
        nb_client.nb.virtualization.clusters.filter.return_value = []
        new_cluster = MockRecord(11, name="my-cloud/staging")
        nb_client.nb.virtualization.clusters.create.return_value = new_cluster

        result = nb_client.ensure_cluster("staging", "folder2", "my-cloud", site_id=5)

        assert result == 11
        call_args = nb_client.nb.virtualization.clusters.create.call_args[0][0]
        assert call_args["name"] == "my-cloud/staging"
        assert call_args["type"] == 2
        assert call_args["site"] == 5

    def test_creates_cluster_without_cloud_name(self, nb_client):
        """When cloud_name is empty, uses folder_name only -- no fallback needed."""
        nb_client._sync_tag_id = 1
        nb_client._cluster_type_id = 2
        nb_client.nb.virtualization.clusters.get.return_value = None
        new_cluster = MockRecord(12, name="standalone")
        nb_client.nb.virtualization.clusters.create.return_value = new_cluster

        result = nb_client.ensure_cluster("standalone", "folder3", "")

        assert result == 12
        call_args = nb_client.nb.virtualization.clusters.create.call_args[0][0]
        assert call_args["name"] == "standalone"

    def test_dry_run_not_found(self, nb_client_dry_run):
        """Dry-run when cluster doesn't exist -- returns mock ID."""
        nb_client_dry_run.nb.virtualization.clusters.get.return_value = None
        nb_client_dry_run.nb.virtualization.clusters.filter.return_value = []

        result = nb_client_dry_run.ensure_cluster("prod", "f1", "cloud1")

        assert result == 1

    def test_dry_run_found_by_old_name(self, nb_client_dry_run):
        """Dry-run finds cluster by old name via filter() -- returns real ID, no rename."""
        nb_client_dry_run._sync_tag_id = 1
        nb_client_dry_run._cluster_type_id = 2
        old_cluster = MockRecord(25, name="prod", tags=[],
                                 type=MockRecord(2), site=None, comments="")

        def get_side_effect(**kwargs):
            return None

        nb_client_dry_run.nb.virtualization.clusters.get.side_effect = get_side_effect
        nb_client_dry_run.nb.virtualization.clusters.filter.return_value = [old_cluster]

        result = nb_client_dry_run.ensure_cluster("prod", "f1", "cloud1")

        assert result == 25
        # Dry-run should NOT rename
        assert old_cluster.name == "prod"
        old_cluster.save.assert_not_called()


class TestEnsurePlatform:
    def test_finds_existing_platform(self, nb_client):
        platform = MockRecord(5, name="Ubuntu 22.04", slug="ubuntu-22-04")
        nb_client.nb.dcim.platforms.get.return_value = platform

        result = nb_client.ensure_platform("ubuntu-22-04")

        assert result == 5
        nb_client.nb.dcim.platforms.get.assert_called_with(slug="ubuntu-22-04")

    def test_creates_platform_when_not_found(self, nb_client):
        nb_client.nb.dcim.platforms.get.return_value = None
        new_platform = MockRecord(6, name="windows-2022", slug="windows-2022")
        nb_client.nb.dcim.platforms.create.return_value = new_platform

        result = nb_client.ensure_platform("windows-2022", "Windows Server 2022")

        assert result == 6
        call_args = nb_client.nb.dcim.platforms.create.call_args[0][0]
        assert call_args["name"] == "Windows Server 2022"
        assert call_args["slug"] == "windows-2022"

    def test_dry_run(self, nb_client_dry_run):
        nb_client_dry_run.nb.dcim.platforms.get.return_value = None

        result = nb_client_dry_run.ensure_platform("linux")

        assert result == 1
        nb_client_dry_run.nb.dcim.platforms.create.assert_not_called()

    def test_slug_used_as_name_when_no_name(self, nb_client):
        nb_client.nb.dcim.platforms.get.return_value = None
        new_platform = MockRecord(7, name="linux", slug="linux")
        nb_client.nb.dcim.platforms.create.return_value = new_platform

        result = nb_client.ensure_platform("linux")

        assert result == 7
        call_args = nb_client.nb.dcim.platforms.create.call_args[0][0]
        assert call_args["name"] == "linux"

    def test_handles_duplicate_slug_error(self, nb_client):
        nb_client.nb.dcim.platforms.get.side_effect = [None, MockRecord(8, slug="centos")]
        nb_client.nb.dcim.platforms.create.side_effect = Exception("400 slug exists")

        result = nb_client.ensure_platform("centos")

        assert result == 8


class TestEnsureTenant:
    """Tests for ensure_tenant() — success cases."""

    def test_finds_existing_tenant_by_name(self, nb_client):
        nb_client._sync_tag_id = 1
        tenant = MockRecord(10, name="acme-corp", slug="acme-corp",
                            description="ACME Corporation", tags=[])
        nb_client.nb.tenancy.tenants.get.return_value = tenant

        result = nb_client.ensure_tenant("acme-corp")

        assert result == 10
        assert nb_client._tenant_cache["acme-corp"] == 10

    def test_finds_existing_tenant_by_slug(self, nb_client):
        nb_client._sync_tag_id = 1
        tenant = MockRecord(11, name="Beta Inc", slug="beta-inc",
                            description="Beta Inc", tags=[])

        def get_side_effect(**kwargs):
            if kwargs.get("name"):
                return None
            if kwargs.get("slug") == "beta-inc":
                return tenant
            return None

        nb_client.nb.tenancy.tenants.get.side_effect = get_side_effect

        result = nb_client.ensure_tenant("Beta Inc", slug="beta-inc")

        assert result == 11
        assert nb_client._tenant_cache["beta-inc"] == 11

    def test_creates_new_tenant(self, nb_client):
        nb_client._sync_tag_id = 1
        nb_client.nb.tenancy.tenants.get.return_value = None
        new_tenant = MockRecord(12, name="new-tenant", slug="new-tenant")
        nb_client.nb.tenancy.tenants.create.return_value = new_tenant

        result = nb_client.ensure_tenant("new-tenant", description="New Tenant Corp")

        assert result == 12
        assert nb_client._tenant_cache["new-tenant"] == 12
        call_args = nb_client.nb.tenancy.tenants.create.call_args[0][0]
        assert call_args["name"] == "new-tenant"
        assert call_args["slug"] == "new-tenant"
        assert call_args["description"] == "New Tenant Corp"
        assert call_args["tags"] == [1]

    def test_creates_tenant_without_description(self, nb_client):
        nb_client._sync_tag_id = 1
        nb_client.nb.tenancy.tenants.get.return_value = None
        new_tenant = MockRecord(13, name="simple-tenant")
        nb_client.nb.tenancy.tenants.create.return_value = new_tenant

        result = nb_client.ensure_tenant("simple-tenant")

        assert result == 13
        call_args = nb_client.nb.tenancy.tenants.create.call_args[0][0]
        assert "description" not in call_args

    def test_dry_run_returns_mock_id(self, nb_client_dry_run):
        nb_client_dry_run.nb.tenancy.tenants.get.return_value = None

        result = nb_client_dry_run.ensure_tenant("dry-tenant")

        assert result == 1_000_000
        assert nb_client_dry_run._tenant_cache["dry-tenant"] == 1_000_000
        nb_client_dry_run.nb.tenancy.tenants.create.assert_not_called()

    def test_returns_cached_id(self, nb_client):
        nb_client._tenant_cache["cached-tenant"] = 99

        result = nb_client.ensure_tenant("cached-tenant")

        assert result == 99
        nb_client.nb.tenancy.tenants.get.assert_not_called()

    def test_slug_defaults_to_name(self, nb_client):
        nb_client._sync_tag_id = 1
        nb_client.nb.tenancy.tenants.get.return_value = None
        new_tenant = MockRecord(14, name="my-tenant")
        nb_client.nb.tenancy.tenants.create.return_value = new_tenant

        nb_client.ensure_tenant("my-tenant")

        call_args = nb_client.nb.tenancy.tenants.create.call_args[0][0]
        assert call_args["slug"] == "my-tenant"

    def test_custom_slug(self, nb_client):
        nb_client._sync_tag_id = 1
        nb_client.nb.tenancy.tenants.get.return_value = None
        new_tenant = MockRecord(15, name="My Tenant")
        nb_client.nb.tenancy.tenants.create.return_value = new_tenant

        nb_client.ensure_tenant("My Tenant", slug="my-tenant")

        call_args = nb_client.nb.tenancy.tenants.create.call_args[0][0]
        assert call_args["name"] == "My Tenant"
        assert call_args["slug"] == "my-tenant"
        assert nb_client._tenant_cache["my-tenant"] == 15


class TestEnsureTenantErrors:
    """Tests for ensure_tenant() — error/edge cases."""

    def test_duplicate_slug_retry_succeeds(self, nb_client):
        nb_client._sync_tag_id = 1
        # First lookups return None, create throws duplicate slug error
        nb_client.nb.tenancy.tenants.get.side_effect = [
            None, None,  # initial lookup by name, by slug
            MockRecord(20, name="dup-tenant", slug="dup-tenant"),  # retry after error
        ]
        nb_client.nb.tenancy.tenants.create.side_effect = Exception("400 slug already exists")

        result = nb_client.ensure_tenant("dup-tenant")

        assert result == 20
        assert nb_client._tenant_cache["dup-tenant"] == 20

    def test_description_updated_on_existing_tenant(self, nb_client):
        nb_client._sync_tag_id = 1
        # tags=[1] so _add_tag_to_object won't call save (tag already present)
        tenant = MockRecord(10, name="acme-corp", slug="acme-corp",
                            description="Old Description", tags=[MockRecord(1)])
        nb_client.nb.tenancy.tenants.get.return_value = tenant

        result = nb_client.ensure_tenant("acme-corp", description="New Description")

        assert result == 10
        # Verify save was called exactly once (description update only)
        tenant.save.assert_called_once()
        assert tenant.description == "New Description"

    def test_description_not_updated_when_same(self, nb_client):
        nb_client._sync_tag_id = 1
        tenant = MockRecord(10, name="acme-corp", slug="acme-corp",
                            description="Same Description", tags=[MockRecord(1)])
        nb_client.nb.tenancy.tenants.get.return_value = tenant

        result = nb_client.ensure_tenant("acme-corp", description="Same Description")

        assert result == 10
        tenant.save.assert_not_called()

    def test_no_description_update_when_none_provided(self, nb_client):
        nb_client._sync_tag_id = 1
        tenant = MockRecord(10, name="acme-corp", slug="acme-corp",
                            description="Existing", tags=[MockRecord(1)])
        nb_client.nb.tenancy.tenants.get.return_value = tenant

        result = nb_client.ensure_tenant("acme-corp")

        assert result == 10
        tenant.save.assert_not_called()

    def test_create_failure_non_duplicate_raises(self, nb_client):
        nb_client._sync_tag_id = 1
        nb_client.nb.tenancy.tenants.get.return_value = None
        nb_client.nb.tenancy.tenants.create.side_effect = Exception("500 server error")

        with pytest.raises(Exception, match="500 server error"):
            nb_client.ensure_tenant("fail-tenant")

    def test_dry_run_increments_mock_ids(self, nb_client_dry_run):
        nb_client_dry_run.nb.tenancy.tenants.get.return_value = None

        id1 = nb_client_dry_run.ensure_tenant("tenant-a")
        id2 = nb_client_dry_run.ensure_tenant("tenant-b")

        assert id1 == 1_000_000
        assert id2 == 1_000_001

    def test_create_without_tag(self, nb_client):
        """When no sync tag is configured, tenant is created without tags."""
        nb_client._sync_tag_id = None
        nb_client.nb.tenancy.tenants.get.return_value = None
        # ensure_sync_tag returns None when no tag configured
        nb_client.ensure_sync_tag = MagicMock(return_value=None)
        new_tenant = MockRecord(16, name="no-tag-tenant")
        nb_client.nb.tenancy.tenants.create.return_value = new_tenant

        result = nb_client.ensure_tenant("no-tag-tenant")

        assert result == 16
        call_args = nb_client.nb.tenancy.tenants.create.call_args[0][0]
        assert "tags" not in call_args


class TestEnsureTenantSlugSanitization:
    """Tests for ensure_tenant() slug handling."""

    def test_underscores_replaced_with_hyphens(self, nb_client):
        nb_client._sync_tag_id = 1
        nb_client.nb.tenancy.tenants.get.return_value = None
        new_tenant = MockRecord(20, name="tenant_with_underscores")
        nb_client.nb.tenancy.tenants.create.return_value = new_tenant

        nb_client.ensure_tenant("tenant_with_underscores")

        call_args = nb_client.nb.tenancy.tenants.create.call_args[0][0]
        assert call_args["slug"] == "tenant-with-underscores"

    def test_uppercase_lowered(self, nb_client):
        nb_client._sync_tag_id = 1
        nb_client.nb.tenancy.tenants.get.return_value = None
        new_tenant = MockRecord(21, name="My Tenant")
        nb_client.nb.tenancy.tenants.create.return_value = new_tenant

        nb_client.ensure_tenant("My Tenant")

        call_args = nb_client.nb.tenancy.tenants.create.call_args[0][0]
        assert call_args["slug"] == "my-tenant"

    def test_empty_slug_raises(self, nb_client):
        with pytest.raises(ValueError, match="Cannot derive a valid slug"):
            nb_client.ensure_tenant("")

    def test_valueerror_on_name_lookup_falls_through(self, nb_client):
        """pynetbox .get() raises ValueError on multiple results; should fall through."""
        nb_client._sync_tag_id = 1
        tenant = MockRecord(22, name="dup-name", slug="dup-name", tags=[])

        def get_side_effect(**kwargs):
            if kwargs.get("name"):
                raise ValueError("get() returned more than one result")
            if kwargs.get("slug") == "dup-name":
                return tenant
            return None

        nb_client.nb.tenancy.tenants.get.side_effect = get_side_effect

        result = nb_client.ensure_tenant("dup-name")

        assert result == 22


class TestMixinResolution:
    """Verify that infrastructure methods are accessible via NetBoxClient."""

    def test_has_safe_update_object(self, nb_client):
        assert hasattr(nb_client, '_safe_update_object')

    def test_has_ensure_site(self, nb_client):
        assert hasattr(nb_client, 'ensure_site')

    def test_has_ensure_cluster_type(self, nb_client):
        assert hasattr(nb_client, 'ensure_cluster_type')

    def test_has_ensure_cluster(self, nb_client):
        assert hasattr(nb_client, 'ensure_cluster')

    def test_has_ensure_platform(self, nb_client):
        assert hasattr(nb_client, 'ensure_platform')

    def test_has_ensure_tenant(self, nb_client):
        assert hasattr(nb_client, 'ensure_tenant')
