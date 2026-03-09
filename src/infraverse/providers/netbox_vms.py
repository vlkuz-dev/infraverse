"""NetBox VM CRUD methods (mixin for NetBoxClient)."""

import logging
from typing import Any, Dict, List, Optional

from pynetbox.core.response import Record

from infraverse.providers.base import VMInfo

logger = logging.getLogger(__name__)


class NetBoxVMsMixin:
    """Mixin providing VM CRUD operations for NetBoxClient.

    Expects the host class to have: self.nb, self.dry_run,
    ensure_sync_tag(), _add_tag_to_object().
    """

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
