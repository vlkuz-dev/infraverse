"""Tests for infraverse.sync.cleanup module."""


from infraverse.sync.cleanup import (
    cleanup_orphaned_infrastructure,
    cleanup_orphaned_vms,
    _extract_cloud_names,
)
from infraverse.sync.provider_profile import VCLOUD_PROFILE
from tests.conftest import MockRecord, MockTag, make_mock_netbox_client


class TestCleanupOrphanedInfrastructure:
    """Tests for cleanup_orphaned_infrastructure."""

    def test_no_orphaned_objects(self):
        """When all NetBox objects exist in YC, nothing is deleted."""
        netbox = make_mock_netbox_client()
        yc_data = {
            "zones": [{"id": "ru-central1-a"}],
            "folders": [{"id": "folder-1"}],
            "subnets": [{"id": "subnet-1"}],
        }
        # No objects in NetBox
        netbox.nb.dcim.sites.all.return_value = []
        netbox.nb.virtualization.clusters.all.return_value = []
        netbox.nb.ipam.prefixes.all.return_value = []

        result = cleanup_orphaned_infrastructure(yc_data, netbox)

        assert result == {"sites": 0, "clusters": 0, "prefixes": 0}

    def test_deletes_orphaned_site(self):
        """Sites with sync tag that don't exist in YC zones are deleted."""
        netbox = make_mock_netbox_client()
        yc_data = {"zones": [{"id": "ru-central1-a"}], "folders": [], "subnets": []}

        orphaned_site = MockRecord(
            id=1,
            name="old-zone",
            slug="ru-central1-z",
            tags=[MockTag(id=1)],
            comments="",
            description="Yandex Cloud Availability Zone: ru-central1-z",
        )
        netbox.nb.dcim.sites.all.return_value = [orphaned_site]
        netbox.nb.virtualization.clusters.all.return_value = []
        netbox.nb.ipam.prefixes.all.return_value = []

        result = cleanup_orphaned_infrastructure(yc_data, netbox, dry_run=False)

        assert result["sites"] == 1
        orphaned_site.delete.assert_called_once()

    def test_keeps_valid_site(self):
        """Sites whose zone exists in YC are not deleted."""
        netbox = make_mock_netbox_client()
        yc_data = {"zones": [{"id": "ru-central1-a"}], "folders": [], "subnets": []}

        valid_site = MockRecord(
            id=1,
            name="ru-central1-a",
            slug="ru-central1-a",
            tags=[MockTag(id=1)],
            comments="",
            description="Yandex Cloud Availability Zone: ru-central1-a",
        )
        netbox.nb.dcim.sites.all.return_value = [valid_site]
        netbox.nb.virtualization.clusters.all.return_value = []
        netbox.nb.ipam.prefixes.all.return_value = []

        result = cleanup_orphaned_infrastructure(yc_data, netbox)

        assert result["sites"] == 0
        valid_site.delete.assert_not_called()

    def test_deletes_orphaned_cluster(self):
        """Clusters with sync tag and missing folder ID are deleted."""
        netbox = make_mock_netbox_client()
        yc_data = {"zones": [], "folders": [{"id": "folder-1"}], "subnets": []}

        orphaned_cluster = MockRecord(
            id=2,
            name="old-folder",
            tags=[MockTag(id=1)],
            comments="Folder ID: folder-gone",
        )
        netbox.nb.dcim.sites.all.return_value = []
        netbox.nb.virtualization.clusters.all.return_value = [orphaned_cluster]
        netbox.nb.ipam.prefixes.all.return_value = []

        result = cleanup_orphaned_infrastructure(yc_data, netbox, dry_run=False)

        assert result["clusters"] == 1
        orphaned_cluster.delete.assert_called_once()

    def test_deletes_orphaned_prefix(self):
        """Prefixes with sync tag whose CIDR is no longer in YC subnets are deleted."""
        netbox = make_mock_netbox_client()
        yc_data = {"zones": [], "folders": [], "subnets": [{"id": "subnet-1", "cidr": "10.0.0.0/24"}]}

        orphaned_prefix = MockRecord(
            id=3,
            prefix="10.99.0.0/24",
            tags=[MockTag(id=1)],
            description="VPC: test-vpc",
        )
        netbox.nb.dcim.sites.all.return_value = []
        netbox.nb.virtualization.clusters.all.return_value = []
        netbox.nb.ipam.prefixes.all.return_value = [orphaned_prefix]

        result = cleanup_orphaned_infrastructure(yc_data, netbox, dry_run=False)

        assert result["prefixes"] == 1
        orphaned_prefix.delete.assert_called_once()

    def test_dry_run_no_deletion(self):
        """In dry-run mode, orphaned objects are logged but not deleted."""
        netbox = make_mock_netbox_client()
        yc_data = {"zones": [], "folders": [], "subnets": []}

        orphaned_site = MockRecord(
            id=1,
            name="old-zone",
            slug="ru-central1-z",
            tags=[MockTag(id=1)],
            comments="",
            description="Yandex Cloud Availability Zone: ru-central1-z",
        )
        netbox.nb.dcim.sites.all.return_value = [orphaned_site]
        netbox.nb.virtualization.clusters.all.return_value = []
        netbox.nb.ipam.prefixes.all.return_value = []

        result = cleanup_orphaned_infrastructure(yc_data, netbox, dry_run=True)

        assert result["sites"] == 1  # counts what would be deleted
        orphaned_site.delete.assert_not_called()

    def test_site_without_slug_or_description_not_deleted(self):
        """Sites without slug or description are not deleted even with sync tag."""
        netbox = make_mock_netbox_client()
        yc_data = {"zones": [], "folders": [], "subnets": []}

        site_no_slug = MockRecord(
            id=1,
            name="mystery-site",
            slug="",
            tags=[MockTag(id=1)],
            comments="",
            description="",
        )
        netbox.nb.dcim.sites.all.return_value = [site_no_slug]
        netbox.nb.virtualization.clusters.all.return_value = []
        netbox.nb.ipam.prefixes.all.return_value = []

        result = cleanup_orphaned_infrastructure(yc_data, netbox)

        assert result["sites"] == 0

    def test_site_without_sync_tag_not_deleted(self):
        """Sites without the sync tag are never deleted."""
        netbox = make_mock_netbox_client()
        yc_data = {"zones": [], "folders": [], "subnets": []}

        site_no_tag = MockRecord(
            id=1,
            name="untagged-site",
            slug="gone-zone",
            tags=[],
            comments="",
            description="Yandex Cloud Availability Zone: gone-zone",
        )
        netbox.nb.dcim.sites.all.return_value = [site_no_tag]
        netbox.nb.virtualization.clusters.all.return_value = []
        netbox.nb.ipam.prefixes.all.return_value = []

        result = cleanup_orphaned_infrastructure(yc_data, netbox)

        assert result["sites"] == 0

    def test_exception_during_cleanup_returns_zero_counts(self):
        """If ensure_sync_tag raises, return zero counts gracefully."""
        netbox = make_mock_netbox_client()
        netbox.ensure_sync_tag.side_effect = Exception("API down")
        yc_data = {"zones": [], "folders": [], "subnets": []}

        result = cleanup_orphaned_infrastructure(yc_data, netbox)

        assert result == {"sites": 0, "clusters": 0, "prefixes": 0}

    def test_delete_failure_continues(self):
        """If deleting one object fails, cleanup continues with the rest."""
        netbox = make_mock_netbox_client()
        yc_data = {"zones": [], "folders": [], "subnets": []}

        site1 = MockRecord(id=1, name="s1", slug="z1", tags=[MockTag(id=1)], comments="", description="")
        site1.delete.side_effect = Exception("Cannot delete")
        site2 = MockRecord(id=2, name="s2", slug="z2", tags=[MockTag(id=1)], comments="", description="")

        netbox.nb.dcim.sites.all.return_value = [site1, site2]
        netbox.nb.virtualization.clusters.all.return_value = []
        netbox.nb.ipam.prefixes.all.return_value = []

        result = cleanup_orphaned_infrastructure(yc_data, netbox, dry_run=False)

        # site1 failed to delete, site2 succeeded
        assert result["sites"] == 1
        site1.delete.assert_called_once()
        site2.delete.assert_called_once()


class TestCleanupOrphanedVMs:
    """Tests for cleanup_orphaned_vms."""

    def test_no_orphaned_vms(self):
        """When all NetBox VMs exist in YC, nothing is deleted."""
        netbox = make_mock_netbox_client()
        yc_vms = [{"name": "vm-1"}, {"name": "vm-2"}]

        vm1 = MockRecord(id=1, name="vm-1", tags=[MockTag(id=1)])
        vm2 = MockRecord(id=2, name="vm-2", tags=[MockTag(id=1)])
        netbox.fetch_vms.return_value = [vm1, vm2]

        result = cleanup_orphaned_vms(yc_vms, netbox)

        assert result == 0

    def test_deletes_orphaned_vm(self):
        """VMs with sync tag not in YC list are deleted."""
        netbox = make_mock_netbox_client()
        yc_vms = [{"name": "vm-1"}]

        vm1 = MockRecord(id=1, name="vm-1", tags=[MockTag(id=1)])
        vm_orphan = MockRecord(id=2, name="vm-gone", tags=[MockTag(id=1)])
        netbox.fetch_vms.return_value = [vm1, vm_orphan]

        result = cleanup_orphaned_vms(yc_vms, netbox, dry_run=False)

        assert result == 1
        vm_orphan.delete.assert_called_once()
        vm1.delete.assert_not_called()

    def test_vm_without_sync_tag_not_deleted(self):
        """VMs without the sync tag are never deleted."""
        netbox = make_mock_netbox_client()
        yc_vms = []

        vm_untagged = MockRecord(id=1, name="manual-vm", tags=[])
        netbox.fetch_vms.return_value = [vm_untagged]

        result = cleanup_orphaned_vms(yc_vms, netbox, dry_run=False)

        assert result == 0
        vm_untagged.delete.assert_not_called()

    def test_dry_run_no_deletion(self):
        """In dry-run mode, orphaned VMs are not deleted."""
        netbox = make_mock_netbox_client()
        yc_vms = []

        vm_orphan = MockRecord(id=1, name="vm-orphan", tags=[MockTag(id=1)])
        netbox.fetch_vms.return_value = [vm_orphan]

        result = cleanup_orphaned_vms(yc_vms, netbox, dry_run=True)

        assert result == 1  # counts what would be deleted
        vm_orphan.delete.assert_not_called()

    def test_empty_yc_list_deletes_all_tagged(self):
        """If YC returns no VMs, all tagged VMs are orphaned."""
        netbox = make_mock_netbox_client()
        yc_vms = []

        vm1 = MockRecord(id=1, name="vm-1", tags=[MockTag(id=1)])
        vm2 = MockRecord(id=2, name="vm-2", tags=[MockTag(id=1)])
        netbox.fetch_vms.return_value = [vm1, vm2]

        result = cleanup_orphaned_vms(yc_vms, netbox, dry_run=False)

        assert result == 2

    def test_cleanup_ignores_other_provider_vms(self):
        """VCloud cleanup must not delete VMs tagged with YC sync tag."""
        yc_tag_id = 5
        vcloud_tag_id = 7

        netbox = make_mock_netbox_client()
        netbox.ensure_sync_tag.return_value = vcloud_tag_id

        # NetBox has YC VMs (tag=5) and one vCloud orphan (tag=7)
        yc_vm = MockRecord(id=1, name="yc-web-01", tags=[MockTag(id=yc_tag_id)])
        yc_vm2 = MockRecord(id=2, name="yc-db-01", tags=[MockTag(id=yc_tag_id)])
        vcloud_orphan = MockRecord(id=3, name="vcloud-old", tags=[MockTag(id=vcloud_tag_id)])
        vcloud_active = MockRecord(id=4, name="vcloud-active", tags=[MockTag(id=vcloud_tag_id)])
        netbox.fetch_vms.return_value = [yc_vm, yc_vm2, vcloud_orphan, vcloud_active]

        # vCloud source only has vcloud-active
        vcloud_vms = [{"name": "vcloud-active"}]

        result = cleanup_orphaned_vms(
            vcloud_vms, netbox, dry_run=False, provider_profile=VCLOUD_PROFILE,
        )

        assert result == 1  # only vcloud-old
        vcloud_orphan.delete.assert_called_once()
        yc_vm.delete.assert_not_called()
        yc_vm2.delete.assert_not_called()
        vcloud_active.delete.assert_not_called()

    def test_exception_during_vm_cleanup_returns_zero(self):
        """If fetch_vms raises, return 0 gracefully."""
        netbox = make_mock_netbox_client()
        netbox.fetch_vms.side_effect = Exception("API error")

        result = cleanup_orphaned_vms([], netbox)

        assert result == 0


class TestCloudNameScoping:
    """Tests for multi-account cleanup scoping by cloud_name."""

    def test_extract_cloud_names(self):
        """_extract_cloud_names pulls cloud_name from folders."""
        yc_data = {
            "folders": [
                {"id": "f1", "cloud_name": "cloud-alpha"},
                {"id": "f2", "cloud_name": "cloud-beta"},
                {"id": "f3"},  # no cloud_name
            ]
        }
        assert _extract_cloud_names(yc_data) == {"cloud-alpha", "cloud-beta"}

    def test_extract_cloud_names_empty_when_no_cloud_name(self):
        """Returns empty set when folders lack cloud_name — backward compat."""
        yc_data = {"folders": [{"id": "f1"}, {"id": "f2"}]}
        assert _extract_cloud_names(yc_data) == set()

    def test_cluster_cleanup_scoped_by_cloud_name(self):
        """Cluster from another cloud is NOT deleted."""
        netbox = make_mock_netbox_client()
        yc_data = {
            "zones": [],
            "folders": [{"id": "folder-1", "cloud_name": "cloud-alpha"}],
            "subnets": [],
        }

        # Cluster belongs to cloud-beta (different account)
        other_cloud_cluster = MockRecord(
            id=1,
            name="cloud-beta/some-folder",
            tags=[MockTag(id=1)],
            comments="Folder ID: folder-other",
        )
        netbox.nb.dcim.sites.all.return_value = []
        netbox.nb.virtualization.clusters.all.return_value = [other_cloud_cluster]
        netbox.nb.ipam.prefixes.all.return_value = []

        result = cleanup_orphaned_infrastructure(yc_data, netbox, dry_run=False)

        assert result["clusters"] == 0
        other_cloud_cluster.delete.assert_not_called()

    def test_cluster_cleanup_deletes_orphaned_in_own_cloud(self):
        """Cluster in own cloud IS deleted when orphaned."""
        netbox = make_mock_netbox_client()
        yc_data = {
            "zones": [],
            "folders": [{"id": "folder-1", "cloud_name": "cloud-alpha"}],
            "subnets": [],
        }

        # Cluster belongs to cloud-alpha but folder is gone
        orphan_cluster = MockRecord(
            id=1,
            name="cloud-alpha/dead-folder",
            tags=[MockTag(id=1)],
            comments="Folder ID: folder-gone",
        )
        netbox.nb.dcim.sites.all.return_value = []
        netbox.nb.virtualization.clusters.all.return_value = [orphan_cluster]
        netbox.nb.ipam.prefixes.all.return_value = []

        result = cleanup_orphaned_infrastructure(yc_data, netbox, dry_run=False)

        assert result["clusters"] == 1
        orphan_cluster.delete.assert_called_once()

    def test_vm_cleanup_scoped_by_cloud_name(self):
        """VM in another cloud's cluster is NOT deleted."""
        netbox = make_mock_netbox_client()

        other_cluster = MockRecord(id=10, name="cloud-beta/folder-x")
        vm_other = MockRecord(
            id=1, name="vm-other", tags=[MockTag(id=1)], cluster=other_cluster,
        )
        netbox.fetch_vms.return_value = [vm_other]

        result = cleanup_orphaned_vms(
            [], netbox, dry_run=False, cloud_names={"cloud-alpha"},
        )

        assert result == 0
        vm_other.delete.assert_not_called()

    def test_vm_cleanup_skips_vm_without_cluster(self):
        """VM with no cluster is NOT deleted when cloud_names is set."""
        netbox = make_mock_netbox_client()

        vm_no_cluster = MockRecord(
            id=1, name="vm-no-cluster", tags=[MockTag(id=1)], cluster=None,
        )
        netbox.fetch_vms.return_value = [vm_no_cluster]

        result = cleanup_orphaned_vms(
            [], netbox, dry_run=False, cloud_names={"cloud-alpha"},
        )

        assert result == 0
        vm_no_cluster.delete.assert_not_called()

    def test_prefix_cleanup_skipped_in_multi_account(self):
        """Prefixes are not deleted when cloud_names is non-empty."""
        netbox = make_mock_netbox_client()
        yc_data = {
            "zones": [],
            "folders": [{"id": "f1", "cloud_name": "cloud-alpha"}],
            "subnets": [],  # no subnets — would trigger delete in global mode
        }

        orphaned_prefix = MockRecord(
            id=1,
            prefix="10.99.0.0/24",
            tags=[MockTag(id=1)],
            description="VPC: test",
        )
        netbox.nb.dcim.sites.all.return_value = []
        netbox.nb.virtualization.clusters.all.return_value = []
        netbox.nb.ipam.prefixes.all.return_value = [orphaned_prefix]

        result = cleanup_orphaned_infrastructure(yc_data, netbox, dry_run=False)

        assert result["prefixes"] == 0
        orphaned_prefix.delete.assert_not_called()

    def test_no_cloud_name_falls_back_to_global(self):
        """When folders lack cloud_name, existing global behavior is preserved."""
        netbox = make_mock_netbox_client()
        yc_data = {
            "zones": [],
            "folders": [{"id": "folder-1"}],  # no cloud_name
            "subnets": [],
        }

        # Cluster from any cloud is considered — global behavior
        orphan_cluster = MockRecord(
            id=1,
            name="cloud-beta/dead-folder",
            tags=[MockTag(id=1)],
            comments="Folder ID: folder-gone",
        )
        netbox.nb.dcim.sites.all.return_value = []
        netbox.nb.virtualization.clusters.all.return_value = [orphan_cluster]
        netbox.nb.ipam.prefixes.all.return_value = []

        result = cleanup_orphaned_infrastructure(yc_data, netbox, dry_run=False)

        assert result["clusters"] == 1
        orphan_cluster.delete.assert_called_once()

    def test_vm_cleanup_deletes_orphan_in_own_cloud(self):
        """VM in own cloud's cluster IS deleted when orphaned."""
        netbox = make_mock_netbox_client()

        own_cluster = MockRecord(id=10, name="cloud-alpha/my-folder")
        vm_orphan = MockRecord(
            id=1, name="vm-orphan", tags=[MockTag(id=1)], cluster=own_cluster,
        )
        netbox.fetch_vms.return_value = [vm_orphan]

        result = cleanup_orphaned_vms(
            [], netbox, dry_run=False, cloud_names={"cloud-alpha"},
        )

        assert result == 1
        vm_orphan.delete.assert_called_once()
