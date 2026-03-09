"""NetBox interface, disk, and IP management methods (mixin for NetBoxClient)."""

import logging
from typing import Any, Dict, Optional

from pynetbox.core.response import Record

logger = logging.getLogger(__name__)


class NetBoxInterfacesMixin:
    """Mixin providing interface/disk/IP operations for NetBoxClient.

    Expects the host class to have: self.nb, self.dry_run.
    """

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
