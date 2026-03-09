"""VM networking — sync interfaces, IPs, and primary IP assignment."""

import logging
from typing import Any, Dict

from infraverse.providers.netbox import NetBoxClient
from infraverse.ip import is_private_ip, get_ip_without_cidr, ensure_cidr_notation

logger = logging.getLogger(__name__)


def update_vm_primary_ip(
    vm: Any,
    yc_vm: Dict[str, Any],
    netbox: NetBoxClient
) -> bool:
    """
    Check and update primary IP for an existing VM if not set.
    Always prefers private IPs over public IPs for primary assignment.

    Args:
        vm: Existing NetBox VM object
        yc_vm: Yandex Cloud VM data
        netbox: NetBox client

    Returns:
        True if updated, False otherwise
    """
    try:
        network_interfaces = yc_vm.get("network_interfaces", [])
        if not isinstance(network_interfaces, list) or not network_interfaces:
            return False

        # Look for private IPs first, then public
        expected_private_ip = None
        expected_public_ip = None

        for iface in network_interfaces:
            if not isinstance(iface, dict):
                continue

            primary_v4 = iface.get("primary_v4_address")
            if primary_v4 and isinstance(primary_v4, str):
                if is_private_ip(primary_v4):
                    expected_private_ip = primary_v4
                    break
                elif not expected_public_ip:
                    expected_public_ip = primary_v4

            nat_v4 = iface.get("primary_v4_address_one_to_one_nat")
            if nat_v4 and isinstance(nat_v4, str) and not expected_public_ip:
                expected_public_ip = nat_v4

        # Prefer private IP over public
        expected_primary_ip = expected_private_ip if expected_private_ip else expected_public_ip
        if not expected_primary_ip:
            return False

        expected_base_ip = get_ip_without_cidr(expected_primary_ip)

        # Check if VM already has the correct primary IPv4 set
        if hasattr(vm, 'primary_ip4') and vm.primary_ip4:
            current_primary_base = get_ip_without_cidr(str(vm.primary_ip4.address))
            if current_primary_base == expected_base_ip:
                logger.debug(f"VM {vm.name} already has correct primary IPv4 set: {current_primary_base}")
                return False
            else:
                current_is_private = is_private_ip(current_primary_base)
                expected_is_private = is_private_ip(expected_base_ip)
                if not current_is_private and expected_is_private:
                    logger.info(
                        f"VM {vm.name}: Will switch primary from public IP "
                        f"{current_primary_base} to private IP {expected_base_ip}"
                    )
                else:
                    logger.info(f"VM {vm.name}: Will update primary from {current_primary_base} to {expected_base_ip}")

        primary_v4 = expected_primary_ip
        base_ip = expected_base_ip
        primary_v4 = ensure_cidr_notation(primary_v4)

        # Try to find this IP in NetBox
        try:
            existing_ips = list(netbox.nb.ipam.ip_addresses.filter(
                address__ic=base_ip
            ))

            existing_ip = None
            for ip in existing_ips:
                if ip.address.split('/')[0] == base_ip:
                    existing_ip = ip
                    break

            if existing_ip:
                if netbox.dry_run:
                    logger.info(f"[DRY-RUN] Would set primary IPv4 for VM {vm.name}: {base_ip}")
                    return True

                # First, check if this IP is set as primary on any other VM
                vms_with_primary = list(netbox.nb.virtualization.virtual_machines.filter(
                    primary_ip4_id=existing_ip.id
                ))

                for vm_with_primary in vms_with_primary:
                    if vm_with_primary.id != vm.id:
                        logger.info(f"Unsetting IP {base_ip} as primary on VM {vm_with_primary.name}")
                        vm_with_primary.primary_ip4 = None
                        vm_with_primary.save()

                # Check if IP is assigned to this VM's interface
                vm_interfaces = list(netbox.nb.virtualization.interfaces.filter(virtual_machine_id=vm.id))
                ip_assigned_to_vm = False

                if hasattr(existing_ip, 'assigned_object_id') and existing_ip.assigned_object_id:
                    for iface in vm_interfaces:
                        if existing_ip.assigned_object_id == iface.id:
                            ip_assigned_to_vm = True
                            break

                # If not assigned to this VM, assign it to the first interface
                if not ip_assigned_to_vm and vm_interfaces:
                    logger.info(f"Assigning IP {base_ip} to VM {vm.name}'s first interface")
                    existing_ip.assigned_object_type = "virtualization.vminterface"
                    existing_ip.assigned_object_id = vm_interfaces[0].id
                    existing_ip.save()

                # Now set as primary IP
                if netbox.set_vm_primary_ip(vm.id, existing_ip.id, ip_version=4):
                    logger.info(f"Updated primary IPv4 for VM {vm.name}: {base_ip} (as {existing_ip.address})")
                    return True
        except Exception as e:
            logger.debug(f"Could not find or set primary IP for {vm.name}: {e}")

        return False
    except Exception as e:
        logger.error(f"Failed to update primary IP for VM {vm.name}: {e}")
        return False


def sync_vm_interfaces(
    vm: Any,
    yc_vm: Dict[str, Any],
    netbox: NetBoxClient
) -> Dict[str, int]:
    """
    Synchronize network interfaces and IP addresses for an existing VM.

    Args:
        vm: Existing NetBox VM object
        yc_vm: Yandex Cloud VM data
        netbox: NetBox client

    Returns:
        Dictionary with sync statistics
    """
    result = {
        "interfaces_created": 0,
        "ips_created": 0,
        "errors": 0
    }

    try:
        yc_interfaces = yc_vm.get("network_interfaces", [])
        if not isinstance(yc_interfaces, list):
            return result

        try:
            existing_interfaces = list(netbox.nb.virtualization.interfaces.filter(virtual_machine_id=vm.id))
        except Exception as e:
            logger.error(f"Failed to get interfaces for VM {vm.name}: {e}")
            return result

        existing_interface_names = {iface.name: iface for iface in existing_interfaces}

        for idx, yc_iface in enumerate(yc_interfaces):
            if not isinstance(yc_iface, dict):
                continue

            interface_name = f"eth{idx}"

            if interface_name in existing_interface_names:
                nb_interface = existing_interface_names[interface_name]
                logger.debug(f"Interface {interface_name} already exists for VM {vm.name}")
            else:
                interface_data = {
                    "virtual_machine": vm.id,
                    "name": interface_name,
                    "type": "virtual",
                    "enabled": True
                }

                nb_interface = netbox.create_interface(interface_data)
                if nb_interface:
                    logger.info(f"Created interface {interface_name} for VM {vm.name}")
                    result["interfaces_created"] += 1
                else:
                    logger.error(f"Failed to create interface {interface_name} for VM {vm.name}")
                    result["errors"] += 1
                    continue

            # Process IP addresses for this interface
            primary_v4 = yc_iface.get("primary_v4_address")
            if primary_v4 and isinstance(primary_v4, str):
                base_ip = get_ip_without_cidr(primary_v4)
                primary_v4 = ensure_cidr_notation(primary_v4)

                try:
                    existing_ips = list(netbox.nb.ipam.ip_addresses.filter(
                        address__ic=base_ip
                    ))

                    existing_ip = None
                    for ip in existing_ips:
                        if ip.address.split('/')[0] == base_ip:
                            existing_ip = ip
                            break

                    if existing_ip:
                        if (hasattr(existing_ip, 'assigned_object_id')
                                and existing_ip.assigned_object_id == nb_interface.id):
                            logger.debug(
                                f"IP {base_ip} (as {existing_ip.address}) already exists "
                                f"for interface {interface_name} on VM {vm.name}"
                            )
                        else:
                            logger.debug(
                                f"IP {base_ip} (as {existing_ip.address}) exists but "
                                f"not assigned to {interface_name}, updating assignment"
                            )
                            if netbox.dry_run:
                                logger.info(
                                    f"[DRY-RUN] Would reassign IP {base_ip} to "
                                    f"interface {interface_name} on VM {vm.name}"
                                )
                                result["ips_created"] += 1
                            else:
                                try:
                                    if hasattr(existing_ip, 'assigned_object_id') and existing_ip.assigned_object_id:
                                        vms_with_primary = list(netbox.nb.virtualization.virtual_machines.filter(
                                            primary_ip4_id=existing_ip.id
                                        ))
                                        for vm_with_primary in vms_with_primary:
                                            logger.info(
                                                f"Unsetting IP {base_ip} as primary "
                                                f"on VM {vm_with_primary.name}"
                                            )
                                            vm_with_primary.primary_ip4 = None
                                            vm_with_primary.save()

                                    existing_ip.assigned_object_type = "virtualization.vminterface"
                                    existing_ip.assigned_object_id = nb_interface.id
                                    existing_ip.save()
                                    logger.info(
                                        f"Updated IP {base_ip} (as {existing_ip.address}) "
                                        f"assignment to interface {interface_name} "
                                        f"on VM {vm.name}"
                                    )
                                    result["ips_created"] += 1
                                except Exception as e:
                                    logger.error(f"Failed to update IP {base_ip} assignment: {e}")
                                    result["errors"] += 1
                    else:
                        ip_data = {
                            "address": primary_v4,
                            "assigned_object_type": "virtualization.vminterface",
                            "assigned_object_id": nb_interface.id,
                            "status": "active",
                            "description": "Private IP" if is_private_ip(primary_v4) else ""
                        }

                        created_ip = netbox.create_ip(ip_data)
                        if created_ip:
                            logger.info(f"Created IP {primary_v4} for interface {interface_name} on VM {vm.name}")
                            result["ips_created"] += 1
                        else:
                            logger.error(
                                f"Failed to create IP {primary_v4} for "
                                f"interface {interface_name} on VM {vm.name}"
                            )
                            result["errors"] += 1

                except Exception as e:
                    logger.error(f"Failed to process IP {primary_v4} for VM {vm.name}: {e}")
                    result["errors"] += 1

            # Process public IP (NAT) if exists
            public_v4 = yc_iface.get("primary_v4_address_one_to_one_nat")
            if public_v4 and isinstance(public_v4, str):
                base_public_ip = get_ip_without_cidr(public_v4)
                public_v4 = ensure_cidr_notation(public_v4)

                try:
                    existing_public_ips = list(netbox.nb.ipam.ip_addresses.filter(
                        address__ic=base_public_ip
                    ))

                    existing_public_ip = None
                    for ip in existing_public_ips:
                        if ip.address.split('/')[0] == base_public_ip:
                            existing_public_ip = ip
                            break

                    if not existing_public_ip:
                        public_ip_data = {
                            "address": public_v4,
                            "assigned_object_type": "virtualization.vminterface",
                            "assigned_object_id": nb_interface.id,
                            "status": "active",
                            "description": "Public IP (NAT)"
                        }

                        created_public_ip = netbox.create_ip(public_ip_data)
                        if created_public_ip:
                            logger.info(f"Created public IP {public_v4} for interface {interface_name} on VM {vm.name}")
                            result["ips_created"] += 1
                        else:
                            logger.error(
                                f"Failed to create public IP {public_v4} for "
                                f"interface {interface_name} on VM {vm.name}"
                            )
                            result["errors"] += 1
                    else:
                        if (hasattr(existing_public_ip, 'assigned_object_id')
                                and existing_public_ip.assigned_object_id != nb_interface.id):
                            if netbox.dry_run:
                                logger.info(
                                    f"[DRY-RUN] Would reassign public IP "
                                    f"{base_public_ip} to interface "
                                    f"{interface_name} on VM {vm.name}"
                                )
                                result["ips_created"] += 1
                            else:
                                try:
                                    vms_with_primary = list(netbox.nb.virtualization.virtual_machines.filter(
                                        primary_ip4_id=existing_public_ip.id
                                    ))
                                    for vm_with_primary in vms_with_primary:
                                        logger.info(
                                            f"Unsetting public IP {base_public_ip} "
                                            f"as primary on VM {vm_with_primary.name}"
                                        )
                                        vm_with_primary.primary_ip4 = None
                                        vm_with_primary.save()

                                    existing_public_ip.assigned_object_type = "virtualization.vminterface"
                                    existing_public_ip.assigned_object_id = nb_interface.id
                                    existing_public_ip.save()
                                    logger.info(
                                        f"Updated public IP {base_public_ip} "
                                        f"(as {existing_public_ip.address}) assignment "
                                        f"to interface {interface_name} on VM {vm.name}"
                                    )
                                    result["ips_created"] += 1
                                except Exception as e:
                                    logger.error(f"Failed to update public IP {base_public_ip} assignment: {e}")
                                    result["errors"] += 1
                        else:
                            logger.debug(
                                f"Public IP {base_public_ip} "
                                f"(as {existing_public_ip.address}) "
                                f"already exists and properly assigned"
                            )

                except Exception as e:
                    logger.error(f"Failed to process public IP {public_v4} for VM {vm.name}: {e}")
                    result["errors"] += 1

        return result

    except Exception as e:
        logger.error(f"Failed to sync interfaces for VM {vm.name}: {e}")
        result["errors"] += 1
        return result
