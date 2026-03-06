"""Tests for vCloud Director client."""

import pytest
from unittest.mock import MagicMock, patch

import httpx

from infraverse.providers.base import CloudProvider, VMInfo
from infraverse.providers.vcloud import VCloudDirectorClient


@pytest.fixture
def mock_client():
    """Create a VCloudDirectorClient with a mocked httpx client."""
    with patch.object(VCloudDirectorClient, "__init__", lambda self, *a, **kw: None):
        client = VCloudDirectorClient.__new__(VCloudDirectorClient)
        client.base_url = "https://vcd.example.com"
        client.username = "admin"
        client.password = "secret"
        client.org = "System"
        client.auth_token = "test-token-123"
        client.client = MagicMock(spec=httpx.Client)
        return client


def _mock_response(json_data=None, status_code=200, headers=None):
    """Create a mock httpx response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.headers = headers or {}
    resp.raise_for_status.return_value = None
    return resp


# --- Authentication tests ---


class TestAuthenticate:
    def test_successful_auth(self, mock_client):
        mock_client.auth_token = None
        resp = _mock_response(
            headers={"x-vcloud-authorization": "new-token-abc"}
        )
        mock_client.client.post.return_value = resp

        mock_client.authenticate()

        assert mock_client.auth_token == "new-token-abc"
        mock_client.client.post.assert_called_once_with(
            "https://vcd.example.com/api/sessions",
            headers={"Accept": "application/*+json;version=36.0"},
            auth=("admin@System", "secret"),
        )

    def test_auth_http_error(self, mock_client):
        mock_client.auth_token = None
        resp = MagicMock()
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Unauthorized", request=MagicMock(), response=MagicMock(status_code=401)
        )
        mock_client.client.post.return_value = resp

        with pytest.raises(httpx.HTTPStatusError):
            mock_client.authenticate()

    def test_auth_missing_token_header(self, mock_client):
        mock_client.auth_token = None
        resp = _mock_response(headers={})
        mock_client.client.post.return_value = resp

        with pytest.raises(ValueError, match="No x-vcloud-authorization"):
            mock_client.authenticate()

    def test_auth_custom_org(self):
        with patch.object(VCloudDirectorClient, "__init__", lambda self, *a, **kw: None):
            client = VCloudDirectorClient.__new__(VCloudDirectorClient)
            client.base_url = "https://vcd.example.com"
            client.username = "user1"
            client.password = "pass1"
            client.org = "MyOrg"
            client.auth_token = None
            client.client = MagicMock(spec=httpx.Client)

            resp = _mock_response(headers={"x-vcloud-authorization": "tok"})
            client.client.post.return_value = resp

            client.authenticate()

            _, kwargs = client.client.post.call_args
            assert kwargs["auth"] == ("user1@MyOrg", "pass1")


# --- VM listing tests ---


class TestFetchAllVmRecords:
    def test_single_page(self, mock_client):
        records = [
            {"name": "vm-1", "href": "urn:vcloud:vm:1", "status": 4},
            {"name": "vm-2", "href": "urn:vcloud:vm:2", "status": 8},
        ]
        resp = _mock_response({
            "record": records,
            "total": 2,
            "pageSize": 128,
        })
        mock_client.client.get.return_value = resp

        result = mock_client.fetch_all_vm_records()

        assert len(result) == 2
        assert result[0]["name"] == "vm-1"
        assert result[1]["name"] == "vm-2"
        mock_client.client.get.assert_called_once()

    def test_paginated_results(self, mock_client):
        page1 = _mock_response({
            "record": [{"name": f"vm-{i}"} for i in range(128)],
            "total": 200,
            "pageSize": 128,
        })
        page2 = _mock_response({
            "record": [{"name": f"vm-{i}"} for i in range(128, 200)],
            "total": 200,
            "pageSize": 128,
        })
        mock_client.client.get.side_effect = [page1, page2]

        result = mock_client.fetch_all_vm_records()

        assert len(result) == 200
        assert mock_client.client.get.call_count == 2

    def test_empty_result(self, mock_client):
        resp = _mock_response({
            "record": [],
            "total": 0,
            "pageSize": 128,
        })
        mock_client.client.get.return_value = resp

        result = mock_client.fetch_all_vm_records()

        assert result == []

    def test_http_error_on_fetch(self, mock_client):
        resp = MagicMock()
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server Error", request=MagicMock(), response=MagicMock(status_code=500)
        )
        mock_client.client.get.return_value = resp

        with pytest.raises(httpx.HTTPStatusError):
            mock_client.fetch_all_vm_records()

    def test_auth_required(self):
        """Fetching without authentication raises RuntimeError."""
        with patch.object(VCloudDirectorClient, "__init__", lambda self, *a, **kw: None):
            client = VCloudDirectorClient.__new__(VCloudDirectorClient)
            client.base_url = "https://vcd.example.com"
            client.auth_token = None
            client.client = MagicMock(spec=httpx.Client)

            with pytest.raises(RuntimeError, match="Not authenticated"):
                client.fetch_all_vm_records()


# --- Status mapping tests ---


class TestStatusMapping:
    def test_powered_on(self, mock_client):
        assert mock_client._map_status(4) == "active"

    def test_powered_off(self, mock_client):
        assert mock_client._map_status(8) == "offline"

    def test_suspended(self, mock_client):
        assert mock_client._map_status(3) == "offline"

    def test_unknown_int_status(self, mock_client):
        assert mock_client._map_status(999) == "unknown"

    def test_string_powered_on(self, mock_client):
        assert mock_client._map_status("POWERED_ON") == "active"

    def test_string_powered_off(self, mock_client):
        assert mock_client._map_status("POWERED_OFF") == "offline"

    def test_string_suspended(self, mock_client):
        assert mock_client._map_status("SUSPENDED") == "offline"

    def test_string_numeric(self, mock_client):
        assert mock_client._map_status("4") == "active"
        assert mock_client._map_status("8") == "offline"

    def test_unknown_string(self, mock_client):
        assert mock_client._map_status("WEIRD_STATUS") == "unknown"

    def test_none_status(self, mock_client):
        assert mock_client._map_status(None) == "unknown"


# --- VMInfo conversion tests ---


class TestRecordToVminfo:
    def test_full_record(self, mock_client):
        record = {
            "name": "web-server",
            "href": "urn:vcloud:vm:abc-123",
            "status": 4,
            "ipAddress": "10.0.0.5",
            "numberOfCpus": 4,
            "memoryMB": 8192,
            "org": "MyOrg",
            "vdc": "Production",
        }
        vm = mock_client._record_to_vminfo(record)

        assert isinstance(vm, VMInfo)
        assert vm.name == "web-server"
        assert vm.id == "urn:vcloud:vm:abc-123"
        assert vm.status == "active"
        assert vm.ip_addresses == ["10.0.0.5"]
        assert vm.vcpus == 4
        assert vm.memory_mb == 8192
        assert vm.provider == "vcloud"
        assert vm.cloud_name == "MyOrg"
        assert vm.folder_name == "Production"

    def test_minimal_record(self, mock_client):
        record = {"name": "bare-vm"}
        vm = mock_client._record_to_vminfo(record)

        assert vm.name == "bare-vm"
        assert vm.id == ""
        assert vm.status == "unknown"
        assert vm.ip_addresses == []
        assert vm.vcpus == 0
        assert vm.memory_mb == 0

    def test_network_connections(self, mock_client):
        record = {
            "name": "multi-nic",
            "href": "urn:vcloud:vm:1",
            "status": 4,
            "ipAddress": "10.0.0.1",
            "networkConnections": [
                {"ipAddress": "10.0.0.1"},
                {"ipAddress": "192.168.1.1"},
            ],
        }
        vm = mock_client._record_to_vminfo(record)
        # 10.0.0.1 should not be duplicated
        assert vm.ip_addresses == ["10.0.0.1", "192.168.1.1"]


# --- CloudProvider interface tests ---


class TestFetchVms:
    def test_returns_vminfo_list(self, mock_client):
        records = [
            {
                "name": "vm-1",
                "href": "urn:vcloud:vm:1",
                "status": 4,
                "ipAddress": "10.0.0.1",
                "numberOfCpus": 2,
                "memoryMB": 4096,
                "org": "Org1",
                "vdc": "VDC1",
            },
            {
                "name": "vm-2",
                "href": "urn:vcloud:vm:2",
                "status": 8,
                "numberOfCpus": 1,
                "memoryMB": 2048,
                "org": "Org1",
                "vdc": "VDC1",
            },
        ]
        resp = _mock_response({
            "record": records,
            "total": 2,
            "pageSize": 128,
        })
        mock_client.client.get.return_value = resp

        result = mock_client.fetch_vms()

        assert len(result) == 2
        assert all(isinstance(vm, VMInfo) for vm in result)
        assert result[0].name == "vm-1"
        assert result[0].status == "active"
        assert result[1].name == "vm-2"
        assert result[1].status == "offline"

    def test_empty_vms(self, mock_client):
        resp = _mock_response({"record": [], "total": 0, "pageSize": 128})
        mock_client.client.get.return_value = resp

        result = mock_client.fetch_vms()
        assert result == []


class TestGetProviderName:
    def test_returns_vcloud_director(self, mock_client):
        assert mock_client.get_provider_name() == "vcloud"


class TestCloudProviderProtocol:
    def test_implements_protocol(self, mock_client):
        assert isinstance(mock_client, CloudProvider)


class TestInit:
    def test_init_sets_fields(self):
        with patch("infraverse.providers.vcloud.httpx.Client") as mock_httpx:
            client = VCloudDirectorClient(
                url="https://vcd.example.com/",
                username="admin",
                password="secret",
                org="TestOrg",
            )
            assert client.base_url == "https://vcd.example.com"
            assert client.username == "admin"
            assert client.password == "secret"
            assert client.org == "TestOrg"
            assert client.auth_token is None
            mock_httpx.assert_called_once_with(timeout=30.0)

    def test_init_default_org(self):
        with patch("infraverse.providers.vcloud.httpx.Client"):
            client = VCloudDirectorClient(
                url="https://vcd.example.com",
                username="admin",
                password="secret",
            )
            assert client.org == "System"
