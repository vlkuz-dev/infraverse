"""Provider-specific profile for multi-provider NetBox sync."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderProfile:
    """Carries provider-specific strings through the sync pipeline."""

    key: str
    display_name: str
    tag_name: str
    tag_slug: str
    tag_color: str
    tag_description: str
    cluster_type_name: str
    cluster_type_slug: str
    cluster_type_description: str
    site_description_prefix: str
    vm_comment_prefix: str


YC_PROFILE = ProviderProfile(
    key="yandex_cloud",
    display_name="Yandex Cloud",
    tag_name="synced-from-yc",
    tag_slug="synced-from-yc",
    tag_color="2196f3",
    tag_description="Object synced from Yandex Cloud",
    cluster_type_name="yandex-cloud",
    cluster_type_slug="yandex-cloud",
    cluster_type_description="Yandex Cloud Platform",
    site_description_prefix="Yandex Cloud Availability Zone",
    vm_comment_prefix="YC VM ID",
)

VCLOUD_PROFILE = ProviderProfile(
    key="vcloud",
    display_name="vCloud Director",
    tag_name="synced-from-vcloud",
    tag_slug="synced-from-vcloud",
    tag_color="4caf50",
    tag_description="Object synced from vCloud Director",
    cluster_type_name="vcloud",
    cluster_type_slug="vcloud",
    cluster_type_description="VMware vCloud Director",
    site_description_prefix="vCloud Site",
    vm_comment_prefix="vCloud VM",
)

_PROFILES = {
    "yandex_cloud": YC_PROFILE,
    "vcloud": VCLOUD_PROFILE,
}


def get_profile(key: str) -> ProviderProfile:
    """Get a provider profile by key.

    Raises:
        KeyError: If the key is not recognized.
    """
    return _PROFILES[key]
