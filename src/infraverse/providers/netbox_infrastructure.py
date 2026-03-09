"""NetBox infrastructure management methods (mixin for NetBoxClient).

Handles sites, cluster types, clusters, and platforms.
"""

import logging
import re
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class NetBoxInfrastructureMixin:
    """Mixin providing infrastructure management for NetBoxClient.

    Expects the host class to have: self.nb, self.dry_run,
    self._cluster_type_cache, self._cluster_type_id,
    and tag methods from NetBoxTagsMixin (ensure_sync_tag, _add_tag_to_object).
    """

    def _safe_update_object(self, obj: Any, updates: Dict[str, Any]) -> bool:
        """
        Safely update a NetBox object with the given updates.

        Args:
            obj: NetBox object to update
            updates: Dictionary of fields to update

        Returns:
            True if object was updated, False otherwise
        """
        if not updates or self.dry_run:
            return False

        needs_update = False

        try:
            # Check and apply updates
            for field, new_value in updates.items():
                current_value = getattr(obj, field, None)

                # Handle object comparisons (e.g., site.id vs site object)
                if hasattr(current_value, 'id'):
                    current_value = current_value.id
                elif hasattr(current_value, 'value'):
                    # Handle pynetbox ChoiceItem objects (e.g., status)
                    current_value = current_value.value

                if current_value != new_value:
                    setattr(obj, field, new_value)
                    needs_update = True
                    logger.debug(f"Setting {field} from {current_value} to {new_value}")

            # Save if there were changes
            if needs_update:
                obj.save()
                obj_name = getattr(obj, 'name', str(obj))
                logger.info(f"Updated object: {obj_name}")
                return True

        except Exception as e:
            obj_name = getattr(obj, 'name', str(obj))
            logger.warning(f"Could not update object {obj_name}: {e}")

        return False

    def ensure_site(
        self,
        zone_id: str,
        zone_name: Optional[str] = None,
        description_prefix: Optional[str] = None,
    ) -> int:
        """
        Ensure availability zone exists as a site in NetBox.

        Args:
            zone_id: Zone ID (e.g., "ru-central1-a")
            zone_name: Optional zone display name
            description_prefix: Prefix for the site description (default: "Yandex Cloud Availability Zone")

        Returns:
            Site ID
        """
        name = zone_name or zone_id
        slug = zone_id.lower().replace("_", "-")
        prefix = description_prefix or "Yandex Cloud Availability Zone"
        description = f"{prefix}: {zone_id}"

        # Check if site exists by name or slug
        site = None

        # Try by name first
        try:
            site = self.nb.dcim.sites.get(name=name)
        except Exception:
            pass

        # If not found by name, try by slug
        if not site:
            try:
                site = self.nb.dcim.sites.get(slug=slug)
            except Exception:
                pass

        if site:
            # Check and apply updates if needed
            updates = {}

            if getattr(site, 'name', None) != name:
                updates['name'] = name
            if getattr(site, 'slug', None) != slug:
                updates['slug'] = slug
            if getattr(site, 'description', None) != description:
                updates['description'] = description
            current_status = getattr(site, 'status', None)
            status_value = getattr(current_status, 'value', current_status)
            if status_value != 'active':
                updates['status'] = 'active'

            self._safe_update_object(site, updates)

            # Add sync tag
            tag_id = self.ensure_sync_tag()
            if tag_id:
                self._add_tag_to_object(site, tag_id)

            return site.id

        # Create site if it doesn't exist
        if self.dry_run:
            logger.info(f"[DRY-RUN] Would create site for zone: {name}")
            return 1  # Mock ID for dry run

        # Ensure tag exists
        tag_id = self.ensure_sync_tag()

        site_data = {
            "name": name,
            "slug": slug,
            "status": "active",
            "description": description
        }

        # Add tag if available
        if tag_id:
            site_data["tags"] = [tag_id]

        try:
            site = self.nb.dcim.sites.create(site_data)
            logger.info(f"Created site for zone: {name} (ID: {site.id})")
            return site.id
        except Exception as e:
            error_msg = str(e)
            # Check if it's a duplicate slug error
            if '400' in error_msg and 'slug' in error_msg.lower():
                logger.warning(f"Site with slug '{slug}' already exists, trying to fetch it")
                # Try to get existing site
                try:
                    site = self.nb.dcim.sites.get(slug=slug)
                    if site:
                        logger.info(f"Found existing site: {site.name} (ID: {site.id})")
                        return site.id
                except Exception:
                    pass

                # Try by name again
                try:
                    site = self.nb.dcim.sites.get(name=name)
                    if site:
                        logger.info(f"Found existing site by name: {name} (ID: {site.id})")
                        return site.id
                except Exception:
                    pass

            logger.error(f"Failed to create or find site for zone {name}: {e}")
            raise

    def ensure_cluster_type(
        self,
        name: Optional[str] = None,
        slug: Optional[str] = None,
        description: Optional[str] = None,
    ) -> int:
        """
        Ensure a cluster type exists.

        All params optional; defaults to "yandex-cloud" for backward compatibility.

        Returns:
            Cluster type ID
        """
        desired_name = name or "yandex-cloud"
        desired_slug = slug or "yandex-cloud"
        desired_description = description or "Yandex Cloud Platform"

        # Check per-slug cache
        if desired_slug in self._cluster_type_cache:
            return self._cluster_type_cache[desired_slug]

        # Backward compat: check old scalar cache
        if self._cluster_type_id is not None and desired_slug == "yandex-cloud":
            return self._cluster_type_id

        # Check if cluster type exists by name or slug
        cluster_type = None

        # First try by name
        try:
            cluster_type = self.nb.virtualization.cluster_types.get(name=desired_name)
        except Exception:
            pass

        # If not found by name, try by slug
        if not cluster_type:
            try:
                cluster_type = self.nb.virtualization.cluster_types.get(slug=desired_slug)
            except Exception:
                pass

        if cluster_type:
            # Check and apply updates if needed
            updates = {}

            if getattr(cluster_type, 'name', None) != desired_name:
                updates['name'] = desired_name
            if getattr(cluster_type, 'slug', None) != desired_slug:
                updates['slug'] = desired_slug
            if getattr(cluster_type, 'description', None) != desired_description:
                updates['description'] = desired_description

            self._safe_update_object(cluster_type, updates)

            # Add sync tag
            tag_id = self.ensure_sync_tag()
            if tag_id:
                self._add_tag_to_object(cluster_type, tag_id)

            self._cluster_type_cache[desired_slug] = cluster_type.id
            if desired_slug == "yandex-cloud":
                self._cluster_type_id = cluster_type.id
            return cluster_type.id

        # Create cluster type if it doesn't exist
        if self.dry_run:
            logger.info(f"[DRY-RUN] Would create cluster type: {desired_name}")
            mock_id = 1_000_000 + len(self._cluster_type_cache)
            self._cluster_type_cache[desired_slug] = mock_id
            if desired_slug == "yandex-cloud":
                self._cluster_type_id = mock_id
            return mock_id

        # Ensure tag exists
        tag_id = self.ensure_sync_tag()

        cluster_type_data = {
            "name": desired_name,
            "slug": desired_slug,
            "description": desired_description
        }

        # Add tag if available
        if tag_id:
            cluster_type_data["tags"] = [tag_id]

        try:
            cluster_type = self.nb.virtualization.cluster_types.create(cluster_type_data)
            self._cluster_type_cache[desired_slug] = cluster_type.id
            if desired_slug == "yandex-cloud":
                self._cluster_type_id = cluster_type.id
            logger.info(f"Created cluster type: {desired_name} (ID: {cluster_type.id})")
            return cluster_type.id
        except Exception as e:
            error_msg = str(e)
            # Check if it's a duplicate slug error
            if '400' in error_msg and 'slug' in error_msg.lower():
                logger.warning(f"Cluster type with slug '{desired_slug}' already exists, trying to fetch it")
                # Try one more time to get by slug
                try:
                    cluster_type = self.nb.virtualization.cluster_types.get(slug=desired_slug)
                    if cluster_type:
                        self._cluster_type_cache[desired_slug] = cluster_type.id
                        if desired_slug == "yandex-cloud":
                            self._cluster_type_id = cluster_type.id
                        logger.info(f"Found existing cluster type: {cluster_type.name} (ID: {cluster_type.id})")
                        return cluster_type.id
                except Exception:
                    pass

                # If still not found, try listing all and finding by slug
                try:
                    all_types = list(self.nb.virtualization.cluster_types.all())
                    for ct in all_types:
                        if getattr(ct, 'slug', None) == desired_slug:
                            self._cluster_type_cache[desired_slug] = ct.id
                            if desired_slug == "yandex-cloud":
                                self._cluster_type_id = ct.id
                            logger.info(f"Found existing cluster type by iteration: {ct.name} (ID: {ct.id})")
                            return ct.id
                except Exception:
                    pass

            logger.error(f"Failed to create or find cluster type: {e}")
            raise

    def ensure_cluster(
        self,
        folder_name: str,
        folder_id: str,
        cloud_name: str,
        site_id: Optional[int] = None,
        description: str = "",
        cluster_type_slug: Optional[str] = None,
        tag_slug: Optional[str] = None,
    ) -> int:
        """
        Ensure cluster exists for a cloud folder.

        Args:
            folder_name: Folder display name
            folder_id: Folder ID
            cloud_name: Parent cloud name
            site_id: Optional site ID to assign cluster to
            description: Optional description
            cluster_type_slug: Optional cluster type slug (default: "yandex-cloud")
            tag_slug: Optional tag slug (default: "synced-from-yc")

        Returns:
            Cluster ID
        """
        # Include cloud_name to avoid collisions across clouds
        if cloud_name:
            cluster_name = f"{cloud_name}/{folder_name}"
        else:
            cluster_name = f"{folder_name}"

        # Generate a slug from the cluster name
        cluster_slug = cluster_name.lower().replace("/", "-").replace(" ", "-").replace("_", "-")
        # Ensure slug is valid (alphanumeric and hyphens only)
        cluster_slug = re.sub(r'[^a-z0-9-]', '-', cluster_slug)
        cluster_slug = re.sub(r'-+', '-', cluster_slug)  # Replace multiple hyphens with single
        cluster_slug = cluster_slug.strip('-')  # Remove leading/trailing hyphens

        # Check if cluster exists by name or slug
        cluster = None

        # Try by new name format (cloud/folder) first
        try:
            cluster = self.nb.virtualization.clusters.get(name=cluster_name)
        except Exception as e:
            logger.debug(f"Cluster lookup by name '{cluster_name}' failed: {e}")

        # If not found by name, try by slug
        if not cluster:
            try:
                cluster = self.nb.virtualization.clusters.get(slug=cluster_slug)
            except Exception as e:
                logger.debug(f"Cluster lookup by slug '{cluster_slug}' failed: {e}")

        # Fallback: try old name format (folder_name only, without cloud prefix)
        if not cluster and cloud_name and folder_name != cluster_name:
            try:
                # Use filter() instead of get() — get() raises ValueError
                # when multiple clusters match the same folder name
                results = list(self.nb.virtualization.clusters.filter(name=folder_name))
                if results:
                    cluster = results[0]
                    logger.info(
                        f"Migrating cluster '{folder_name}' → '{cluster_name}'"
                    )
                    if not self.dry_run:
                        cluster.name = cluster_name
                        cluster.slug = cluster_slug
                        cluster.save()
            except Exception as e:
                logger.debug(f"Cluster fallback lookup by old name '{folder_name}' failed: {e}")

        if cluster:
            # Check and apply updates if needed
            updates = {}

            # Check cluster type
            ct_kwargs = {"slug": cluster_type_slug} if cluster_type_slug else {}
            cluster_type_id = self.ensure_cluster_type(**ct_kwargs)
            if hasattr(cluster, 'type') and cluster.type:
                current_type_id = cluster.type.id if hasattr(cluster.type, 'id') else cluster.type
                if current_type_id != cluster_type_id:
                    updates['type'] = cluster_type_id

            # Check site if provided
            if site_id is not None:
                current_site_id = None
                if hasattr(cluster, 'site') and cluster.site:
                    current_site_id = cluster.site.id if hasattr(cluster.site, 'id') else cluster.site
                if current_site_id != site_id:
                    updates['site'] = site_id

            # Check comments
            new_comments = f"Folder ID: {folder_id}\n{description}".strip()
            if getattr(cluster, 'comments', '') != new_comments:
                updates['comments'] = new_comments

            self._safe_update_object(cluster, updates)

            # Add sync tag
            tag_kwargs = {"tag_slug": tag_slug} if tag_slug else {}
            tag_id = self.ensure_sync_tag(**tag_kwargs)
            if tag_id:
                self._add_tag_to_object(cluster, tag_id)

            return cluster.id

        # Create cluster if it doesn't exist
        if self.dry_run:
            logger.info(f"[DRY-RUN] Would create cluster: {cluster_name}")
            return 1  # Mock ID for dry run

        # Ensure cluster type and tag exist
        ct_kwargs = {"slug": cluster_type_slug} if cluster_type_slug else {}
        cluster_type_id = self.ensure_cluster_type(**ct_kwargs)
        tag_kwargs = {"tag_slug": tag_slug} if tag_slug else {}
        tag_id = self.ensure_sync_tag(**tag_kwargs)

        cluster_data = {
            "name": cluster_name,
            "type": cluster_type_id,
            "status": "active",
            "comments": f"Folder ID: {folder_id}\n{description}".strip()
        }

        # Optionally assign to site
        if site_id:
            cluster_data["site"] = site_id

        # Add tag if available
        if tag_id:
            cluster_data["tags"] = [tag_id]

        try:
            cluster = self.nb.virtualization.clusters.create(cluster_data)
            logger.info(f"Created cluster: {cluster_name} (ID: {cluster.id})")
            return cluster.id
        except Exception as e:
            error_msg = str(e)
            # Check if it's a duplicate name error
            if '400' in error_msg:
                logger.warning(f"Cluster '{cluster_name}' might already exist, trying to fetch it")
                # Try to get existing cluster
                try:
                    cluster = self.nb.virtualization.clusters.get(name=cluster_name)
                    if cluster:
                        logger.info(f"Found existing cluster: {cluster_name} (ID: {cluster.id})")
                        return cluster.id
                except Exception:
                    pass

                # Try listing all clusters with this name
                try:
                    all_clusters = list(self.nb.virtualization.clusters.filter(name=cluster_name))
                    if all_clusters:
                        cluster = all_clusters[0]
                        logger.info(f"Found existing cluster by filter: {cluster_name} (ID: {cluster.id})")
                        return cluster.id
                except Exception:
                    pass

            logger.error(f"Failed to create or find cluster {cluster_name}: {e}")
            raise

    def ensure_platform(self, slug: str, name: str = "") -> int:
        """
        Ensure a platform exists by slug, creating it if necessary.

        Args:
            slug: Platform slug (e.g., 'windows-2022', 'ubuntu-24-04')
            name: Display name; defaults to slug if not provided

        Returns:
            Platform ID
        """
        if not name:
            name = slug

        try:
            platform = self.nb.dcim.platforms.get(slug=slug)
            if platform:
                return platform.id
        except Exception:
            pass

        if self.dry_run:
            logger.info(f"[DRY-RUN] Would create platform: {name} (slug: {slug})")
            return 1

        try:
            platform = self.nb.dcim.platforms.create({
                "name": name,
                "slug": slug,
            })
            logger.info(f"Created platform: {name} (ID: {platform.id})")
            return platform.id
        except Exception as e:
            error_msg = str(e)
            if '400' in error_msg:
                try:
                    platform = self.nb.dcim.platforms.get(slug=slug)
                    if platform:
                        return platform.id
                except Exception:
                    pass
            logger.error(f"Failed to create or find platform {slug}: {e}")
            raise
