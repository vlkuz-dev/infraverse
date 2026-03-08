"""Tests for infraverse.sync.provider_profile module."""

import pytest

from infraverse.sync.provider_profile import (
    YC_PROFILE,
    VCLOUD_PROFILE,
    get_profile,
)


class TestProviderProfileConstants:
    def test_yc_profile_values(self):
        assert YC_PROFILE.key == "yandex_cloud"
        assert YC_PROFILE.tag_slug == "synced-from-yc"
        assert YC_PROFILE.cluster_type_slug == "yandex-cloud"
        assert YC_PROFILE.vm_comment_prefix == "YC VM ID"

    def test_vcloud_profile_values(self):
        assert VCLOUD_PROFILE.key == "vcloud"
        assert VCLOUD_PROFILE.tag_slug == "synced-from-vcloud"
        assert VCLOUD_PROFILE.cluster_type_slug == "vcloud"
        assert VCLOUD_PROFILE.vm_comment_prefix == "vCloud VM"

    def test_profiles_have_different_tags(self):
        assert YC_PROFILE.tag_slug != VCLOUD_PROFILE.tag_slug
        assert YC_PROFILE.tag_color != VCLOUD_PROFILE.tag_color

    def test_profiles_have_different_cluster_types(self):
        assert YC_PROFILE.cluster_type_slug != VCLOUD_PROFILE.cluster_type_slug


class TestProviderProfileFrozen:
    def test_frozen_immutability(self):
        with pytest.raises(AttributeError):
            YC_PROFILE.key = "something_else"

    def test_frozen_immutability_vcloud(self):
        with pytest.raises(AttributeError):
            VCLOUD_PROFILE.tag_slug = "modified"


class TestGetProfile:
    def test_get_yandex_cloud(self):
        assert get_profile("yandex_cloud") is YC_PROFILE

    def test_get_vcloud(self):
        assert get_profile("vcloud") is VCLOUD_PROFILE

    def test_unknown_raises_key_error(self):
        with pytest.raises(KeyError):
            get_profile("unknown_provider")
