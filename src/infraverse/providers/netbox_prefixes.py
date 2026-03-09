"""NetBox prefix management methods (mixin for NetBoxClient).

Handles IP prefix creation, updates, and scope/site assignment.
"""

import logging
from typing import Any, Dict, Optional

from pynetbox.core.response import Record

logger = logging.getLogger(__name__)


class NetBoxPrefixesMixin:
    """Mixin providing prefix management for NetBoxClient.

    Expects the host class to have: self.nb, self.dry_run,
    and tag methods from NetBoxTagsMixin (ensure_sync_tag, _add_tag_to_object).
    """

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
