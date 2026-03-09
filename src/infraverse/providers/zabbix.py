"""Zabbix JSON-RPC API client for fetching monitored hosts."""

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from infraverse.providers.retry import retry_with_backoff

logger = logging.getLogger(__name__)

# Zabbix host status: 0 = enabled (monitored), 1 = disabled
_ZABBIX_STATUS_MAP: dict[int, str] = {
    0: "active",
    1: "offline",
}


@dataclass
class ZabbixHost:
    """Representation of a Zabbix monitored host."""

    name: str
    hostid: str
    status: str  # "active" | "offline"
    ip_addresses: list[str] = field(default_factory=list)


class ZabbixClient:
    """Client for Zabbix JSON-RPC API.

    Authenticates via user.login and fetches hosts via host.get.

    Supports both Zabbix <5.4 ("user" param) and >=5.4 ("username" param)
    for user.login by trying "username" first, then falling back to "user".
    """

    def __init__(self, url: str, username: str, password: str, verify_ssl: bool = True):
        """Initialize Zabbix client.

        Args:
            url: Zabbix server URL (e.g. https://zabbix.example.com)
            username: Zabbix username
            password: Zabbix password
            verify_ssl: Whether to verify SSL certificates (set False for self-signed)
        """
        self.base_url = url.rstrip("/")
        self.api_url = f"{self.base_url}/api_jsonrpc.php"
        self.username = username
        self.password = password
        self.verify_ssl = verify_ssl
        self.auth_token: str | None = None
        self.client = httpx.Client(timeout=30.0, verify=verify_ssl)
        self._request_id = 0

    def __del__(self):
        """Close httpx client on deletion."""
        if hasattr(self, "client"):
            self.client.close()

    def _next_request_id(self) -> int:
        """Return incrementing request ID for JSON-RPC."""
        self._request_id += 1
        return self._request_id

    @retry_with_backoff
    def _jsonrpc_request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        """Send a JSON-RPC 2.0 request to Zabbix API.

        Args:
            method: Zabbix API method (e.g. "user.login", "host.get")
            params: Method parameters

        Returns:
            The "result" field from the JSON-RPC response.

        Raises:
            httpx.HTTPStatusError: On HTTP-level errors.
            RuntimeError: On JSON-RPC-level errors from Zabbix.
        """
        payload: dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
            "id": self._next_request_id(),
        }
        if self.auth_token:
            payload["auth"] = self.auth_token

        resp = self.client.post(
            self.api_url,
            json=payload,
            headers={"Content-Type": "application/json-rpc"},
        )
        resp.raise_for_status()

        data = resp.json()
        if "error" in data:
            error = data["error"]
            msg = error.get("data", error.get("message", str(error)))
            raise RuntimeError(f"Zabbix API error: {msg}")

        return data.get("result")

    def authenticate(self) -> None:
        """Authenticate to Zabbix API via user.login.

        Tries Zabbix >=5.4 "username" parameter first. If that fails with
        an invalid-params error, falls back to the legacy "user" parameter
        (Zabbix <5.4).

        Stores the auth token for subsequent requests.

        Raises:
            RuntimeError: On authentication failure.
            httpx.HTTPStatusError: On HTTP-level errors.
        """
        saved_token = self.auth_token
        self.auth_token = None
        try:
            result = self._try_login("username")
        except RuntimeError:
            # Zabbix <5.4 doesn't recognize "username", fall back to "user"
            try:
                result = self._try_login("user")
            except Exception:
                self.auth_token = saved_token
                raise
        except Exception:
            self.auth_token = saved_token
            raise

        if not result or not isinstance(result, str):
            raise RuntimeError("Zabbix authentication failed: no token returned")

        self.auth_token = result
        logger.info("Authenticated to Zabbix at %s", self.base_url)

    def _try_login(self, user_param: str) -> Any:
        """Attempt user.login with the given parameter name for username."""
        return self._jsonrpc_request(
            "user.login",
            {user_param: self.username, "password": self.password},
        )

    def _map_status(self, raw_status: Any) -> str:
        """Map Zabbix host status to normalized string."""
        try:
            return _ZABBIX_STATUS_MAP.get(int(raw_status), "offline")
        except (ValueError, TypeError):
            return "offline"

    def _extract_ips(self, host: dict[str, Any]) -> list[str]:
        """Extract IP addresses from Zabbix host interfaces."""
        ips: list[str] = []
        for iface in host.get("interfaces", []):
            ip = iface.get("ip")
            if ip and ip not in ips:
                ips.append(ip)
        return ips

    def _host_to_zabbix_host(self, host: dict[str, Any]) -> ZabbixHost:
        """Convert raw Zabbix host dict to ZabbixHost dataclass."""
        return ZabbixHost(
            name=host.get("name", host.get("host", "")),
            hostid=str(host.get("hostid", "")),
            status=self._map_status(host.get("status")),
            ip_addresses=self._extract_ips(host),
        )

    def _fetch_hosts_paginated(self, max_pages: int = 100) -> list[dict[str, Any]]:
        """Fetch all raw host dicts from Zabbix with pagination.

        Args:
            max_pages: Safety limit to prevent infinite loops if the server
                ignores the offset parameter.
        """
        all_hosts: list[dict[str, Any]] = []
        limit = 1000
        offset = 0

        for _ in range(max_pages):
            result = self._jsonrpc_request(
                "host.get",
                {
                    "output": ["hostid", "host", "name", "status"],
                    "selectInterfaces": ["ip"],
                    "limit": limit,
                    "offset": offset,
                },
            )
            if not result:
                break
            all_hosts.extend(result)
            if len(result) < limit:
                break
            offset += limit
        else:
            logger.warning(
                "Zabbix pagination hit max_pages=%d limit (%d hosts fetched); "
                "results may be incomplete",
                max_pages, len(all_hosts),
            )

        return all_hosts

    def search_host_by_name(self, name: str) -> ZabbixHost | None:
        """Search for a Zabbix host by exact name match.

        Args:
            name: Exact host name to search for.

        Returns:
            ZabbixHost if found, None otherwise.

        Raises:
            RuntimeError: On API error.
        """
        if not self.auth_token:
            self.authenticate()

        result = self._jsonrpc_request(
            "host.get",
            {
                "output": ["hostid", "host", "name", "status"],
                "selectInterfaces": ["ip"],
                "filter": {"name": name},
            },
        )
        if not result:
            return None
        return self._host_to_zabbix_host(result[0])

    def search_host_by_ip(self, ip: str) -> ZabbixHost | None:
        """Search for a Zabbix host by IP address.

        Uses hostinterface.get to find interfaces matching the IP,
        then fetches the associated host.

        Args:
            ip: IP address to search for.

        Returns:
            ZabbixHost if found, None otherwise.

        Raises:
            RuntimeError: On API error.
        """
        if not self.auth_token:
            self.authenticate()

        iface_result = self._jsonrpc_request(
            "hostinterface.get",
            {
                "output": ["hostid"],
                "filter": {"ip": ip},
            },
        )
        if not iface_result:
            return None

        host_id = iface_result[0].get("hostid")
        if not host_id:
            return None

        host_result = self._jsonrpc_request(
            "host.get",
            {
                "output": ["hostid", "host", "name", "status"],
                "selectInterfaces": ["ip"],
                "hostids": [host_id],
            },
        )
        if not host_result:
            return None
        return self._host_to_zabbix_host(host_result[0])

    def fetch_hosts(self) -> list[ZabbixHost]:
        """Fetch all monitored hosts from Zabbix.

        Returns:
            List of ZabbixHost objects.

        Raises:
            RuntimeError: If not authenticated or API error.
        """
        if not self.auth_token:
            self.authenticate()

        try:
            all_hosts = self._fetch_hosts_paginated()
        except (RuntimeError, httpx.HTTPStatusError) as exc:
            # Only retry on likely token-expiry errors, not permission errors
            exc_msg = str(exc).lower()
            if "permission" in exc_msg or "not authorized" in exc_msg:
                raise
            logger.info("Zabbix request failed, re-authenticating")
            self.authenticate()
            all_hosts = self._fetch_hosts_paginated()

        logger.info("Fetched %d hosts from Zabbix", len(all_hosts))
        return [self._host_to_zabbix_host(h) for h in all_hosts]
