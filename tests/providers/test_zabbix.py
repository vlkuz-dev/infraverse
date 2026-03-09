"""Tests for Zabbix client."""

import pytest
from unittest.mock import MagicMock, patch

import httpx

from infraverse.providers.zabbix import ZabbixClient, ZabbixHost


@pytest.fixture
def mock_client():
    """Create a ZabbixClient with a mocked httpx client."""
    with patch.object(ZabbixClient, "__init__", lambda self, *a, **kw: None):
        client = ZabbixClient.__new__(ZabbixClient)
        client.base_url = "https://zabbix.example.com"
        client.api_url = "https://zabbix.example.com/api_jsonrpc.php"
        client.username = "Admin"
        client.password = "secret"
        client.verify_ssl = True
        client.auth_token = "test-auth-token"
        client._request_id = 0
        client.client = MagicMock(spec=httpx.Client)
        return client


def _mock_response(json_data=None, status_code=200):
    """Create a mock httpx response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.raise_for_status.return_value = None
    return resp


# --- Authentication tests ---


class TestAuthenticate:
    def test_successful_auth_with_username_param(self, mock_client):
        """Zabbix >=5.4 uses 'username' parameter."""
        mock_client.auth_token = None
        resp = _mock_response({
            "jsonrpc": "2.0",
            "result": "auth-token-abc123",
            "id": 1,
        })
        mock_client.client.post.return_value = resp

        mock_client.authenticate()

        assert mock_client.auth_token == "auth-token-abc123"
        call_args = mock_client.client.post.call_args
        payload = call_args.kwargs["json"]
        assert payload["method"] == "user.login"
        assert payload["params"] == {"username": "Admin", "password": "secret"}
        assert "auth" not in payload

    def test_fallback_to_user_param_on_error(self, mock_client):
        """Zabbix <5.4 uses 'user' parameter - fallback when 'username' fails."""
        mock_client.auth_token = None

        error_resp = _mock_response({
            "jsonrpc": "2.0",
            "error": {
                "code": -32602,
                "message": "Invalid params.",
                "data": "No permissions to referred object or it does not exist!",
            },
            "id": 1,
        })
        success_resp = _mock_response({
            "jsonrpc": "2.0",
            "result": "auth-token-legacy",
            "id": 2,
        })
        mock_client.client.post.side_effect = [error_resp, success_resp]

        mock_client.authenticate()

        assert mock_client.auth_token == "auth-token-legacy"
        calls = mock_client.client.post.call_args_list
        first_payload = calls[0].kwargs["json"]
        assert first_payload["params"] == {"username": "Admin", "password": "secret"}
        second_payload = calls[1].kwargs["json"]
        assert second_payload["params"] == {"user": "Admin", "password": "secret"}

    def test_auth_failure_both_params_fail(self, mock_client):
        """Both 'username' and 'user' fail - raises error from second attempt."""
        mock_client.auth_token = None
        error_resp = _mock_response({
            "jsonrpc": "2.0",
            "error": {
                "code": -32602,
                "message": "Invalid params.",
                "data": "Login name or password is incorrect.",
            },
            "id": 1,
        })
        mock_client.client.post.return_value = error_resp

        with pytest.raises(RuntimeError, match="Login name or password is incorrect"):
            mock_client.authenticate()

    def test_auth_failure_no_token_returned(self, mock_client):
        mock_client.auth_token = None
        resp = _mock_response({
            "jsonrpc": "2.0",
            "result": "",
            "id": 1,
        })
        mock_client.client.post.return_value = resp

        with pytest.raises(RuntimeError, match="no token returned"):
            mock_client.authenticate()

    @patch("time.sleep")
    def test_auth_http_error(self, _sleep, mock_client):
        mock_client.auth_token = None
        resp = MagicMock()
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server Error", request=MagicMock(), response=MagicMock(status_code=500)
        )
        mock_client.client.post.return_value = resp

        with pytest.raises(httpx.HTTPStatusError):
            mock_client.authenticate()

    def test_auth_clears_token_for_login_request(self, mock_client):
        """Auth token should not be sent with user.login request."""
        mock_client.auth_token = "old-token"
        resp = _mock_response({
            "jsonrpc": "2.0",
            "result": "new-token",
            "id": 1,
        })
        mock_client.client.post.return_value = resp

        mock_client.authenticate()

        call_args = mock_client.client.post.call_args
        payload = call_args.kwargs["json"]
        assert "auth" not in payload
        assert mock_client.auth_token == "new-token"

    @patch("time.sleep")
    def test_auth_restores_token_on_http_failure(self, _sleep, mock_client):
        """On HTTP failure, the original auth token is restored."""
        mock_client.auth_token = "old-token"
        resp = MagicMock()
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server Error", request=MagicMock(), response=MagicMock(status_code=500)
        )
        mock_client.client.post.return_value = resp

        with pytest.raises(httpx.HTTPStatusError):
            mock_client.authenticate()

        assert mock_client.auth_token == "old-token"


# --- Host listing tests ---


class TestFetchHosts:
    def test_active_hosts(self, mock_client):
        resp = _mock_response({
            "jsonrpc": "2.0",
            "result": [
                {
                    "hostid": "10001",
                    "host": "web-server",
                    "name": "Web Server",
                    "status": "0",
                    "interfaces": [{"ip": "10.0.0.1"}],
                },
                {
                    "hostid": "10002",
                    "host": "db-server",
                    "name": "DB Server",
                    "status": "0",
                    "interfaces": [{"ip": "10.0.0.2"}],
                },
            ],
            "id": 1,
        })
        mock_client.client.post.return_value = resp

        hosts = mock_client.fetch_hosts()

        assert len(hosts) == 2
        assert all(isinstance(h, ZabbixHost) for h in hosts)
        assert hosts[0].name == "Web Server"
        assert hosts[0].hostid == "10001"
        assert hosts[0].status == "active"
        assert hosts[0].ip_addresses == ["10.0.0.1"]
        assert hosts[1].name == "DB Server"
        assert hosts[1].status == "active"

    def test_disabled_host(self, mock_client):
        resp = _mock_response({
            "jsonrpc": "2.0",
            "result": [
                {
                    "hostid": "10003",
                    "host": "old-server",
                    "name": "Old Server",
                    "status": "1",
                    "interfaces": [{"ip": "10.0.0.3"}],
                },
            ],
            "id": 1,
        })
        mock_client.client.post.return_value = resp

        hosts = mock_client.fetch_hosts()

        assert len(hosts) == 1
        assert hosts[0].status == "offline"

    def test_no_hosts(self, mock_client):
        resp = _mock_response({
            "jsonrpc": "2.0",
            "result": [],
            "id": 1,
        })
        mock_client.client.post.return_value = resp

        hosts = mock_client.fetch_hosts()

        assert hosts == []

    def test_host_with_multiple_interfaces(self, mock_client):
        resp = _mock_response({
            "jsonrpc": "2.0",
            "result": [
                {
                    "hostid": "10004",
                    "host": "multi-nic",
                    "name": "Multi NIC",
                    "status": "0",
                    "interfaces": [
                        {"ip": "10.0.0.1"},
                        {"ip": "192.168.1.1"},
                    ],
                },
            ],
            "id": 1,
        })
        mock_client.client.post.return_value = resp

        hosts = mock_client.fetch_hosts()

        assert hosts[0].ip_addresses == ["10.0.0.1", "192.168.1.1"]

    def test_host_with_duplicate_ips(self, mock_client):
        resp = _mock_response({
            "jsonrpc": "2.0",
            "result": [
                {
                    "hostid": "10005",
                    "host": "dup-ip",
                    "name": "Dup IP",
                    "status": "0",
                    "interfaces": [
                        {"ip": "10.0.0.1"},
                        {"ip": "10.0.0.1"},
                    ],
                },
            ],
            "id": 1,
        })
        mock_client.client.post.return_value = resp

        hosts = mock_client.fetch_hosts()

        assert hosts[0].ip_addresses == ["10.0.0.1"]

    def test_host_with_no_interfaces(self, mock_client):
        resp = _mock_response({
            "jsonrpc": "2.0",
            "result": [
                {
                    "hostid": "10006",
                    "host": "no-iface",
                    "name": "No Interface",
                    "status": "0",
                },
            ],
            "id": 1,
        })
        mock_client.client.post.return_value = resp

        hosts = mock_client.fetch_hosts()

        assert hosts[0].ip_addresses == []

    def test_pagination(self, mock_client):
        """Test that fetch_hosts pages through results."""
        page1_hosts = [
            {
                "hostid": str(i),
                "host": f"host-{i}",
                "name": f"Host {i}",
                "status": "0",
                "interfaces": [{"ip": f"10.0.0.{i % 256}"}],
            }
            for i in range(1000)
        ]
        page2_hosts = [
            {
                "hostid": "2001",
                "host": "host-last",
                "name": "Host Last",
                "status": "0",
                "interfaces": [{"ip": "10.0.1.1"}],
            }
        ]
        resp1 = _mock_response({"jsonrpc": "2.0", "result": page1_hosts, "id": 1})
        resp2 = _mock_response({"jsonrpc": "2.0", "result": page2_hosts, "id": 2})
        mock_client.client.post.side_effect = [resp1, resp2]

        hosts = mock_client.fetch_hosts()

        assert len(hosts) == 1001
        assert mock_client.client.post.call_count == 2
        assert mock_client.last_fetch_truncated is False

    def test_pagination_truncated_sets_flag(self, mock_client):
        """When max_pages is hit, last_fetch_truncated is True."""
        # Create a page that always returns a full 1000 hosts
        full_page = [
            {
                "hostid": str(i),
                "host": f"host-{i}",
                "name": f"Host {i}",
                "status": "0",
                "interfaces": [],
            }
            for i in range(1000)
        ]
        resp = _mock_response({"jsonrpc": "2.0", "result": full_page, "id": 1})
        mock_client.client.post.return_value = resp

        # Use max_pages=2 so we hit the limit quickly
        raw = mock_client._fetch_hosts_paginated(max_pages=2)

        assert len(raw) == 2000
        assert mock_client.last_fetch_truncated is True

    def test_pagination_not_truncated_clears_flag(self, mock_client):
        """Normal pagination clears the truncated flag."""
        mock_client.last_fetch_truncated = True  # pre-set from previous call
        resp = _mock_response({
            "jsonrpc": "2.0",
            "result": [{"hostid": "1", "host": "h", "name": "H", "status": "0", "interfaces": []}],
            "id": 1,
        })
        mock_client.client.post.return_value = resp

        mock_client._fetch_hosts_paginated()

        assert mock_client.last_fetch_truncated is False

    def test_not_authenticated_auto_authenticates(self):
        """Fetching without authentication triggers auto-authenticate."""
        with patch.object(ZabbixClient, "__init__", lambda self, *a, **kw: None):
            client = ZabbixClient.__new__(ZabbixClient)
            client.auth_token = None
            client.api_url = "http://zabbix.test/api_jsonrpc.php"
            client.client = MagicMock(spec=httpx.Client)

            with patch.object(client, "authenticate") as mock_auth:
                def set_token():
                    client.auth_token = "test-token"
                mock_auth.side_effect = set_token

                resp = MagicMock()
                resp.raise_for_status.return_value = None
                resp.json.return_value = {
                    "jsonrpc": "2.0",
                    "result": [],
                    "id": 1,
                }
                client._request_id = 0
                client.client.post.return_value = resp

                result = client.fetch_hosts()
                mock_auth.assert_called_once()
                assert result == []


# --- Error handling tests ---


class TestErrorHandling:
    def test_api_error_response(self, mock_client):
        resp = _mock_response({
            "jsonrpc": "2.0",
            "error": {
                "code": -32600,
                "message": "Invalid request.",
                "data": "No permissions to referred object.",
            },
            "id": 1,
        })
        mock_client.client.post.return_value = resp

        with pytest.raises(RuntimeError, match="No permissions to referred object"):
            mock_client.fetch_hosts()

    def test_api_error_with_message_only(self, mock_client):
        resp = _mock_response({
            "jsonrpc": "2.0",
            "error": {
                "code": -32600,
                "message": "Something went wrong.",
            },
            "id": 1,
        })
        mock_client.client.post.return_value = resp

        with pytest.raises(RuntimeError, match="Something went wrong"):
            mock_client.fetch_hosts()

    @patch("time.sleep")
    def test_http_error_on_fetch(self, _sleep, mock_client):
        resp = MagicMock()
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server Error", request=MagicMock(), response=MagicMock(status_code=500)
        )
        mock_client.client.post.return_value = resp

        with pytest.raises(httpx.HTTPStatusError):
            mock_client.fetch_hosts()


# --- Status mapping tests ---


class TestStatusMapping:
    def test_enabled_int(self, mock_client):
        assert mock_client._map_status(0) == "active"

    def test_disabled_int(self, mock_client):
        assert mock_client._map_status(1) == "offline"

    def test_enabled_string(self, mock_client):
        assert mock_client._map_status("0") == "active"

    def test_disabled_string(self, mock_client):
        assert mock_client._map_status("1") == "offline"

    def test_unknown_status(self, mock_client):
        assert mock_client._map_status(99) == "offline"

    def test_none_status(self, mock_client):
        assert mock_client._map_status(None) == "offline"


# --- ZabbixHost dataclass tests ---


class TestZabbixHost:
    def test_creation(self):
        host = ZabbixHost(
            name="Test Host",
            hostid="123",
            status="active",
            ip_addresses=["10.0.0.1"],
        )
        assert host.name == "Test Host"
        assert host.hostid == "123"
        assert host.status == "active"
        assert host.ip_addresses == ["10.0.0.1"]

    def test_defaults(self):
        host = ZabbixHost(name="Bare", hostid="1", status="active")
        assert host.ip_addresses == []

    def test_name_fallback_to_host_field(self, mock_client):
        """When 'name' is missing, falls back to 'host' field."""
        host_data = {
            "hostid": "100",
            "host": "technical-name",
            "status": "0",
        }
        result = mock_client._host_to_zabbix_host(host_data)
        assert result.name == "technical-name"


# --- Init tests ---


class TestInit:
    def test_init_sets_fields(self):
        with patch("infraverse.providers.zabbix.httpx.Client") as mock_httpx:
            client = ZabbixClient(
                url="https://zabbix.example.com/",
                username="Admin",
                password="secret",
            )
            assert client.base_url == "https://zabbix.example.com"
            assert client.api_url == "https://zabbix.example.com/api_jsonrpc.php"
            assert client.username == "Admin"
            assert client.password == "secret"
            assert client.auth_token is None
            assert client.verify_ssl is True
            mock_httpx.assert_called_once_with(timeout=30.0, verify=True)

    def test_url_trailing_slash_stripped(self):
        with patch("infraverse.providers.zabbix.httpx.Client"):
            client = ZabbixClient(
                url="https://zabbix.example.com///",
                username="Admin",
                password="secret",
            )
            assert client.base_url == "https://zabbix.example.com"

    def test_verify_ssl_false(self):
        """verify_ssl=False disables SSL verification for self-signed certs."""
        with patch("infraverse.providers.zabbix.httpx.Client") as mock_httpx:
            client = ZabbixClient(
                url="https://zabbix.example.com",
                username="Admin",
                password="secret",
                verify_ssl=False,
            )
            assert client.verify_ssl is False
            mock_httpx.assert_called_once_with(timeout=30.0, verify=False)


# --- JSON-RPC internals ---


class TestJsonRpcRequest:
    def test_includes_auth_when_set(self, mock_client):
        mock_client.auth_token = "my-token"
        resp = _mock_response({"jsonrpc": "2.0", "result": "ok", "id": 1})
        mock_client.client.post.return_value = resp

        mock_client._jsonrpc_request("test.method", {"key": "val"})

        payload = mock_client.client.post.call_args.kwargs["json"]
        assert payload["auth"] == "my-token"
        assert payload["method"] == "test.method"
        assert payload["params"] == {"key": "val"}

    def test_no_auth_when_none(self, mock_client):
        mock_client.auth_token = None
        resp = _mock_response({"jsonrpc": "2.0", "result": "ok", "id": 1})
        mock_client.client.post.return_value = resp

        mock_client._jsonrpc_request("test.method")

        payload = mock_client.client.post.call_args.kwargs["json"]
        assert "auth" not in payload

    def test_request_id_increments(self, mock_client):
        resp = _mock_response({"jsonrpc": "2.0", "result": "ok", "id": 1})
        mock_client.client.post.return_value = resp

        mock_client._jsonrpc_request("method1")
        mock_client._jsonrpc_request("method2")

        calls = mock_client.client.post.call_args_list
        assert calls[0].kwargs["json"]["id"] == 1
        assert calls[1].kwargs["json"]["id"] == 2


# --- Per-VM host search tests ---


class TestSearchHostByName:
    def test_found(self, mock_client):
        """Search by name returns ZabbixHost when host exists."""
        resp = _mock_response({
            "jsonrpc": "2.0",
            "result": [
                {
                    "hostid": "10001",
                    "host": "web-server",
                    "name": "Web Server",
                    "status": "0",
                    "interfaces": [{"ip": "10.0.0.1"}],
                },
            ],
            "id": 1,
        })
        mock_client.client.post.return_value = resp

        result = mock_client.search_host_by_name("Web Server")

        assert result is not None
        assert isinstance(result, ZabbixHost)
        assert result.name == "Web Server"
        assert result.hostid == "10001"
        assert result.status == "active"
        assert result.ip_addresses == ["10.0.0.1"]
        # Verify correct API call with filter
        payload = mock_client.client.post.call_args.kwargs["json"]
        assert payload["method"] == "host.get"
        assert payload["params"]["filter"] == {"name": "Web Server"}

    def test_not_found(self, mock_client):
        """Search by name returns None when host doesn't exist."""
        resp = _mock_response({
            "jsonrpc": "2.0",
            "result": [],
            "id": 1,
        })
        mock_client.client.post.return_value = resp

        result = mock_client.search_host_by_name("nonexistent-host")

        assert result is None

    def test_api_error(self, mock_client):
        """Search by name raises RuntimeError on API error."""
        resp = _mock_response({
            "jsonrpc": "2.0",
            "error": {
                "code": -32600,
                "message": "Invalid request.",
                "data": "No permissions to referred object.",
            },
            "id": 1,
        })
        mock_client.client.post.return_value = resp

        with pytest.raises(RuntimeError, match="No permissions"):
            mock_client.search_host_by_name("Web Server")

    def test_auto_authenticates_when_no_token(self):
        """search_host_by_name triggers authenticate when no auth token."""
        with patch.object(ZabbixClient, "__init__", lambda self, *a, **kw: None):
            client = ZabbixClient.__new__(ZabbixClient)
            client.auth_token = None
            client.api_url = "http://zabbix.test/api_jsonrpc.php"
            client.client = MagicMock(spec=httpx.Client)
            client._request_id = 0

            with patch.object(client, "authenticate") as mock_auth:
                def set_token():
                    client.auth_token = "test-token"
                mock_auth.side_effect = set_token

                resp = _mock_response({
                    "jsonrpc": "2.0",
                    "result": [],
                    "id": 1,
                })
                client.client.post.return_value = resp

                result = client.search_host_by_name("test-host")
                mock_auth.assert_called_once()
                assert result is None

    def test_multiple_matches_returns_first(self, mock_client):
        """If multiple hosts match (unlikely with exact filter), return first."""
        resp = _mock_response({
            "jsonrpc": "2.0",
            "result": [
                {
                    "hostid": "10001",
                    "host": "web-server",
                    "name": "Web Server",
                    "status": "0",
                    "interfaces": [{"ip": "10.0.0.1"}],
                },
                {
                    "hostid": "10002",
                    "host": "web-server-2",
                    "name": "Web Server",
                    "status": "0",
                    "interfaces": [{"ip": "10.0.0.2"}],
                },
            ],
            "id": 1,
        })
        mock_client.client.post.return_value = resp

        result = mock_client.search_host_by_name("Web Server")

        assert result is not None
        assert result.hostid == "10001"


class TestSearchHostByIp:
    def test_found(self, mock_client):
        """Search by IP returns ZabbixHost when host exists."""
        iface_resp = _mock_response({
            "jsonrpc": "2.0",
            "result": [{"hostid": "10001"}],
            "id": 1,
        })
        host_resp = _mock_response({
            "jsonrpc": "2.0",
            "result": [
                {
                    "hostid": "10001",
                    "host": "web-server",
                    "name": "Web Server",
                    "status": "0",
                    "interfaces": [{"ip": "10.0.0.1"}],
                },
            ],
            "id": 2,
        })
        mock_client.client.post.side_effect = [iface_resp, host_resp]

        result = mock_client.search_host_by_ip("10.0.0.1")

        assert result is not None
        assert isinstance(result, ZabbixHost)
        assert result.name == "Web Server"
        assert result.ip_addresses == ["10.0.0.1"]
        # Verify first call is hostinterface.get
        calls = mock_client.client.post.call_args_list
        first_payload = calls[0].kwargs["json"]
        assert first_payload["method"] == "hostinterface.get"
        assert first_payload["params"]["filter"] == {"ip": "10.0.0.1"}
        # Verify second call is host.get with hostid
        second_payload = calls[1].kwargs["json"]
        assert second_payload["method"] == "host.get"
        assert second_payload["params"]["hostids"] == ["10001"]

    def test_not_found(self, mock_client):
        """Search by IP returns None when no host matches."""
        resp = _mock_response({
            "jsonrpc": "2.0",
            "result": [],
            "id": 1,
        })
        mock_client.client.post.return_value = resp

        result = mock_client.search_host_by_ip("192.168.1.99")

        assert result is None

    def test_api_error(self, mock_client):
        """Search by IP raises RuntimeError on API error."""
        resp = _mock_response({
            "jsonrpc": "2.0",
            "error": {
                "code": -32600,
                "message": "Invalid request.",
                "data": "No permissions.",
            },
            "id": 1,
        })
        mock_client.client.post.return_value = resp

        with pytest.raises(RuntimeError, match="No permissions"):
            mock_client.search_host_by_ip("10.0.0.1")

    def test_auto_authenticates_when_no_token(self):
        """search_host_by_ip triggers authenticate when no auth token."""
        with patch.object(ZabbixClient, "__init__", lambda self, *a, **kw: None):
            client = ZabbixClient.__new__(ZabbixClient)
            client.auth_token = None
            client.api_url = "http://zabbix.test/api_jsonrpc.php"
            client.client = MagicMock(spec=httpx.Client)
            client._request_id = 0

            with patch.object(client, "authenticate") as mock_auth:
                def set_token():
                    client.auth_token = "test-token"
                mock_auth.side_effect = set_token

                resp = _mock_response({
                    "jsonrpc": "2.0",
                    "result": [],
                    "id": 1,
                })
                client.client.post.return_value = resp

                result = client.search_host_by_ip("10.0.0.1")
                mock_auth.assert_called_once()
                assert result is None
