"""Tests for size conversion utilities."""

import pytest

from infraverse.sync.size_converters import (
    BYTES_PER_GIB,
    NETBOX_MB_PER_GIB,
    parse_cores,
    parse_disk_size_mb,
    parse_memory_mb,
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


class TestParseMemoryMb:
    def test_bytes_4_gib(self):
        # 4 GiB in bytes -> 4000 NetBox MB
        assert parse_memory_mb({"memory": 4 * BYTES_PER_GIB}) == 4000

    def test_bytes_8_gib(self):
        assert parse_memory_mb({"memory": 8 * BYTES_PER_GIB}) == 8000

    def test_bytes_float(self):
        assert parse_memory_mb({"memory": float(4 * BYTES_PER_GIB)}) == 4000

    def test_bytes_string(self):
        assert parse_memory_mb({"memory": str(4 * BYTES_PER_GIB)}) == 4000

    def test_small_int_treated_as_gb(self):
        # Values < 1000 are treated as GB
        assert parse_memory_mb({"memory": 8}) == 8000

    def test_mid_range_treated_as_mb(self):
        # Values 1000-999999 are treated as already MB
        assert parse_memory_mb({"memory": 4000}) == 4000

    def test_zero_memory(self):
        assert parse_memory_mb({"memory": 0}) == 0

    def test_missing_key(self):
        assert parse_memory_mb({}) == 0

    def test_empty_string(self):
        assert parse_memory_mb({"memory": ""}) == 0

    def test_non_numeric_string(self):
        assert parse_memory_mb({"memory": "abc"}) == 0

    def test_unexpected_type_returns_zero(self):
        assert parse_memory_mb({"memory": [1024]}) == 0

    def test_vm_name_in_log(self, caplog):
        parse_memory_mb({"memory": "abc"}, vm_name="test-vm")
        assert "test-vm" in caplog.text

    def test_threshold_999_treated_as_gb(self):
        assert parse_memory_mb({"memory": 999}) == 999000

    def test_threshold_1000_treated_as_mb(self):
        assert parse_memory_mb({"memory": 1000}) == 1000

    def test_threshold_999999_treated_as_mb(self):
        assert parse_memory_mb({"memory": 999999}) == 999999

    def test_threshold_1000000_treated_as_bytes(self):
        assert parse_memory_mb({"memory": 1000000}) == round(1000000 / BYTES_PER_GIB * NETBOX_MB_PER_GIB)


class TestParseCores:
    def test_int_value(self):
        assert parse_cores({"cores": 4}) == 4

    def test_float_value(self):
        assert parse_cores({"cores": 4.0}) == 4

    def test_string_value(self):
        assert parse_cores({"cores": "8"}) == 8

    def test_missing_key_defaults_to_1(self):
        assert parse_cores({}) == 1

    def test_zero_returns_1(self):
        # cores=0 is falsy, so falls through to default vcpus=1
        assert parse_cores({"cores": 0}) == 1

    def test_non_numeric_string_returns_1(self):
        assert parse_cores({"cores": "abc"}) == 1

    def test_empty_string_returns_1(self):
        assert parse_cores({"cores": ""}) == 1

    def test_unexpected_type_returns_1(self):
        assert parse_cores({"cores": [4]}) == 1

    def test_vm_name_in_log(self, caplog):
        parse_cores({"cores": "abc"}, vm_name="test-vm")
        assert "test-vm" in caplog.text
