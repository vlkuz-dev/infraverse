"""Tests for Yandex Cloud client."""

import pytest
from unittest.mock import MagicMock, patch
import httpx

from infraverse.providers.base import CloudProvider, VMInfo
from infraverse.providers.yandex import YandexCloudClient


@pytest.fixture
def mock_client():
    """Create a YandexCloudClient with a mocked httpx client."""
    with patch.object(YandexCloudClient, '__init__', lambda self, token: None):
        client = YandexCloudClient.__new__(YandexCloudClient)
        client.token = "test-token"
        client.headers = {"Authorization": "Bearer test-token"}
        client.client = MagicMock(spec=httpx.Client)
        return client


def _mock_response(json_data, status_code=200):
    """Create a mock httpx response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status.return_value = None
    return resp


class TestFetchZones:
    def test_fetch_zones_success(self, mock_client):
        zones = [
            {"id": "ru-central1-a", "name": "ru-central1-a", "regionId": "ru-central1"},
            {"id": "ru-central1-b", "name": "ru-central1-b", "regionId": "ru-central1"},
        ]
        mock_client.client.get.return_value = _mock_response({"zones": zones})

        result = mock_client.fetch_zones()

        assert len(result) == 2
        assert result[0]["id"] == "ru-central1-a"
        mock_client.client.get.assert_called_once_with(
            "https://compute.api.cloud.yandex.net/compute/v1/zones"
        )

    def test_fetch_zones_empty(self, mock_client):
        mock_client.client.get.return_value = _mock_response({"zones": []})
        result = mock_client.fetch_zones()
        assert result == []

    def test_fetch_zones_http_error(self, mock_client):
        resp = MagicMock()
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server Error", request=MagicMock(), response=MagicMock(status_code=500)
        )
        mock_client.client.get.return_value = resp

        with pytest.raises(httpx.HTTPStatusError):
            mock_client.fetch_zones()


class TestFetchClouds:
    def test_fetch_clouds_success(self, mock_client):
        clouds = [{"id": "cloud1", "name": "my-cloud"}]
        mock_client.client.get.return_value = _mock_response({"clouds": clouds})

        result = mock_client.fetch_clouds()

        assert len(result) == 1
        assert result[0]["id"] == "cloud1"

    def test_fetch_clouds_pagination(self, mock_client):
        page1 = {"clouds": [{"id": "c1"}], "nextPageToken": "tok1"}
        page2 = {"clouds": [{"id": "c2"}]}
        mock_client.client.get.side_effect = [
            _mock_response(page1),
            _mock_response(page2),
        ]

        result = mock_client.fetch_clouds()

        assert len(result) == 2
        assert result[0]["id"] == "c1"
        assert result[1]["id"] == "c2"


class TestFetchFolders:
    def test_fetch_folders_success(self, mock_client):
        folders = [
            {"id": "folder1", "name": "prod"},
            {"id": "folder2", "name": "staging"},
        ]
        mock_client.client.get.return_value = _mock_response({"folders": folders})

        result = mock_client.fetch_folders("cloud1")

        assert len(result) == 2
        mock_client.client.get.assert_called_once_with(
            "https://resource-manager.api.cloud.yandex.net/resource-manager/v1/folders",
            params={"cloudId": "cloud1"}
        )

    def test_fetch_folders_pagination(self, mock_client):
        page1 = {"folders": [{"id": "f1"}], "nextPageToken": "tok1"}
        page2 = {"folders": [{"id": "f2"}]}
        mock_client.client.get.side_effect = [
            _mock_response(page1),
            _mock_response(page2),
        ]

        result = mock_client.fetch_folders("cloud1")

        assert len(result) == 2
        assert result[0]["id"] == "f1"
        assert result[1]["id"] == "f2"


class TestFetchVpcs:
    def test_fetch_vpcs_success(self, mock_client):
        networks = [{"id": "vpc1", "name": "default"}]
        mock_client.client.get.return_value = _mock_response({"networks": networks})

        result = mock_client.fetch_vpcs("folder1")

        assert len(result) == 1
        assert result[0]["name"] == "default"

    def test_fetch_vpcs_pagination(self, mock_client):
        page1 = {"networks": [{"id": "n1"}], "nextPageToken": "tok1"}
        page2 = {"networks": [{"id": "n2"}]}
        mock_client.client.get.side_effect = [
            _mock_response(page1),
            _mock_response(page2),
        ]

        result = mock_client.fetch_vpcs("folder1")

        assert len(result) == 2
        assert result[0]["id"] == "n1"
        assert result[1]["id"] == "n2"


class TestFetchSubnets:
    def test_fetch_subnets_single_page(self, mock_client):
        subnets = [{"id": "subnet1", "name": "sub-a"}]
        mock_client.client.get.return_value = _mock_response({"subnets": subnets})

        result = mock_client.fetch_subnets("folder1")

        assert len(result) == 1
        assert result[0]["id"] == "subnet1"

    def test_fetch_subnets_pagination(self, mock_client):
        page1 = {"subnets": [{"id": "s1"}], "nextPageToken": "token123"}
        page2 = {"subnets": [{"id": "s2"}]}

        mock_client.client.get.side_effect = [
            _mock_response(page1),
            _mock_response(page2),
        ]

        result = mock_client.fetch_subnets("folder1")

        assert len(result) == 2
        assert result[0]["id"] == "s1"
        assert result[1]["id"] == "s2"
        assert mock_client.client.get.call_count == 2


class TestFetchVmsInFolder:
    def test_fetch_vms_success(self, mock_client):
        instances = [
            {
                "id": "vm1",
                "name": "web-1",
                "resources": {"memory": 4294967296, "cores": 2},
            }
        ]
        mock_client.client.get.return_value = _mock_response({"instances": instances})

        result = mock_client.fetch_vms_in_folder("folder1")

        assert len(result) == 1
        assert result[0]["name"] == "web-1"

    def test_fetch_vms_empty(self, mock_client):
        mock_client.client.get.return_value = _mock_response({"instances": []})
        result = mock_client.fetch_vms_in_folder("folder1")
        assert result == []


class TestFetchDisk:
    def test_fetch_disk_success(self, mock_client):
        disk = {"id": "disk1", "size": "10737418240", "name": "boot-disk"}
        mock_client.client.get.return_value = _mock_response(disk)

        result = mock_client.fetch_disk("disk1")

        assert result["id"] == "disk1"
        mock_client.client.get.assert_called_once_with(
            "https://compute.api.cloud.yandex.net/compute/v1/disks/disk1"
        )


class TestFetchImage:
    def test_fetch_image_success(self, mock_client):
        image = {"id": "img1", "name": "ubuntu-22.04"}
        mock_client.client.get.return_value = _mock_response(image)

        result = mock_client.fetch_image("img1")

        assert result["name"] == "ubuntu-22.04"


class TestFetchAllData:
    def test_fetch_all_data_orchestration(self, mock_client):
        """Test that fetch_all_data properly orchestrates sub-calls and structures output."""
        # Setup mock responses for the chain of calls
        zones = [{"id": "ru-central1-a", "name": "ru-central1-a", "regionId": "ru-central1"}]
        clouds = [{"id": "cloud1", "name": "my-cloud", "description": ""}]
        folders = [{"id": "folder1", "name": "prod", "description": ""}]
        vpcs = [{"id": "vpc1", "name": "default", "description": ""}]
        subnets = [{
            "id": "subnet1",
            "name": "sub-a",
            "networkId": "vpc1",
            "v4CidrBlocks": ["10.0.0.0/24"],
            "zoneId": "ru-central1-a",
        }]
        vms = [{
            "id": "vm1",
            "name": "web-1",
            "status": "RUNNING",
            "zoneId": "ru-central1-a",
            "resources": {"memory": 4294967296, "cores": 2},
            "networkInterfaces": [{
                "networkId": "vpc1",
                "subnetId": "subnet1",
                "primaryV4Address": {"address": "10.0.0.5"},
            }],
            "platformId": "standard-v3",
        }]

        # Map URL patterns to responses
        def mock_get(url, **kwargs):
            if "zones" in url:
                return _mock_response({"zones": zones})
            elif "clouds" in url:
                return _mock_response({"clouds": clouds})
            elif "folders" in url:
                return _mock_response({"folders": folders})
            elif "networks" in url:
                return _mock_response({"networks": vpcs})
            elif "subnets" in url:
                return _mock_response({"subnets": subnets})
            elif "instances" in url:
                return _mock_response({"instances": vms})
            return _mock_response({})

        mock_client.client.get.side_effect = mock_get

        result = mock_client.fetch_all_data()

        assert len(result["zones"]) == 1
        assert len(result["clouds"]) == 1
        assert len(result["folders"]) == 1
        assert len(result["vpcs"]) == 1
        assert len(result["subnets"]) == 1
        assert len(result["vms"]) == 1

        # Verify VM structure
        vm = result["vms"][0]
        assert vm["id"] == "vm1"
        assert vm["name"] == "web-1"
        assert vm["status"] == "RUNNING"
        assert vm["folder_id"] == "folder1"
        assert vm["cloud_id"] == "cloud1"
        assert vm["zone_id"] == "ru-central1-a"
        assert len(vm["network_interfaces"]) == 1
        assert vm["network_interfaces"][0]["primary_v4_address"] == "10.0.0.5"

        # Verify folder structure
        folder = result["folders"][0]
        assert folder["cloud_id"] == "cloud1"
        assert folder["cloud_name"] == "my-cloud"

        # Verify subnet structure
        subnet = result["subnets"][0]
        assert subnet["cidr"] == "10.0.0.0/24"
        assert subnet["vpc_id"] == "vpc1"
        assert subnet["zone_id"] == "ru-central1-a"

    def test_fetch_all_data_zones_fallback(self, mock_client):
        """Test that default zones are used when zone fetch fails."""

        def mock_get(url, **kwargs):
            if "zones" in url:
                resp = MagicMock()
                resp.raise_for_status.side_effect = Exception("API error")
                return resp
            elif "clouds" in url:
                return _mock_response({"clouds": []})
            return _mock_response({})

        mock_client.client.get.side_effect = mock_get

        result = mock_client.fetch_all_data()

        # Should have default zones
        assert len(result["zones"]) == 4
        zone_ids = [z["id"] for z in result["zones"]]
        assert "ru-central1-a" in zone_ids
        assert "ru-central1-d" in zone_ids

    def test_fetch_all_data_with_disks(self, mock_client):
        """Test VM disk fetching including boot, secondary, and local disks."""
        vms = [{
            "id": "vm1",
            "name": "web-1",
            "status": "RUNNING",
            "zoneId": "ru-central1-a",
            "resources": {},
            "bootDisk": {"diskId": "boot-disk-1"},
            "secondaryDisks": [{"diskId": "data-disk-1"}],
            "localDisks": [{"size": "1073741824", "deviceName": "local-ssd"}],
            "networkInterfaces": [],
            "platformId": "standard-v3",
        }]

        boot_disk = {"id": "boot-disk-1", "size": "10737418240", "name": "boot"}
        data_disk = {"id": "data-disk-1", "size": "21474836480", "name": "data"}
        image = {"id": "img1", "name": "ubuntu-22.04"}

        def mock_get(url, **kwargs):
            if "zones" in url:
                return _mock_response({"zones": []})
            elif "clouds" in url:
                return _mock_response({"clouds": [{"id": "c1", "name": "c1"}]})
            elif "folders" in url:
                return _mock_response({"folders": [{"id": "f1", "name": "f1"}]})
            elif "networks" in url:
                return _mock_response({"networks": []})
            elif "subnets" in url:
                return _mock_response({"subnets": []})
            elif "instances" in url:
                return _mock_response({"instances": vms})
            elif "images" in url:
                return _mock_response(image)
            elif "disks/boot-disk-1" in url:
                return _mock_response({**boot_disk, "sourceImageId": "img1"})
            elif "disks/data-disk-1" in url:
                return _mock_response(data_disk)
            return _mock_response({})

        mock_client.client.get.side_effect = mock_get

        result = mock_client.fetch_all_data()

        vm = result["vms"][0]
        assert len(vm["disks"]) == 3  # boot + data + local
        assert vm["os"] == "ubuntu-22.04"

        # Check disk types
        disk_types = [d["type"] for d in vm["disks"]]
        assert "cloud" in disk_types
        assert "local" in disk_types

        # Check local disk
        local_disk = next(d for d in vm["disks"] if d["type"] == "local")
        assert local_disk["size"] == 1073741824
        assert local_disk["name"] == "local-ssd"

    def test_fetch_all_data_disk_error_handled(self, mock_client):
        """Test that disk fetch errors are handled gracefully."""
        vms = [{
            "id": "vm1",
            "name": "web-1",
            "status": "RUNNING",
            "zoneId": "ru-central1-a",
            "resources": {},
            "bootDisk": {"diskId": "bad-disk"},
            "networkInterfaces": [],
            "platformId": "standard-v3",
        }]

        def mock_get(url, **kwargs):
            if "zones" in url:
                return _mock_response({"zones": []})
            elif "clouds" in url:
                return _mock_response({"clouds": [{"id": "c1", "name": "c1"}]})
            elif "folders" in url:
                return _mock_response({"folders": [{"id": "f1", "name": "f1"}]})
            elif "networks" in url:
                return _mock_response({"networks": []})
            elif "subnets" in url:
                return _mock_response({"subnets": []})
            elif "instances" in url:
                return _mock_response({"instances": vms})
            elif "disks" in url:
                resp = MagicMock()
                resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                    "Not Found", request=MagicMock(), response=MagicMock(status_code=404)
                )
                return resp
            return _mock_response({})

        mock_client.client.get.side_effect = mock_get

        result = mock_client.fetch_all_data()

        # VM should still be present, just without disks
        assert len(result["vms"]) == 1
        assert len(result["vms"][0]["disks"]) == 0
        assert result["vms"][0]["os"] is None

    def test_fetch_all_data_nat_ip(self, mock_client):
        """Test that NAT (one-to-one) IPs are captured on network interfaces."""
        vms = [{
            "id": "vm1",
            "name": "web-1",
            "status": "RUNNING",
            "zoneId": "ru-central1-a",
            "resources": {},
            "networkInterfaces": [{
                "networkId": "vpc1",
                "subnetId": "subnet1",
                "primaryV4Address": {
                    "address": "10.0.0.5",
                    "oneToOneNat": {"address": "84.201.1.1"}
                },
            }],
            "platformId": "standard-v3",
        }]

        def mock_get(url, **kwargs):
            if "zones" in url:
                return _mock_response({"zones": []})
            elif "clouds" in url:
                return _mock_response({"clouds": [{"id": "c1", "name": "c1"}]})
            elif "folders" in url:
                return _mock_response({"folders": [{"id": "f1", "name": "f1"}]})
            elif "networks" in url:
                return _mock_response({"networks": [{"id": "vpc1", "name": "default"}]})
            elif "subnets" in url:
                return _mock_response({"subnets": [{
                    "id": "subnet1",
                    "name": "sub-a",
                    "networkId": "vpc1",
                    "v4CidrBlocks": ["10.0.0.0/24"],
                    "zoneId": "ru-central1-a",
                }]})
            elif "instances" in url:
                return _mock_response({"instances": vms})
            return _mock_response({})

        mock_client.client.get.side_effect = mock_get

        result = mock_client.fetch_all_data()

        iface = result["vms"][0]["network_interfaces"][0]
        assert iface["primary_v4_address"] == "10.0.0.5"
        assert iface["primary_v4_address_one_to_one_nat"] == "84.201.1.1"

    def test_fetch_all_data_sets_error_flag_on_vm_fetch_failure(self, mock_client):
        """Test that _has_fetch_errors is set when folder-level fetches fail."""
        def mock_get(url, **kwargs):
            if "zones" in url:
                return _mock_response({"zones": []})
            elif "clouds" in url:
                return _mock_response({"clouds": [{"id": "c1", "name": "c1"}]})
            elif "folders" in url:
                return _mock_response({"folders": [{"id": "f1", "name": "f1"}]})
            elif "networks" in url:
                return _mock_response({"networks": []})
            elif "subnets" in url:
                return _mock_response({"subnets": []})
            elif "instances" in url:
                resp = MagicMock()
                resp.raise_for_status.side_effect = Exception("API timeout")
                return resp
            return _mock_response({})

        mock_client.client.get.side_effect = mock_get

        result = mock_client.fetch_all_data()

        assert result["_has_fetch_errors"] is True
        assert len(result["vms"]) == 0

    def test_fetch_all_data_sets_error_flag_on_folder_fetch_failure(self, mock_client):
        """Test that _has_fetch_errors is set when fetch_folders fails for a cloud."""
        def mock_get(url, **kwargs):
            if "zones" in url:
                return _mock_response({"zones": []})
            elif "clouds" in url:
                return _mock_response({"clouds": [{"id": "c1", "name": "c1"}]})
            elif "folders" in url:
                resp = MagicMock()
                resp.raise_for_status.side_effect = Exception("Permission denied")
                return resp
            return _mock_response({})

        mock_client.client.get.side_effect = mock_get

        result = mock_client.fetch_all_data()

        assert result["_has_fetch_errors"] is True
        assert len(result["folders"]) == 0
        assert len(result["vms"]) == 0

    def test_fetch_all_data_no_error_flag_on_success(self, mock_client):
        """Test that _has_fetch_errors is False when all fetches succeed."""
        def mock_get(url, **kwargs):
            if "zones" in url:
                return _mock_response({"zones": []})
            elif "clouds" in url:
                return _mock_response({"clouds": [{"id": "c1", "name": "c1"}]})
            elif "folders" in url:
                return _mock_response({"folders": [{"id": "f1", "name": "f1"}]})
            elif "networks" in url:
                return _mock_response({"networks": []})
            elif "subnets" in url:
                return _mock_response({"subnets": []})
            elif "instances" in url:
                return _mock_response({"instances": []})
            return _mock_response({})

        mock_client.client.get.side_effect = mock_get

        result = mock_client.fetch_all_data()

        assert result["_has_fetch_errors"] is False


class TestInit:
    def test_init_sets_token_and_headers(self):
        with patch('infraverse.providers.yandex.httpx.Client') as mock_httpx:
            client = YandexCloudClient("my-token")
            assert client.token == "my-token"
            assert client.headers == {"Authorization": "Bearer my-token"}
            mock_httpx.assert_called_once_with(
                timeout=30.0, headers={"Authorization": "Bearer my-token"}
            )


class TestImports:
    def test_import_from_module(self):
        from infraverse.providers.yandex import YandexCloudClient as YC
        assert YC is YandexCloudClient


def _make_fetch_all_data_mock(vms, clouds=None, folders=None):
    """Helper: create a mock_get function for fetch_all_data with given VMs."""
    clouds = clouds or [{"id": "c1", "name": "my-cloud"}]
    folders = folders or [{"id": "f1", "name": "prod"}]

    def mock_get(url, **kwargs):
        if "zones" in url:
            return _mock_response({"zones": []})
        elif "clouds" in url:
            return _mock_response({"clouds": clouds})
        elif "folders" in url:
            return _mock_response({"folders": folders})
        elif "networks" in url:
            return _mock_response({"networks": []})
        elif "subnets" in url:
            return _mock_response({"subnets": []})
        elif "instances" in url:
            return _mock_response({"instances": vms})
        return _mock_response({})
    return mock_get


class TestGetProviderName:
    def test_returns_yandex_cloud(self, mock_client):
        assert mock_client.get_provider_name() == "yandex_cloud"


class TestFetchVms:
    """Tests for fetch_vms() CloudProvider method."""

    def test_converts_vm_to_vminfo(self, mock_client):
        """Verify VMInfo fields are correctly populated from YC VM data."""
        yc_vms = [{
            "id": "vm1",
            "name": "web-server",
            "status": "RUNNING",
            "zoneId": "ru-central1-a",
            "resources": {"memory": 4294967296, "cores": 2},
            "networkInterfaces": [{
                "networkId": "vpc1",
                "subnetId": "subnet1",
                "primaryV4Address": {
                    "address": "10.0.0.5",
                    "oneToOneNat": {"address": "84.201.1.1"},
                },
            }],
            "platformId": "standard-v3",
        }]
        mock_client.client.get.side_effect = _make_fetch_all_data_mock(yc_vms)

        result = mock_client.fetch_vms()

        assert len(result) == 1
        vm = result[0]
        assert isinstance(vm, VMInfo)
        assert vm.name == "web-server"
        assert vm.id == "vm1"
        assert vm.status == "active"
        assert vm.ip_addresses == ["10.0.0.5", "84.201.1.1"]
        assert vm.vcpus == 2
        assert vm.memory_mb == 4096
        assert vm.provider == "yandex_cloud"
        assert vm.cloud_name == "my-cloud"
        assert vm.folder_name == "prod"

    def test_status_mapping(self, mock_client):
        """Verify various YC statuses map correctly."""
        statuses = {
            "RUNNING": "active",
            "STOPPED": "offline",
            "CRASHED": "offline",
            "ERROR": "offline",
            "PROVISIONING": "unknown",
            "STARTING": "unknown",
            "STOPPING": "unknown",
        }
        for yc_status, expected in statuses.items():
            yc_vms = [{
                "id": "vm1",
                "name": "test-vm",
                "status": yc_status,
                "resources": {},
                "networkInterfaces": [],
                "platformId": "standard-v3",
            }]
            mock_client.client.get.side_effect = _make_fetch_all_data_mock(yc_vms)
            result = mock_client.fetch_vms()
            assert result[0].status == expected, f"YC status {yc_status} should map to {expected}"

    def test_unknown_status_maps_to_unknown(self, mock_client):
        """An unrecognised YC status should map to 'unknown'."""
        yc_vms = [{
            "id": "vm1",
            "name": "test-vm",
            "status": "SOME_FUTURE_STATUS",
            "resources": {},
            "networkInterfaces": [],
            "platformId": "standard-v3",
        }]
        mock_client.client.get.side_effect = _make_fetch_all_data_mock(yc_vms)
        result = mock_client.fetch_vms()
        assert result[0].status == "unknown"

    def test_multiple_vms(self, mock_client):
        """Multiple VMs across the same folder."""
        yc_vms = [
            {
                "id": "vm1", "name": "web-1", "status": "RUNNING",
                "resources": {"memory": 2147483648, "cores": 1},
                "networkInterfaces": [{"networkId": "v1", "subnetId": "s1",
                    "primaryV4Address": {"address": "10.0.0.1"}}],
                "platformId": "standard-v3",
            },
            {
                "id": "vm2", "name": "web-2", "status": "STOPPED",
                "resources": {"memory": 8589934592, "cores": 4},
                "networkInterfaces": [],
                "platformId": "standard-v3",
            },
        ]
        mock_client.client.get.side_effect = _make_fetch_all_data_mock(yc_vms)

        result = mock_client.fetch_vms()

        assert len(result) == 2
        assert result[0].name == "web-1"
        assert result[0].status == "active"
        assert result[0].memory_mb == 2048
        assert result[1].name == "web-2"
        assert result[1].status == "offline"
        assert result[1].vcpus == 4
        assert result[1].memory_mb == 8192

    def test_empty_cloud(self, mock_client):
        """No VMs returns empty list."""
        mock_client.client.get.side_effect = _make_fetch_all_data_mock([])
        result = mock_client.fetch_vms()
        assert result == []

    def test_vm_without_network_interfaces(self, mock_client):
        """VM with no network interfaces has empty ip_addresses."""
        yc_vms = [{
            "id": "vm1", "name": "isolated-vm", "status": "RUNNING",
            "resources": {"cores": 1, "memory": 1073741824},
            "networkInterfaces": [],
            "platformId": "standard-v3",
        }]
        mock_client.client.get.side_effect = _make_fetch_all_data_mock(yc_vms)
        result = mock_client.fetch_vms()
        assert result[0].ip_addresses == []
        assert result[0].memory_mb == 1024

    def test_implements_cloud_provider_protocol(self, mock_client):
        """YandexCloudClient should satisfy CloudProvider protocol."""
        assert isinstance(mock_client, CloudProvider)
