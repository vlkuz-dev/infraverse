"""Tests for infraverse.ip.classifier module."""


from infraverse.ip.classifier import is_private_ip


class TestIsPrivateIP:
    def test_private_10_network(self):
        assert is_private_ip("10.128.0.5") is True

    def test_private_172_network(self):
        assert is_private_ip("172.20.1.1") is True

    def test_private_192_network(self):
        assert is_private_ip("192.168.0.1") is True

    def test_private_with_cidr(self):
        assert is_private_ip("10.0.0.1/24") is True

    def test_public_ip(self):
        assert is_private_ip("51.250.1.10") is False

    def test_loopback(self):
        assert is_private_ip("127.0.0.1") is True

    def test_invalid_ip(self):
        assert is_private_ip("invalid") is False

    def test_empty_string(self):
        assert is_private_ip("") is False
