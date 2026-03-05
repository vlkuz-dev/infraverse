"""Zabbix JSON-RPC API client for fetching monitored hosts."""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List

import httpx

logger = logging.getLogger(__name__)

# Zabbix host status: 0 = enabled (monitored), 1 = disabled
_ZABBIX_STATUS_MAP: Dict[int, str] = {
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
    """

    def __init__(self, url: str, username: str, password: str):
        """Initialize Zabbix client.

        Args:
            url: Zabbix server URL (e.g. https://zabbix.example.com)
            username: Zabbix username
            password: Zabbix password
        """
        self.base_url = url.rstrip("/")
        self.api_url = f"{self.base_url}/api_jsonrpc.php"
        self.username = username
        self.password = password
        self.auth_token: str | None = None
        self.client = httpx.Client(timeout=30.0)
        self._request_id = 0

    def __del__(self):
        """Close httpx client on deletion."""
        if hasattr(self, "client"):
            self.client.close()

    def _next_request_id(self) -> int:
        """Return incrementing request ID for JSON-RPC."""
        self._request_id += 1
        return self._request_id

    def _jsonrpc_request(self, method: str, params: Dict[str, Any] | None = None) -> Any:
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
        payload: Dict[str, Any] = {
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

        Stores the auth token for subsequent requests.

        Raises:
            RuntimeError: On authentication failure.
            httpx.HTTPStatusError: On HTTP-level errors.
        """
        # user.login does not require auth token
        saved_token = self.auth_token
        self.auth_token = None
        try:
            result = self._jsonrpc_request(
                "user.login",
                {"user": self.username, "password": self.password},
            )
        except Exception:
            self.auth_token = saved_token
            raise

        if not result or not isinstance(result, str):
            raise RuntimeError("Zabbix authentication failed: no token returned")

        self.auth_token = result
        logger.info("Authenticated to Zabbix at %s", self.base_url)

    def _map_status(self, raw_status: Any) -> str:
        """Map Zabbix host status to normalized string."""
        try:
            return _ZABBIX_STATUS_MAP.get(int(raw_status), "offline")
        except (ValueError, TypeError):
            return "offline"

    def _extract_ips(self, host: Dict[str, Any]) -> List[str]:
        """Extract IP addresses from Zabbix host interfaces."""
        ips: List[str] = []
        for iface in host.get("interfaces", []):
            ip = iface.get("ip")
            if ip and ip not in ips:
                ips.append(ip)
        return ips

    def _host_to_zabbix_host(self, host: Dict[str, Any]) -> ZabbixHost:
        """Convert raw Zabbix host dict to ZabbixHost dataclass."""
        return ZabbixHost(
            name=host.get("name", host.get("host", "")),
            hostid=str(host.get("hostid", "")),
            status=self._map_status(host.get("status")),
            ip_addresses=self._extract_ips(host),
        )

    def fetch_hosts(self) -> List[ZabbixHost]:
        """Fetch all monitored hosts from Zabbix.

        Returns:
            List of ZabbixHost objects.

        Raises:
            RuntimeError: If not authenticated or API error.
        """
        if not self.auth_token:
            self.authenticate()

        all_hosts: List[Dict[str, Any]] = []
        limit = 1000
        offset = 0

        while True:
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

        logger.info("Fetched %d hosts from Zabbix", len(all_hosts))
        return [self._host_to_zabbix_host(h) for h in all_hosts]
