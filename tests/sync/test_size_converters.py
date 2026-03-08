"""Tests for size conversion utilities."""

import pytest

from infraverse.sync.size_converters import (
    BYTES_PER_GIB,
    NETBOX_MB_PER_GIB,
    parse_disk_size_mb,
)


class TestConstants:
    def test_bytes_per_gib(self):
        assert BYTES_PER_GIB == 1073741824

    def test_netbox_mb_per_gib(self):
        assert NETBOX_MB_PER_GIB == 1000


class TestParseDiskSizeMb:
    def test_10_gib(self):
        assert parse_disk_size_mb(10 * BYTES_PER_GIB) == 10000

    def test_1_gib(self):
        assert parse_disk_size_mb(BYTES_PER_GIB) == 1000

    def test_zero(self):
        assert parse_disk_size_mb(0) == 0

    def test_string_input(self):
        assert parse_disk_size_mb(str(10 * BYTES_PER_GIB)) == 10000

    def test_float_input(self):
        assert parse_disk_size_mb(float(10 * BYTES_PER_GIB)) == 10000

    def test_small_disk_50_gib(self):
        assert parse_disk_size_mb(50 * BYTES_PER_GIB) == 50000

    def test_large_disk_1_tib(self):
        assert parse_disk_size_mb(1024 * BYTES_PER_GIB) == 1024000

    def test_non_exact_gib(self):
        # 1.5 GiB = 1536 MB in NetBox terms
        size_bytes = int(1.5 * BYTES_PER_GIB)
        assert parse_disk_size_mb(size_bytes) == 1500

    def test_negative_value(self):
        assert parse_disk_size_mb(-BYTES_PER_GIB) == -1000

    def test_string_with_whitespace_raises(self):
        with pytest.raises(ValueError):
            parse_disk_size_mb("  not a number  ")

    def test_invalid_string_raises(self):
        with pytest.raises(ValueError):
            parse_disk_size_mb("abc")
