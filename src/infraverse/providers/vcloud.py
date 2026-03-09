"""vCloud Director API client for fetching VM resources."""

import logging
from typing import Any, Dict, List

import httpx

from infraverse.providers.base import VMInfo
from infraverse.providers.retry import retry_with_backoff

logger = logging.getLogger(__name__)

# vCD numeric status → VMInfo status mapping
# See https://developer.broadcom.com/xapis/vmware-cloud-director-api/37.3/types/QueryResultVMRecordType/
_VCD_STATUS_MAP: Dict[int, str] = {
    4: "active",    # POWERED_ON
    8: "offline",   # POWERED_OFF
    3: "offline",   # SUSPENDED
    10: "unknown",  # MIXED (vApp-level)
    -1: "unknown",  # COULD_NOT_BE_CREATED
    0: "unknown",   # UNRESOLVED
    1: "unknown",   # RESOLVED
    5: "unknown",   # WAITING_FOR_INPUT
    6: "unknown",   # UNKNOWN
    7: "unknown",   # UNRECOGNIZED
    9: "unknown",   # INCONSISTENT_STATE
}

# String status variants (some vCD versions return strings)
_VCD_STATUS_STR_MAP: Dict[str, str] = {
    "POWERED_ON": "active",
    "POWERED_OFF": "offline",
    "SUSPENDED": "offline",
}


class VCloudDirectorClient:
    """Client for VMware vCloud Director API.

    Implements CloudProvider protocol: fetch_vms() and get_provider_name().
    """

    def __init__(self, url: str, username: str, password: str, org: str = "System"):
        """Initialize vCloud Director client.

        Args:
            url: vCD API base URL (e.g. https://vcd.example.com)
            username: vCD username
            password: vCD password
            org: vCD organization (default: System)
        """
        self.base_url = url.rstrip("/")
        self.username = username
        self.password = password
        self.org = org
        self.auth_token: str | None = None
        self.client = httpx.Client(timeout=30.0)

    def __del__(self):
        """Close httpx client on deletion."""
        if hasattr(self, "client"):
            self.client.close()

    @retry_with_backoff
    def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """HTTP request with retry on transient errors."""
        resp = self.client.request(method, url, **kwargs)
        resp.raise_for_status()
        return resp

    def authenticate(self) -> None:
        """Authenticate to vCD API and store session token.

        Uses Basic Auth to POST /api/sessions, receives
        x-vcloud-authorization header in response.
        """
        url = f"{self.base_url}/api/sessions"
        headers = {
            "Accept": "application/*+json;version=36.0",
        }
        resp = self._request(
            "POST",
            url,
            headers=headers,
            auth=(f"{self.username}@{self.org}", self.password),
        )
        self.auth_token = resp.headers.get("x-vcloud-authorization")
        if not self.auth_token:
            raise ValueError("No x-vcloud-authorization token in response")
        logger.info("Authenticated to vCloud Director at %s", self.base_url)

    def _auth_headers(self) -> Dict[str, str]:
        """Return headers with auth token for API requests."""
        if not self.auth_token:
            raise RuntimeError("Not authenticated. Call authenticate() first.")
        return {
            "Accept": "application/*+json;version=36.0",
            "x-vcloud-authorization": self.auth_token,
        }

    def _fetch_vms_page(self, page: int, page_size: int = 128) -> Dict[str, Any]:
        """Fetch a single page of VM records from vCD query API.

        Args:
            page: Page number (1-based)
            page_size: Number of records per page

        Returns:
            Raw JSON response dict with 'record' list and pagination info.
        """
        url = f"{self.base_url}/api/query"
        params = {
            "type": "vm",
            "pageSize": str(page_size),
            "page": str(page),
        }
        resp = self._request("GET", url, headers=self._auth_headers(), params=params)
        return resp.json()

    def fetch_all_vm_records(self) -> List[Dict[str, Any]]:
        """Fetch all VM records from vCD with pagination.

        Returns:
            List of raw VM record dicts from the vCD query API.
        """
        all_records: List[Dict[str, Any]] = []
        page = 1

        while True:
            data = self._fetch_vms_page(page)
            records = data.get("record", [])
            all_records.extend(records)

            total = int(data.get("total", 0))
            page_size = int(data.get("pageSize", 128))
            if page * page_size >= total:
                break
            page += 1

        logger.info("Fetched %d VM records from vCloud Director", len(all_records))
        return all_records

    def _map_status(self, raw_status: Any) -> str:
        """Map vCD VM status to normalized status string."""
        if isinstance(raw_status, int):
            return _VCD_STATUS_MAP.get(raw_status, "unknown")
        if isinstance(raw_status, str):
            # Try string map first, then try parsing as int
            if raw_status in _VCD_STATUS_STR_MAP:
                return _VCD_STATUS_STR_MAP[raw_status]
            try:
                return _VCD_STATUS_MAP.get(int(raw_status), "unknown")
            except (ValueError, TypeError):
                return "unknown"
        return "unknown"

    def _extract_ips(self, record: Dict[str, Any]) -> List[str]:
        """Extract IP addresses from a vCD VM record."""
        ips: List[str] = []
        # vCD query API may include ipAddress field
        ip = record.get("ipAddress")
        if ip:
            ips.append(ip)
        # Some records have a nested list of networkConnections
        for conn in record.get("networkConnections", []):
            conn_ip = conn.get("ipAddress")
            if conn_ip and conn_ip not in ips:
                ips.append(conn_ip)
        return ips

    def _record_to_vminfo(self, record: Dict[str, Any]) -> VMInfo:
        """Convert a vCD VM record to a VMInfo object."""
        return VMInfo(
            name=record.get("name", ""),
            id=record.get("href", record.get("id", "")),
            status=self._map_status(record.get("status")),
            ip_addresses=self._extract_ips(record),
            vcpus=int(record.get("numberOfCpus", 0)),
            memory_mb=int(record.get("memoryMB", 0)),
            provider=self.get_provider_name(),
            cloud_name=record.get("org", ""),
            folder_name=record.get("vdc", ""),
        )

    def fetch_all_data(self) -> Dict[str, Any]:
        """Fetch all vCloud data in the format expected by the NetBox sync pipeline.

        Returns a dict compatible with the structure from YandexCloudClient.fetch_all_data(),
        so the same sync pipeline can process both providers.
        """
        if not self.auth_token:
            self.authenticate()

        records = self.fetch_all_vm_records()

        # Extract unique (org, vdc) pairs as folders
        seen_folders: Dict[str, Dict[str, str]] = {}
        for rec in records:
            vdc = rec.get("vdc", "")
            if vdc and vdc not in seen_folders:
                seen_folders[vdc] = {
                    "id": vdc,
                    "name": vdc,
                    "cloud_name": rec.get("org", ""),
                    "description": "",
                }

        # Convert VM records to sync-pipeline-compatible dicts
        vms: List[Dict[str, Any]] = []
        for rec in records:
            raw_status = rec.get("status")
            if isinstance(raw_status, int):
                status = "RUNNING" if raw_status == 4 else "STOPPED"
            elif isinstance(raw_status, str):
                status = "RUNNING" if raw_status == "POWERED_ON" else "STOPPED"
            else:
                status = "STOPPED"

            memory_mb = int(rec.get("memoryMB", 0))
            # Convert MiB → bytes so resources.memory matches YC format.
            # The sync pipeline later applies parse_memory_mb() for NetBox scaling.
            memory_bytes = memory_mb * 1024 * 1024

            cpus = int(rec.get("numberOfCpus", 0))

            # Build network interfaces from available IP data
            network_interfaces: List[Dict[str, Any]] = []
            primary_ip = rec.get("ipAddress")
            if primary_ip:
                network_interfaces.append({
                    "index": 0,
                    "primary_v4_address": primary_ip,
                    "primary_v4_address_one_to_one_nat": None,
                    "vpc_id": None,
                    "vpc_name": None,
                    "subnet_id": None,
                    "subnet_name": None,
                    "zone_id": None,
                })

            # Additional IPs from networkConnections
            for idx, conn in enumerate(rec.get("networkConnections", [])):
                conn_ip = conn.get("ipAddress")
                if conn_ip and conn_ip != primary_ip:
                    network_interfaces.append({
                        "index": len(network_interfaces),
                        "primary_v4_address": conn_ip,
                        "primary_v4_address_one_to_one_nat": None,
                        "vpc_id": None,
                        "vpc_name": None,
                        "subnet_id": None,
                        "subnet_name": None,
                        "zone_id": None,
                    })

            vdc = rec.get("vdc", "")
            org = rec.get("org", "")

            vms.append({
                "id": rec.get("href", rec.get("id", "")),
                "name": rec.get("name", ""),
                "status": status,
                "folder_id": vdc,
                "folder_name": vdc,
                "cloud_id": org,
                "cloud_name": org,
                "zone_id": None,
                "resources": {
                    "memory": memory_bytes,
                    "cores": cpus,
                },
                "disks": [],
                "network_interfaces": network_interfaces,
                "os": rec.get("guestOs", ""),
                "description": "",
                "labels": {},
                "created_at": None,
                "platform_id": "",
            })

        return {
            "zones": [],
            "clouds": [],
            "vpcs": [],
            "subnets": [],
            "folders": list(seen_folders.values()),
            "vms": vms,
            "_has_fetch_errors": False,
            "_provider": "vcloud",
        }

    # -- CloudProvider interface --

    def get_provider_name(self) -> str:
        """Return provider identifier."""
        return "vcloud"

    def fetch_vms(self) -> List[VMInfo]:
        """Fetch all VMs and return them as normalized VMInfo objects."""
        if not self.auth_token:
            self.authenticate()
        records = self.fetch_all_vm_records()
        return [self._record_to_vminfo(r) for r in records]
