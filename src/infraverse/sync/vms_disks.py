"""Disk synchronization — sync virtual disks between cloud provider and NetBox."""

import logging
from typing import Any, Dict

from infraverse.providers.netbox import NetBoxClient
from infraverse.sync.size_converters import parse_disk_size_mb

logger = logging.getLogger(__name__)


def sync_vm_disks(
    vm: Any,
    yc_vm: Dict[str, Any],
    netbox: NetBoxClient,
    remove_orphaned: bool = True
) -> Dict[str, int]:
    """
    Sync virtual disks for an existing VM.

    Args:
        vm: Existing NetBox VM object
        yc_vm: Yandex Cloud VM data
        netbox: NetBox client
        remove_orphaned: Whether to remove disks that don't exist in YC

    Returns:
        Dictionary with counts of created, deleted, and unchanged disks
    """
    try:
        disks_created = 0
        disks_deleted = 0
        disks_unchanged = 0

        # Get existing disks for this VM
        existing_disks = []
        if hasattr(netbox.nb.virtualization, 'virtual_disks'):
            try:
                existing_disks = list(netbox.nb.virtualization.virtual_disks.filter(virtual_machine_id=vm.id))
                logger.debug(f"VM {vm.name}: found {len(existing_disks)} existing disks in NetBox")
            except Exception as e:
                logger.debug(f"Could not fetch existing disks for VM {vm.name}: {e}")
        else:
            logger.debug("Virtual disks not supported in this NetBox version")
            return {"created": 0, "deleted": 0, "unchanged": 0}

        # Create a map of existing disks by name for comparison
        existing_disks_by_name = {disk.name: disk for disk in existing_disks}

        # Get disks from Yandex Cloud
        yc_disks = yc_vm.get("disks", [])
        if not isinstance(yc_disks, list):
            yc_disks = []

        # Track which disks we've seen in YC
        yc_disk_names = set()

        # Process each disk from Yandex Cloud
        for idx, disk in enumerate(yc_disks):
            if not isinstance(disk, dict):
                continue

            disk_name = str(disk.get("name", f"disk-{idx}"))
            yc_disk_names.add(disk_name)

            # Check if disk already exists
            if disk_name in existing_disks_by_name:
                existing_disk = existing_disks_by_name[disk_name]

                # Check if size needs updating
                size = disk.get("size", 0)
                if isinstance(size, (int, float)) and size > 0:
                    size_mb = parse_disk_size_mb(size)
                    if existing_disk.size != size_mb:
                        if netbox.dry_run:
                            logger.info(
                                f"[DRY-RUN] VM {vm.name}: would update disk {disk_name} "
                                f"size from {existing_disk.size} MB to {size_mb} MB"
                            )
                        else:
                            logger.info(
                                f"VM {vm.name}: updating disk {disk_name} "
                                f"size from {existing_disk.size} MB to {size_mb} MB"
                            )
                            try:
                                existing_disk.size = size_mb
                                existing_disk.save()
                            except Exception as e:
                                logger.error(f"VM {vm.name}: failed to update disk {disk_name} size: {e}")
                    else:
                        disks_unchanged += 1
                        logger.debug(f"VM {vm.name}: disk {disk_name} is up to date")
                else:
                    disks_unchanged += 1
                continue

            # Get disk size
            size = disk.get("size", 0)
            if not isinstance(size, (int, float)) or size == 0:
                logger.warning(f"VM {vm.name}: invalid disk size for {disk_name}: {size}")
                continue

            disk_data = {
                "virtual_machine": vm.id,
                "size": parse_disk_size_mb(size),
                "name": disk_name
            }

            disk_type = disk.get("type", "")
            if disk_type:
                disk_data["description"] = f"Type: {disk_type}"

            if netbox.create_disk(disk_data):
                disks_created += 1
                logger.info(f"VM {vm.name}: created disk {disk_name} ({disk_data['size']} MB)")
            else:
                logger.error(f"VM {vm.name}: failed to create disk {disk_name}")

        # Remove orphaned disks (exist in NetBox but not in YC)
        if remove_orphaned:
            for disk_name, disk in existing_disks_by_name.items():
                if disk_name not in yc_disk_names:
                    if netbox.dry_run:
                        logger.info(f"[DRY-RUN] VM {vm.name}: would remove orphaned disk {disk_name}")
                        disks_deleted += 1
                    else:
                        try:
                            logger.info(f"VM {vm.name}: removing orphaned disk {disk_name}")
                            disk.delete()
                            disks_deleted += 1
                        except Exception as e:
                            logger.error(f"VM {vm.name}: failed to delete orphaned disk {disk_name}: {e}")

        if disks_created > 0 or disks_deleted > 0:
            logger.info(
                f"VM {vm.name}: disk sync complete - created: {disks_created}, "
                f"deleted: {disks_deleted}, unchanged: {disks_unchanged}"
            )

        return {
            "created": disks_created,
            "deleted": disks_deleted,
            "unchanged": disks_unchanged
        }

    except Exception as e:
        logger.error(f"Failed to sync disks for VM {vm.name}: {e}")
        return {"created": 0, "deleted": 0, "unchanged": 0}
