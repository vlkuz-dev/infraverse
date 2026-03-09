"""
NetBox client for managing virtualization resources.
Maps Yandex Cloud structure to NetBox:
- Sites = Availability Zones
- Cluster Type = yandex-cloud
- Clusters = Folders
"""

import logging
from typing import Any, Dict, List, Optional

import pynetbox
from pynetbox.core.response import Record

from infraverse.providers.base import VMInfo
from infraverse.providers.netbox_infrastructure import NetBoxInfrastructureMixin
from infraverse.providers.netbox_tags import NetBoxTagsMixin

logger = logging.getLogger(__name__)


class NetBoxClient(NetBoxInfrastructureMixin, NetBoxTagsMixin):
    """NetBox API client for VM synchronization with Yandex Cloud mapping."""

    def __init__(
        self,
        url: str,
        token: str,
        dry_run: bool = False
    ):
        """
        Initialize NetBox client.

        Args:
            url: NetBox API URL
            token: NetBox API token
            dry_run: If True, don't make actual changes
        """
        self.nb = pynetbox.api(url, token=token)
        self.dry_run = dry_run
        self._cluster_type_cache: Dict[str, int] = {}
        self._cluster_type_id: Optional[int] = None  # backward compat shortcut

        logger.info(f"Initialized NetBox client for {url} (dry_run={dry_run})")
        self._sync_tag_cache: Dict[str, int] = {}
        self._sync_tag_id: Optional[int] = None  # backward compat shortcut

    def ensure_prefix(
        self,
        prefix: str,
        vpc_name: str,
        site_id: Optional[int] = None,
        description: str = ""
    ) -> Optional[Record]:
        """
        Ensure IP prefix exists in NetBox.

        Args:
            prefix: CIDR prefix (e.g., "10.0.0.0/24")
            vpc_name: VPC name for description
            site_id: Optional Site ID (can be None)
            description: Optional description

        Returns:
            Prefix object or None
        """
        # Validate site_id - treat 0 as None
        if site_id == 0:
            site_id = None

        if site_id is None:
            logger.debug(f"No site_id provided for prefix {prefix}, will create without scope assignment")

        # Check if prefix exists
        try:
            existing = self.nb.ipam.prefixes.get(prefix=prefix)
        except Exception as e:
            logger.error(f"Failed to check existing prefix {prefix}: {e}")
            return None

        if existing:
            # Try to update scope if different and site_id is provided
            if site_id is not None and not self.dry_run:
                try:
                    # Check current scope (NetBox 4.2+ uses scope instead of site)
                    current_site_id = None
                    try:
                        # NetBox 4.2+ uses scope_type and scope_id
                        if hasattr(existing, 'scope_type') and hasattr(existing, 'scope_id'):
                            if existing.scope_type == "dcim.site" and existing.scope_id:
                                current_site_id = existing.scope_id
                        # Fallback for older NetBox versions
                        elif hasattr(existing, 'site'):
                            site_obj = getattr(existing, 'site', None)
                            if site_obj:
                                if hasattr(site_obj, 'id'):
                                    current_site_id = site_obj.id
                                elif isinstance(site_obj, dict):
                                    current_site_id = site_obj.get('id')
                                elif isinstance(site_obj, (int, str)):
                                    current_site_id = site_obj
                    except (AttributeError, TypeError) as e:
                        logger.debug(f"Could not get current scope/site for prefix {prefix}: {e}")

                    # Only update if site is different
                    if current_site_id != site_id:
                        # Update the scope using the appropriate fields
                        try:
                            # For NetBox 4.2+, use scope_type and scope_id
                            update_data = {
                                "scope_type": "dcim.site",
                                "scope_id": site_id
                            }
                            success = self.update_prefix(existing.id, update_data)
                            if success:
                                logger.info(
                                    f"Updated prefix {prefix} scope assignment "
                                    f"from site {current_site_id} to {site_id}"
                                )
                            else:
                                # Try fallback method for older NetBox versions
                                fallback_data = {"site": site_id}
                                success = self.update_prefix(existing.id, fallback_data)
                                if success:
                                    logger.info(
                                        f"Updated prefix {prefix} site assignment "
                                        f"from {current_site_id} to {site_id} (using legacy field)"
                                    )
                                else:
                                    logger.error(
                                        f"Cannot update prefix {prefix} scope/site assignment. "
                                        f"Check NetBox version compatibility and API token permissions."
                                    )
                        except Exception as e:
                            logger.warning(f"Failed to update prefix {prefix} scope/site: {e}")
                except Exception as e:
                    logger.debug(f"Error checking/updating scope for prefix {prefix}: {e}")

            # Add sync tag to existing prefix
            tag_id = self.ensure_sync_tag()
            if tag_id:
                self._add_tag_to_object(existing, tag_id)

            logger.debug(f"Using existing prefix {prefix}")
            return existing

        # Create prefix if it doesn't exist
        if self.dry_run:
            logger.info(f"[DRY-RUN] Would create prefix: {prefix}")
            return None

        # Ensure tag exists
        tag_id = self.ensure_sync_tag()

        try:
            # Build creation data
            prefix_data = {
                "prefix": prefix,
                "status": "active",
                "description": f"VPC: {vpc_name}\n{description}".strip()
            }

            # Only add scope if provided and valid
            # NetBox 4.2+ uses scope_type and scope_id instead of site
            if site_id is not None:
                # Try NetBox 4.2+ format first
                prefix_data["scope_type"] = "dcim.site"
                prefix_data["scope_id"] = site_id

            # Add tag if available
            if tag_id:
                prefix_data["tags"] = [tag_id]

            try:
                prefix_obj = self.nb.ipam.prefixes.create(prefix_data)
                site_msg = f" in site {site_id}" if site_id is not None else " (no site)"
                logger.info(f"Created prefix: {prefix}" + site_msg)
                return prefix_obj
            except Exception as e:
                # If scope_type/scope_id failed, try with legacy site field
                if site_id is not None and "scope" in str(e).lower():
                    logger.debug("Scope fields not supported, trying legacy site field")
                    prefix_data = {
                        "prefix": prefix,
                        "status": "active",
                        "description": f"VPC: {vpc_name}\n{description}".strip(),
                        "site": site_id
                    }
                    if tag_id:
                        prefix_data["tags"] = [tag_id]

                    try:
                        prefix_obj = self.nb.ipam.prefixes.create(prefix_data)
                        logger.info(f"Created prefix: {prefix} in site {site_id} (using legacy field)")
                        return prefix_obj
                    except Exception as e2:
                        logger.warning(f"Failed to create prefix {prefix}: {e2}")
                        return None
                else:
                    logger.warning(f"Failed to create prefix {prefix}: {e}")
                    return None
        except Exception as e:
            logger.warning(f"Failed to create prefix {prefix}: {e}")
            return None

    def update_prefix(self, prefix_id: int, updates: Dict[str, Any]) -> bool:
        """
        Update a prefix in NetBox.

        Args:
            prefix_id: Prefix ID to update
            updates: Dictionary of fields to update (e.g., {"site": site_id})

        Returns:
            True if successful, False otherwise

        Note:
            Requires 'ipam.change_prefix' permission on the NetBox API token.
            Without this permission, all update attempts will fail with 403 Forbidden.
            NetBox 4.2+ uses scope_type/scope_id instead of site field for prefixes.
        """
        if self.dry_run:
            logger.info(f"[DRY-RUN] Would update prefix {prefix_id} with: {updates}")
            return True

        try:
            # Get a fresh copy of the prefix object
            prefix_obj = self.nb.ipam.prefixes.get(id=prefix_id)
            if not prefix_obj:
                logger.error(f"Prefix with ID {prefix_id} not found")
                return False

            # Log the current state for debugging
            logger.debug(f"Current prefix state: {dict(prefix_obj)}")
            logger.debug(f"Attempting to apply updates: {updates}")

            # Update fields on the object
            for key, value in updates.items():
                # Handle scope fields for NetBox 4.2+ compatibility
                if key in ["scope_type", "scope_id"]:
                    setattr(prefix_obj, key, value)
                # For legacy site field, handle None values properly
                elif key == "site" and value is None:
                    # Clear the site assignment
                    if hasattr(prefix_obj, 'site'):
                        prefix_obj.site = None
                else:
                    setattr(prefix_obj, key, value)

            # Save changes using pynetbox
            try:
                result = prefix_obj.save()
                if result:
                    logger.info(f"Successfully updated prefix {prefix_id} with changes: {updates}")
                    return True
                else:
                    logger.warning(
                        f"Prefix save() returned False for {prefix_id}. "
                        f"This typically means the API token lacks 'ipam.change_prefix' permission."
                    )
            except Exception as save_error:
                # Check if it's a permission error
                error_str = str(save_error).lower()
                if "403" in error_str or "forbidden" in error_str or "permission" in error_str:
                    logger.error(
                        f"Permission denied when updating prefix {prefix_id}. "
                        f"The NetBox API token needs 'ipam.change_prefix' permission. Error: {save_error}"
                    )
                else:
                    logger.debug(f"Save failed, trying alternative method: {save_error}")

            # Alternative method: Use the update() method if available
            try:
                if hasattr(prefix_obj, 'update'):
                    prefix_obj.update(updates)
                    logger.info(f"Successfully updated prefix {prefix_id} using update() method")
                    return True
            except Exception as update_error:
                logger.debug(f"Update method failed: {update_error}")

            # Last resort: Use direct API call
            try:
                # Construct the URL properly
                base_url = str(self.nb.base_url).rstrip('/')
                # Check if base_url already has /api, if not add it
                if not base_url.endswith('/api'):
                    base_url = f"{base_url}/api"

                url = f"{base_url}/ipam/prefixes/{prefix_id}/"

                # Use PATCH to update only specified fields
                headers = {"Authorization": f"Token {self.nb.token}"}
                response = self.nb.http_session.patch(url, json=updates, headers=headers)
                response.raise_for_status()

                logger.info(f"Successfully updated prefix {prefix_id} using direct API")
                return True
            except Exception as api_error:
                error_str = str(api_error).lower()
                if "403" in error_str or "forbidden" in error_str:
                    logger.error(
                        f"HTTP 403 Forbidden when updating prefix {prefix_id}. "
                        f"The NetBox API token must have 'ipam.change_prefix' permission. "
                        f"Current token may only have 'ipam.add_prefix' which is insufficient for updates."
                    )
                    logger.info(
                        "To fix this issue:\n"
                        "1. Log into NetBox as an admin\n"
                        "2. Navigate to Admin -> API Tokens\n"
                        "3. Find your token and edit it\n"
                        "4. Add 'ipam | prefix | Can change prefix' permission\n"
                        "5. Save and retry the operation"
                    )
                else:
                    logger.error(f"All update methods failed for prefix {prefix_id}: {api_error}")
                return False

        except Exception as e:
            logger.error(f"Failed to update prefix {prefix_id}: {e}")
            return False

    def fetch_vms(self) -> List[Record]:
        """
        Fetch all VMs from NetBox.

        Returns:
            list of VM objects
        """
        try:
            vms = list(self.nb.virtualization.virtual_machines.all())
            logger.info(f"Fetched {len(vms)} VMs from NetBox")
            return vms
        except Exception as e:
            logger.error(f"Failed to fetch VMs: {e}")
            return []

    def fetch_all_vms(self) -> List[VMInfo]:
        """
        Fetch all VMs from NetBox as VMInfo objects for comparison.

        Returns:
            list of VMInfo objects

        Raises:
            Exception: If the NetBox API call fails.
        """
        records = list(self.nb.virtualization.virtual_machines.all())
        result = []
        for vm in records:
            ip_addresses = []
            if hasattr(vm, 'primary_ip4') and vm.primary_ip4:
                addr = str(vm.primary_ip4).split('/')[0]
                ip_addresses.append(addr)
            if hasattr(vm, 'primary_ip6') and vm.primary_ip6:
                addr = str(vm.primary_ip6).split('/')[0]
                ip_addresses.append(addr)

            status = "unknown"
            if hasattr(vm, 'status') and vm.status:
                raw = vm.status.value if hasattr(vm.status, 'value') else str(vm.status)
                if raw == "active":
                    status = "active"
                elif raw in ("offline", "decommissioning"):
                    status = "offline"

            cluster_name = ""
            if hasattr(vm, 'cluster') and vm.cluster:
                cluster_name = str(vm.cluster)

            tenant_name = ""
            if hasattr(vm, 'tenant') and vm.tenant:
                tenant_name = str(vm.tenant)

            result.append(VMInfo(
                name=vm.name,
                id=str(vm.id),
                status=status,
                ip_addresses=ip_addresses,
                vcpus=int(vm.vcpus or 0),
                memory_mb=vm.memory or 0,
                provider="netbox",
                cloud_name="",
                folder_name=cluster_name,
                tenant_name=tenant_name,
            ))
        logger.info(f"Fetched {len(result)} VMs from NetBox as VMInfo")
        return result

    def create_vm(self, vm_data: Dict[str, Any], tag_slug: Optional[str] = None) -> Optional[Record]:
        """
        Create VM in NetBox.

        Args:
            vm_data: VM data dictionary with name, cluster, vcpus, memory, status
                     Note: disk field should not be set directly, it's calculated from virtual disks
            tag_slug: Optional tag slug (default: "synced-from-yc")

        Returns:
            Created VM object or None
        """
        if self.dry_run:
            logger.info(f"[DRY-RUN] Would create VM: {vm_data.get('name')}")

            # Return mock object for dry run
            class MockVM:
                def __init__(self):
                    self.id = 1
                    self.name = vm_data.get('name')
                    self.site = None
                    self.cluster = None
            return MockVM()

        # Ensure tag exists
        tag_kwargs = {"tag_slug": tag_slug} if tag_slug else {}
        tag_id = self.ensure_sync_tag(**tag_kwargs)

        # Add tag to VM data if available
        if tag_id:
            vm_data["tags"] = [tag_id]

        # Remove disk field if present (it should be calculated from virtual disks)
        if "disk" in vm_data:
            logger.debug(
                f"Removing disk field from VM data for {vm_data.get('name')} "
                f"- will be calculated from virtual disks"
            )
            vm_data.pop("disk")

        try:
            vm = self.nb.virtualization.virtual_machines.create(vm_data)
            logger.info(f"Created VM: {vm.name} (ID: {vm.id})")
            return vm
        except Exception as e:
            logger.error(f"Failed to create VM {vm_data.get('name')}: {e}")
            return None

    def create_disk(self, disk_data: Dict[str, Any]) -> Optional[Record]:
        """
        Create virtual disk in NetBox.

        Args:
            disk_data: Disk data with virtual_machine, size, name

        Returns:
            Created disk object or None
        """
        if self.dry_run:
            logger.info(f"[DRY-RUN] Would create disk: {disk_data.get('name')}")
            return None

        try:
            # NetBox 3.x uses virtual-disks endpoint
            if hasattr(self.nb.virtualization, 'virtual_disks'):
                disk = self.nb.virtualization.virtual_disks.create(disk_data)
                logger.debug(f"Created disk: {disk.name}")
                return disk
            else:
                logger.debug("Virtual disks not supported in this NetBox version")
                return None
        except Exception as e:
            logger.error(f"Failed to create disk: {e}")
            return None

    def create_interface(self, interface_data: Dict[str, Any]) -> Optional[Record]:
        """
        Create VM interface in NetBox.

        Args:
            interface_data: Interface data with virtual_machine, name

        Returns:
            Created interface object or None
        """
        if self.dry_run:
            logger.info(f"[DRY-RUN] Would create interface: {interface_data.get('name')}")

            # Return mock object for dry run
            class MockInterface:
                def __init__(self):
                    self.id = 1
                    self.name = interface_data.get('name')
                    self.virtual_machine = interface_data.get('virtual_machine')
            return MockInterface()

        try:
            # Set default type if not provided
            if 'type' not in interface_data:
                interface_data['type'] = 'virtual'

            interface = self.nb.virtualization.interfaces.create(interface_data)
            logger.debug(f"Created interface: {interface.name}")
            return interface
        except Exception as e:
            logger.error(f"Failed to create interface: {e}")
            return None

    def create_ip(self, ip_data: Dict[str, Any]) -> Optional[Record]:
        """
        Create IP address in NetBox.

        Args:
            ip_data: IP data with address, interface

        Returns:
            Created IP object or None
        """
        if self.dry_run:
            logger.info(f"[DRY-RUN] Would create IP: {ip_data.get('address')}")
            return None

        try:
            # Ensure address has CIDR notation
            address = ip_data['address']
            if '/' not in address:
                address = f"{address}/32"
                ip_data['address'] = address

            # Get the base IP without mask for searching
            base_ip = address.split('/')[0]

            # Search for IPs matching the base address (regardless of mask)
            existing_ips = list(self.nb.ipam.ip_addresses.filter(
                address__ic=base_ip  # Case-insensitive contains search
            ))

            # Find exact IP match (same address, any mask)
            existing_ip = None
            for ip in existing_ips:
                if ip.address.split('/')[0] == base_ip:
                    existing_ip = ip
                    break

            if existing_ip:
                # Update interface assignment if different
                try:
                    current_interface_id = getattr(existing_ip, 'assigned_object_id', None)
                    # Handle both old and new data formats
                    if 'interface' in ip_data:
                        new_interface_id = ip_data['interface']
                        new_object_type = 'virtualization.vminterface'
                    else:
                        new_interface_id = ip_data.get('assigned_object_id')
                        new_object_type = ip_data.get('assigned_object_type', 'virtualization.vminterface')

                    if current_interface_id != new_interface_id and new_interface_id:
                        if not self.dry_run:
                            existing_ip.assigned_object_type = new_object_type
                            existing_ip.assigned_object_id = new_interface_id
                            existing_ip.save()
                            logger.debug(f"Updated existing IP: {base_ip} (as {existing_ip.address})")
                except Exception as e:
                    logger.debug(f"Could not update IP assignment for {address}: {e}")
                return existing_ip

            # Create new IP - handle both old and new data formats
            create_data = {
                "address": address,
                "status": ip_data.get("status", "active")
            }

            # Handle old format with 'interface' key
            if 'interface' in ip_data:
                create_data["assigned_object_type"] = "virtualization.vminterface"
                create_data["assigned_object_id"] = ip_data['interface']
            # Handle new format with direct assignment fields
            elif 'assigned_object_id' in ip_data:
                create_data["assigned_object_type"] = ip_data.get('assigned_object_type', 'virtualization.vminterface')
                create_data["assigned_object_id"] = ip_data['assigned_object_id']

            # Add description if provided
            if 'description' in ip_data:
                create_data["description"] = ip_data['description']

            ip_obj = self.nb.ipam.ip_addresses.create(create_data)
            logger.debug(f"Created IP: {ip_obj.address}")
            return ip_obj
        except Exception as e:
            logger.error(f"Failed to create IP {ip_data.get('address')}: {e}")
            return None

    def update_vm(self, vm_id: int, updates: Dict[str, Any]) -> bool:
        """
        Update VM in NetBox.

        Args:
            vm_id: VM ID
            updates: Dictionary of fields to update

        Returns:
            True if successful, False otherwise
        """
        if self.dry_run:
            logger.info(f"[DRY-RUN] Would update VM {vm_id}: {updates}")
            return True

        try:
            vm = self.nb.virtualization.virtual_machines.get(id=vm_id)
            if not vm:
                logger.error(f"VM with ID {vm_id} not found")
                return False

            # Remove disk field from updates if present (it should be calculated from virtual disks)
            if "disk" in updates:
                logger.debug(f"Removing disk field from updates for VM {vm_id} - will be calculated from virtual disks")
                updates.pop("disk")

            for key, value in updates.items():
                setattr(vm, key, value)

            vm.save()

            # Add sync tag
            tag_id = self.ensure_sync_tag()
            if tag_id:
                self._add_tag_to_object(vm, tag_id)

            logger.info(f"Updated VM {vm.name}")
            return True
        except Exception as e:
            logger.error(f"Failed to update VM {vm_id}: {e}")
            return False

    def set_vm_primary_ip(self, vm_id: int, ip_id: int, ip_version: int = 4) -> bool:
        """
        Set primary IP address for a VM.

        Args:
            vm_id: VM ID
            ip_id: IP address ID to set as primary
            ip_version: IP version (4 or 6), defaults to 4

        Returns:
            True if successful, False otherwise
        """
        if self.dry_run:
            logger.info(f"[DRY-RUN] Would set primary IPv{ip_version} (ID: {ip_id}) for VM {vm_id}")
            return True

        try:
            vm = self.nb.virtualization.virtual_machines.get(id=vm_id)
            if not vm:
                logger.error(f"VM with ID {vm_id} not found")
                return False

            # Get the IP address object
            ip = self.nb.ipam.ip_addresses.get(id=ip_id)
            if not ip:
                logger.error(f"IP address with ID {ip_id} not found")
                return False

            # Check if IP is assigned to one of this VM's interfaces
            vm_interfaces = list(self.nb.virtualization.interfaces.filter(virtual_machine_id=vm_id))
            ip_assigned_to_vm = False

            if hasattr(ip, 'assigned_object_id') and ip.assigned_object_id:
                # Check if it's assigned to one of this VM's interfaces
                for iface in vm_interfaces:
                    if ip.assigned_object_id == iface.id:
                        ip_assigned_to_vm = True
                        break

            # If not assigned to this VM, assign it to the first interface
            if not ip_assigned_to_vm:
                if not vm_interfaces:
                    logger.error(f"VM {vm.name} has no interfaces to assign IP to")
                    return False

                logger.info(f"Assigning IP {ip.address} to VM {vm.name}'s first interface before setting as primary")
                ip.assigned_object_type = "virtualization.vminterface"
                ip.assigned_object_id = vm_interfaces[0].id
                ip.save()

            # Set primary IP based on version
            if ip_version == 4:
                vm.primary_ip4 = ip_id
            elif ip_version == 6:
                vm.primary_ip6 = ip_id
            else:
                logger.error(f"Invalid IP version: {ip_version}")
                return False

            vm.save()
            logger.info(f"Set primary IPv{ip_version} {ip.address} (ID: {ip_id}) for VM {vm.name}")
            return True
        except Exception as e:
            logger.error(f"Failed to set primary IPv{ip_version} for VM {vm_id}: {e}")
            return False

    def get_vm_by_name(self, name: str) -> Optional[Record]:
        """
        Get VM by name.

        Args:
            name: VM name

        Returns:
            VM object or None
        """
        try:
            vm = self.nb.virtualization.virtual_machines.get(name=name)
            return vm
        except Exception as e:
            logger.error(f"Failed to get VM {name}: {e}")
            return None

    def get_vm_by_custom_field(self, field_name: str, field_value: str) -> Optional[Record]:
        """
        Get VM by custom field value (e.g., yc_id).

        Args:
            field_name: Custom field name
            field_value: Custom field value

        Returns:
            VM object or None
        """
        try:
            vms = self.nb.virtualization.virtual_machines.filter(**{f"cf_{field_name}": field_value})
            if vms:
                return vms[0]
            return None
        except Exception as e:
            logger.error(f"Failed to get VM by {field_name}={field_value}: {e}")
            return None
