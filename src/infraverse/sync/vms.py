"""VM synchronization — prepare, update, and orchestrate VM sync to NetBox."""

import logging
from typing import Any, Dict

from infraverse.providers.netbox import NetBoxClient
from infraverse.ip import is_private_ip
from infraverse.sync.cleanup import cleanup_orphaned_vms
from infraverse.sync.size_converters import parse_memory_mb, parse_cores, parse_disk_size_mb
from infraverse.sync.vms_platform import detect_platform_id
from infraverse.sync.vms_disks import sync_vm_disks
from infraverse.sync.vms_networking import update_vm_primary_ip, sync_vm_interfaces

logger = logging.getLogger(__name__)


def prepare_vm_data(
    yc_vm: Dict[str, Any],
    netbox: NetBoxClient,
    id_mapping: Dict[str, Dict[str, int]],
    provider_profile=None,
    tenant_name: str | None = None,
) -> Dict[str, Any]:
    """Prepare VM data for NetBox creation."""
    from infraverse.sync.provider_profile import YC_PROFILE
    profile = provider_profile or YC_PROFILE
    # Get cluster ID from folder mapping
    folder_id = yc_vm.get("folder_id", "")
    cluster_id = id_mapping["folders"].get(folder_id) if folder_id else None

    if not cluster_id:
        # Fallback: create cluster on the fly if needed
        folder_name = yc_vm.get("folder_name", "default")
        cloud_name = yc_vm.get("cloud_name", "")
        if isinstance(folder_name, str) and isinstance(cloud_name, str):
            cluster_id = netbox.ensure_cluster(
                folder_name=folder_name,
                folder_id=folder_id,
                cloud_name=cloud_name,
                cluster_type_slug=profile.cluster_type_slug,
                tag_slug=profile.tag_slug,
            )

    # Calculate resources using shared helpers
    resources = yc_vm.get("resources", {})
    if not isinstance(resources, dict):
        resources = {}

    vm_name_for_log = yc_vm.get('name', 'unknown')
    memory_mb = parse_memory_mb(resources, vm_name_for_log)

    if memory_mb == 0 and resources:
        logger.warning(f"VM {vm_name_for_log}: memory calculated as 0 MB, resources: {resources}")

    vcpus = parse_cores(resources, vm_name_for_log)

    # Determine status
    status_value = yc_vm.get("status")
    if status_value == "RUNNING":
        status = "active"
    else:
        status = "offline"

    # Get VM name
    vm_name = yc_vm.get("name", "unknown")
    if not isinstance(vm_name, str):
        vm_name = "unknown"

    # Get VM ID and other metadata for comments
    vm_id = yc_vm.get("id", "unknown")
    if not isinstance(vm_id, str):
        vm_id = "unknown"

    platform_id = yc_vm.get("platform_id", "")  # Hardware platform (e.g., standard-v3)
    os_name = yc_vm.get("os", "")  # Operating system from image
    created_at = yc_vm.get("created_at", "")
    zone_id = yc_vm.get("zone_id", "")

    # Build comments with metadata
    comments_parts = [
        f"{profile.vm_comment_prefix}: {vm_id}",
        f"Zone: {zone_id}" if zone_id else None,
        f"Hardware Platform: {platform_id}" if platform_id else None,
        f"OS: {os_name}" if os_name else None,
        f"Created: {created_at}" if created_at else None,
    ]
    comments = "\n".join(filter(None, comments_parts))

    vm_data = {
        "name": vm_name,
        "vcpus": vcpus,
        "memory": memory_mb,
        "status": status,
        "comments": comments
    }

    # Add cluster if available
    if cluster_id:
        vm_data["cluster"] = cluster_id

    # Add site assignment based on zone if available
    if zone_id and zone_id in id_mapping.get("zones", {}):
        site_id = id_mapping["zones"][zone_id]
        if site_id and site_id > 0:
            vm_data["site"] = site_id

    # Map OS to NetBox platform (operating system)
    vm_data["platform"] = detect_platform_id(os_name, netbox)

    # Resolve tenant if provided
    if tenant_name:
        tenant_id = netbox.ensure_tenant(name=tenant_name)
        vm_data["tenant"] = tenant_id

    return vm_data


def update_vm_parameters(
    vm: Any,
    yc_vm: Dict[str, Any],
    netbox: NetBoxClient,
    id_mapping: Dict[str, Any],
    tenant_name: str | None = None,
    provider_profile=None,
) -> bool:
    """
    Update VM parameters (memory, CPU, site, cluster, tenant) for an existing VM.

    Args:
        vm: Existing NetBox VM object
        yc_vm: Yandex Cloud VM data
        netbox: NetBox client
        id_mapping: ID mapping for cluster and sites
        tenant_name: Optional tenant name to assign to the VM
        provider_profile: Optional provider profile for comment generation

    Returns:
        True if updated, False otherwise
    """
    try:
        vm_data = prepare_vm_data(yc_vm, netbox, id_mapping,
                                  provider_profile=provider_profile,
                                  tenant_name=tenant_name)
        updates = {}

        # Check memory
        if hasattr(vm, 'memory'):
            current_memory = vm.memory if vm.memory is not None else 0
            new_memory = vm_data['memory']
            if current_memory != new_memory:
                updates['memory'] = new_memory
                logger.info(f"VM {vm.name}: memory will be updated from {current_memory} to {new_memory} MB")

        # Check vCPUs
        if hasattr(vm, 'vcpus') and vm.vcpus != vm_data['vcpus']:
            updates['vcpus'] = vm_data['vcpus']
            logger.info(f"VM {vm.name}: vCPUs will be updated from {vm.vcpus} to {vm_data['vcpus']}")

        # Check cluster
        if 'cluster' in vm_data:
            current_cluster_id = None
            if hasattr(vm, 'cluster') and vm.cluster:
                current_cluster_id = vm.cluster.id if hasattr(vm.cluster, 'id') else vm.cluster

            new_cluster_id = vm_data['cluster']
            if current_cluster_id != new_cluster_id:
                updates['cluster'] = new_cluster_id
                logger.info(f"VM {vm.name}: cluster will be updated from {current_cluster_id} to {new_cluster_id}")

        # Check site
        if 'site' in vm_data:
            current_site_id = None
            if hasattr(vm, 'site') and vm.site:
                current_site_id = vm.site.id if hasattr(vm.site, 'id') else vm.site

            new_site_id = vm_data['site']
            if current_site_id != new_site_id:
                updates['site'] = new_site_id
                logger.info(f"VM {vm.name}: site will be updated from {current_site_id} to {new_site_id}")

        # Check platform (operating system)
        if 'platform' in vm_data:
            current_platform_id = None
            if hasattr(vm, 'platform') and vm.platform:
                current_platform_id = vm.platform.id if hasattr(vm.platform, 'id') else vm.platform

            new_platform_id = vm_data['platform']
            if current_platform_id != new_platform_id:
                updates['platform'] = new_platform_id
                logger.info(f"VM {vm.name}: platform will be updated from {current_platform_id} to {new_platform_id}")

        # Check tenant
        if 'tenant' in vm_data:
            current_tenant_id = None
            if hasattr(vm, 'tenant') and vm.tenant:
                current_tenant_id = vm.tenant.id if hasattr(vm.tenant, 'id') else vm.tenant

            new_tenant_id = vm_data['tenant']
            if current_tenant_id != new_tenant_id:
                updates['tenant'] = new_tenant_id
                logger.info(f"VM {vm.name}: tenant will be updated from {current_tenant_id} to {new_tenant_id}")

        # Check status
        if hasattr(vm, 'status') and vm.status:
            if hasattr(vm.status, 'value'):
                current_status = vm.status.value
            else:
                current_status = str(vm.status)
            if current_status != vm_data['status']:
                updates['status'] = vm_data['status']
                logger.info(f"VM {vm.name}: status will be updated from {current_status} to {vm_data['status']}")

        # Check comments
        if hasattr(vm, 'comments') and vm.comments != vm_data.get('comments', ''):
            updates['comments'] = vm_data.get('comments', '')

        # Update VM if there are changes
        if updates:
            if netbox.update_vm(vm.id, updates):
                logger.info(f"Updated VM {vm.name} parameters: {list(updates.keys())}")
                return True
            else:
                logger.error(f"Failed to update VM {vm.name}")
                return False
        else:
            logger.debug(f"VM {vm.name} is up to date")
            return False

    except Exception as e:
        logger.error(f"Failed to update parameters for VM {vm.name}: {e}")
        return False


def sync_vms(
    yc_data: Dict[str, Any],
    netbox: NetBoxClient,
    id_mapping: Dict[str, Dict[str, int]],
    cleanup_orphaned: bool = True,
    provider_profile=None,
    tenant_name: str | None = None,
) -> Dict[str, int]:
    """Sync VMs from cloud provider to NetBox. Returns statistics."""
    from infraverse.sync.provider_profile import YC_PROFILE
    profile = provider_profile or YC_PROFILE

    yc_vms = yc_data.get("vms", [])

    if not yc_vms:
        logger.info("No VMs found in %s", profile.display_name)
        return {"created": 0, "updated": 0, "skipped": 0, "deleted": 0, "errors": 0}

    logger.info(f"Found {len(yc_vms)} VMs in {profile.display_name}")

    # Clean up orphaned VMs first if requested
    deleted_count = 0
    if cleanup_orphaned:
        from infraverse.sync.cleanup import _extract_cloud_names

        logger.info("Checking for orphaned VMs to clean up...")
        cloud_names = _extract_cloud_names(yc_data)
        deleted_count = cleanup_orphaned_vms(
            yc_vms, netbox, netbox.dry_run,
            provider_profile=profile, cloud_names=cloud_names,
        )
        if deleted_count > 0:
            logger.info(f"Cleanup complete: removed {deleted_count} orphaned VMs")

    # Get existing VMs from NetBox
    existing_vms = netbox.fetch_vms()
    logger.info(f"Found {len(existing_vms)} existing VMs in NetBox")

    existing_vm_names = {}
    for vm in existing_vms:
        if hasattr(vm, 'name'):
            existing_vm_names[vm.name] = vm

    # Create or update VMs
    created_count = 0
    skipped_count = 0
    updated_count = 0
    failed_count = 0

    for yc_vm in yc_vms:
        vm_name = yc_vm.get("name", "")
        vm_id = yc_vm.get("id", "")

        if not vm_name or not isinstance(vm_name, str):
            logger.warning(f"Skipping VM without valid name: {vm_id}")
            skipped_count += 1
            continue

        try:
            if vm_name in existing_vm_names:
                existing_vm = existing_vm_names[vm_name]

                params_updated = update_vm_parameters(
                    existing_vm, yc_vm, netbox, id_mapping,
                    tenant_name=tenant_name, provider_profile=profile,
                )
                disk_sync_result = sync_vm_disks(existing_vm, yc_vm, netbox)
                disks_changed = disk_sync_result["created"] > 0 or disk_sync_result["deleted"] > 0
                interface_sync_result = sync_vm_interfaces(existing_vm, yc_vm, netbox)
                interfaces_changed = (
                    interface_sync_result["interfaces_created"] > 0
                    or interface_sync_result["ips_created"] > 0
                )
                ip_updated = update_vm_primary_ip(existing_vm, yc_vm, netbox)

                if params_updated or disks_changed or interfaces_changed or ip_updated:
                    updated_count += 1
                    if disks_changed:
                        logger.info(
                            f"VM {vm_name}: disk changes - "
                            f"created: {disk_sync_result['created']}, "
                            f"deleted: {disk_sync_result['deleted']}"
                        )
                    if interfaces_changed:
                        logger.info(
                            f"VM {vm_name}: interface changes - "
                            f"interfaces created: {interface_sync_result['interfaces_created']}, "
                            f"IPs created: {interface_sync_result['ips_created']}"
                        )
                else:
                    logger.debug(f"VM already exists and up to date: {vm_name}")
                    skipped_count += 1
                continue

            vm_data = prepare_vm_data(
                yc_vm, netbox, id_mapping, provider_profile=profile, tenant_name=tenant_name,
            )

            if netbox.dry_run:
                logger.info(f"[DRY-RUN] Would create VM: {vm_name}")
                created_count += 1
                continue

            created_vm = netbox.create_vm(vm_data, tag_slug=profile.tag_slug)
            if not created_vm:
                logger.error(f"Failed to create VM: {vm_name}")
                failed_count += 1
                continue

            logger.info(f"Created VM: {vm_name}")
            created_count += 1

            # Add disks
            disks = yc_vm.get("disks", [])
            if isinstance(disks, list):
                for disk in disks:
                    if not isinstance(disk, dict):
                        continue

                    size = disk.get("size", 0)
                    if isinstance(size, (int, float)):
                        disk_data = {
                            "virtual_machine": created_vm.id,
                            "size": parse_disk_size_mb(size),
                            "name": str(disk.get("name", "disk"))
                        }
                        netbox.create_disk(disk_data)

            # Add network interfaces and IPs
            network_interfaces = yc_vm.get("network_interfaces", [])
            private_ip_id = None
            public_ip_id = None

            if isinstance(network_interfaces, list):
                for idx, iface in enumerate(network_interfaces):
                    if not isinstance(iface, dict):
                        continue

                    interface_data = {
                        "virtual_machine": created_vm.id,
                        "name": f"eth{idx}"
                    }
                    created_iface = netbox.create_interface(interface_data)

                    if not created_iface:
                        continue

                    primary_v4 = iface.get("primary_v4_address")
                    if primary_v4 and isinstance(primary_v4, str):
                        ip_data = {
                            "address": primary_v4,
                            "interface": created_iface.id
                        }
                        created_ip = netbox.create_ip(ip_data)
                        if created_ip:
                            if is_private_ip(primary_v4) and private_ip_id is None:
                                private_ip_id = created_ip.id
                            elif public_ip_id is None:
                                public_ip_id = created_ip.id

                    public_v4 = iface.get("primary_v4_address_one_to_one_nat")
                    if public_v4 and isinstance(public_v4, str):
                        ip_data = {
                            "address": public_v4,
                            "interface": created_iface.id
                        }
                        created_pub_ip = netbox.create_ip(ip_data)
                        if created_pub_ip and public_ip_id is None:
                            public_ip_id = created_pub_ip.id

            primary_ip_id = private_ip_id or public_ip_id
            if primary_ip_id:
                netbox.set_vm_primary_ip(created_vm.id, primary_ip_id, ip_version=4)
                logger.debug(f"Set primary IPv4 (ID: {primary_ip_id}) for VM: {vm_name}")

        except Exception as e:
            logger.error(f"Failed to sync VM {vm_name}: {e}")
            failed_count += 1
            continue

    logger.info(
        f"VM sync completed: {created_count} created, "
        f"{updated_count} updated, {skipped_count} skipped, {failed_count} failed"
    )

    return {
        "created": created_count,
        "updated": updated_count,
        "skipped": skipped_count,
        "deleted": deleted_count,
        "errors": failed_count,
    }
