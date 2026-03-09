"""NetBox tag management methods (mixin for NetBoxClient)."""

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class NetBoxTagsMixin:
    """Mixin providing tag management for NetBoxClient.

    Expects the host class to have: self.nb, self.dry_run,
    self._sync_tag_cache, self._sync_tag_id.
    """

    def ensure_sync_tag(
        self,
        tag_name: Optional[str] = None,
        tag_slug: Optional[str] = None,
        tag_color: Optional[str] = None,
        tag_description: Optional[str] = None,
    ) -> int:
        """
        Ensure a sync tag exists in NetBox.

        All params are optional; defaults to "synced-from-yc" for backward compatibility.

        Returns:
            Tag ID
        """
        tag_name = tag_name or "synced-from-yc"
        tag_slug = tag_slug or "synced-from-yc"
        tag_color = tag_color or "2196f3"
        tag_description = tag_description or "Object synced from Yandex Cloud"

        # Check per-slug cache
        if tag_slug in self._sync_tag_cache:
            return self._sync_tag_cache[tag_slug]

        # Backward compat: check old scalar cache
        if self._sync_tag_id is not None and tag_slug == "synced-from-yc":
            return self._sync_tag_id

        # Check if tag exists
        tag = None
        try:
            tag = self.nb.extras.tags.get(name=tag_name)
        except Exception:
            try:
                tag = self.nb.extras.tags.get(slug=tag_slug)
            except Exception:
                pass

        if tag:
            self._sync_tag_cache[tag_slug] = tag.id
            if tag_slug == "synced-from-yc":
                self._sync_tag_id = tag.id
            logger.debug(f"Found existing tag: {tag_name} (ID: {tag.id})")
            return tag.id

        # Create tag if it doesn't exist
        if self.dry_run:
            logger.info(f"[DRY-RUN] Would create tag: {tag_name}")
            mock_id = 1_000_000 + len(self._sync_tag_cache)
            self._sync_tag_cache[tag_slug] = mock_id
            if tag_slug == "synced-from-yc":
                self._sync_tag_id = mock_id
            return mock_id

        try:
            tag = self.nb.extras.tags.create({
                "name": tag_name,
                "slug": tag_slug,
                "color": tag_color,
                "description": tag_description
            })
            self._sync_tag_cache[tag_slug] = tag.id
            if tag_slug == "synced-from-yc":
                self._sync_tag_id = tag.id
            logger.info(f"Created tag: {tag_name} (ID: {tag.id})")
            return tag.id
        except Exception as e:
            if '400' in str(e) and 'slug' in str(e).lower():
                try:
                    tag = self.nb.extras.tags.get(slug=tag_slug)
                    if tag:
                        self._sync_tag_cache[tag_slug] = tag.id
                        if tag_slug == "synced-from-yc":
                            self._sync_tag_id = tag.id
                        return tag.id
                except Exception:
                    pass
            logger.error(f"Failed to create tag: {e}")
            return 0

    def _add_tag_to_object(self, obj: Any, tag_id: int) -> bool:
        """
        Add sync tag to a NetBox object.

        Args:
            obj: NetBox object to tag
            tag_id: Tag ID to add

        Returns:
            True if tag was added, False otherwise
        """
        if not tag_id or self.dry_run:
            return False

        try:
            # Get current tags
            current_tags = []
            if hasattr(obj, 'tags'):
                current_tags = list(obj.tags) if obj.tags else []

            # Normalize to integer IDs to avoid mixed Record/int types
            tag_ids = [t.id if hasattr(t, 'id') else t for t in current_tags]
            if tag_id in tag_ids:
                return True

            # Add tag using normalized ID list
            tag_ids.append(tag_id)
            obj.tags = tag_ids
            obj.save()
            logger.debug(f"Added sync tag to object: {getattr(obj, 'name', str(obj))}")
            return True

        except Exception as e:
            logger.debug(f"Could not add tag to object: {e}")
            return False
