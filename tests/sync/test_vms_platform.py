"""Tests for infraverse.sync.vms_platform module."""

from infraverse.sync.vms_platform import (
    detect_platform_slug,
    detect_platform_id,
    DEFAULT_PLATFORM_SLUG,
)
from tests.conftest import make_mock_netbox_client


class TestDetectPlatformSlug:
    """Tests for detect_platform_slug."""

    def test_empty_os_returns_default(self):
        assert detect_platform_slug("") == DEFAULT_PLATFORM_SLUG

    def test_none_like_os_returns_default(self):
        assert detect_platform_slug("FreeBSD") == DEFAULT_PLATFORM_SLUG

    def test_windows_variants(self):
        assert detect_platform_slug("windows-2019-dc") == "windows-2019"
        assert detect_platform_slug("Windows Server 2022") == "windows-2022"
        assert detect_platform_slug("Windows Server 2025") == "windows-2025"
        assert detect_platform_slug("Windows") == "windows"

    def test_ubuntu_variants(self):
        assert detect_platform_slug("ubuntu-22.04-lts") == "ubuntu-22-04"
        assert detect_platform_slug("Ubuntu 22-04") == "ubuntu-22-04"
        assert detect_platform_slug("ubuntu jammy") == "ubuntu-22-04"
        assert detect_platform_slug("Ubuntu 24.04 Noble") == "ubuntu-24-04"
        assert detect_platform_slug("ubuntu-24-04") == "ubuntu-24-04"
        assert detect_platform_slug("ubuntu noble") == "ubuntu-24-04"
        assert detect_platform_slug("ubuntu-20.04") == "ubuntu-22-04"  # fallback

    def test_debian_variants(self):
        assert detect_platform_slug("debian-11") == "debian-11"
        assert detect_platform_slug("debian-bullseye") == "debian-11"
        assert detect_platform_slug("debian-12") == "debian-12"
        assert detect_platform_slug("debian-12-v20241115") == "debian-12"
        assert detect_platform_slug("debian-bookworm") == "debian-12"
        assert detect_platform_slug("debian") == "debian-12"  # fallback

    def test_centos_variants(self):
        assert detect_platform_slug("centos-7") == "centos-7"
        assert detect_platform_slug("centos-7.9") == "centos-7"
        assert detect_platform_slug("centos-8") == DEFAULT_PLATFORM_SLUG

    def test_almalinux_variants(self):
        assert detect_platform_slug("almalinux-9") == "almalinux-9"
        assert detect_platform_slug("almalinux-8") == DEFAULT_PLATFORM_SLUG

    def test_oracle_linux(self):
        assert detect_platform_slug("oracle-linux-9") == "oracle-linux-9"
        assert detect_platform_slug("oracle-linux-8") == DEFAULT_PLATFORM_SLUG

    def test_other_distros_return_default(self):
        assert detect_platform_slug("rocky linux 9") == DEFAULT_PLATFORM_SLUG
        assert detect_platform_slug("some-linux-distro") == DEFAULT_PLATFORM_SLUG
        assert detect_platform_slug("rhel 9") == DEFAULT_PLATFORM_SLUG
        assert detect_platform_slug("fedora 40") == DEFAULT_PLATFORM_SLUG


class TestDetectPlatformId:
    """Tests for detect_platform_id."""

    def test_with_netbox_client(self):
        netbox = make_mock_netbox_client()
        netbox.ensure_platform.return_value = 42

        result = detect_platform_id("ubuntu-22.04", netbox)

        assert result == 42
        netbox.ensure_platform.assert_called_once_with("ubuntu-22-04")

    def test_without_netbox_client(self):
        result = detect_platform_id("ubuntu-22.04")

        assert result == 0

    def test_none_netbox_client(self):
        result = detect_platform_id("windows-2022", None)

        assert result == 0
