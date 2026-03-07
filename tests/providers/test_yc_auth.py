"""Tests for Yandex Cloud authentication token providers."""

import json
from unittest.mock import MagicMock, patch

import pytest

from infraverse.providers.yc_auth import (
    MetadataTokenProvider,
    ServiceAccountKeyProvider,
    StaticTokenProvider,
    TokenProvider,
    resolve_token_provider,
)


class TestStaticTokenProvider:
    def test_returns_token_as_is(self):
        provider = StaticTokenProvider("my-token-123")
        assert provider.get_token() == "my-token-123"

    def test_returns_same_token_every_time(self):
        provider = StaticTokenProvider("fixed")
        assert provider.get_token() == "fixed"
        assert provider.get_token() == "fixed"

    def test_implements_token_provider(self):
        assert isinstance(StaticTokenProvider("t"), TokenProvider)


SA_KEY = {
    "id": "ajeXXXXXXXXXXXXXXXXX",
    "service_account_id": "ajeYYYYYYYYYYYYYYYYY",
    "created_at": "2024-01-01T00:00:00Z",
    "key_algorithm": "RSA_2048",
    "public_key": "-----BEGIN PUBLIC KEY-----\ntest\n-----END PUBLIC KEY-----\n",
    "private_key": "-----BEGIN PRIVATE KEY-----\ntest\n-----END PRIVATE KEY-----\n",
}


class TestServiceAccountKeyProvider:
    def test_implements_token_provider(self):
        with patch.object(ServiceAccountKeyProvider, "__init__", lambda self, key: None):
            p = ServiceAccountKeyProvider.__new__(ServiceAccountKeyProvider)
            assert isinstance(p, TokenProvider)

    def test_stores_key_fields(self):
        provider = ServiceAccountKeyProvider(SA_KEY)
        assert provider._key_id == "ajeXXXXXXXXXXXXXXXXX"
        assert provider._service_account_id == "ajeYYYYYYYYYYYYYYYYY"

    @patch("infraverse.providers.yc_auth.httpx.post")
    @patch("infraverse.providers.yc_auth.jwt.encode")
    def test_get_token_creates_jwt_and_exchanges(self, mock_encode, mock_post):
        mock_encode.return_value = "signed-jwt"
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"iamToken": "iam-token-123"}
        mock_resp.raise_for_status.return_value = None
        mock_post.return_value = mock_resp

        provider = ServiceAccountKeyProvider(SA_KEY)
        token = provider.get_token()

        assert token == "iam-token-123"
        mock_encode.assert_called_once()

        # Verify JWT payload
        call_args = mock_encode.call_args
        payload = call_args[0][0]
        assert payload["iss"] == "ajeYYYYYYYYYYYYYYYYY"
        assert payload["aud"] == "https://iam.api.cloud.yandex.net/iam/v1/tokens"
        assert "iat" in payload
        assert "exp" in payload
        assert payload["exp"] - payload["iat"] == 3600

        # Verify algorithm and headers
        assert call_args[1]["algorithm"] == "PS256"
        assert call_args[1]["headers"] == {"kid": "ajeXXXXXXXXXXXXXXXXX"}

        # Verify POST call
        mock_post.assert_called_once_with(
            "https://iam.api.cloud.yandex.net/iam/v1/tokens",
            json={"jwt": "signed-jwt"},
            timeout=10.0,
        )

    @patch("infraverse.providers.yc_auth.httpx.post")
    @patch("infraverse.providers.yc_auth.jwt.encode")
    def test_caches_token(self, mock_encode, mock_post):
        mock_encode.return_value = "signed-jwt"
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"iamToken": "cached-token"}
        mock_resp.raise_for_status.return_value = None
        mock_post.return_value = mock_resp

        provider = ServiceAccountKeyProvider(SA_KEY)
        token1 = provider.get_token()
        token2 = provider.get_token()

        assert token1 == token2 == "cached-token"
        # Should only call once due to caching
        mock_post.assert_called_once()

    @patch("infraverse.providers.yc_auth.time.time")
    @patch("infraverse.providers.yc_auth.httpx.post")
    @patch("infraverse.providers.yc_auth.jwt.encode")
    def test_refreshes_after_expiry(self, mock_encode, mock_post, mock_time):
        mock_encode.return_value = "signed-jwt"

        resp1 = MagicMock()
        resp1.json.return_value = {"iamToken": "token-1"}
        resp1.raise_for_status.return_value = None
        resp2 = MagicMock()
        resp2.json.return_value = {"iamToken": "token-2"}
        resp2.raise_for_status.return_value = None
        mock_post.side_effect = [resp1, resp2]

        provider = ServiceAccountKeyProvider(SA_KEY)

        # First call at time 1000
        mock_time.return_value = 1000.0
        token1 = provider.get_token()
        assert token1 == "token-1"

        # Second call still within cache window (1000 + 2999 < 50*60)
        mock_time.return_value = 3999.0
        token2 = provider.get_token()
        assert token2 == "token-1"
        assert mock_post.call_count == 1

        # Third call after cache window (1000 + 3001 > 50*60)
        mock_time.return_value = 4001.0
        token3 = provider.get_token()
        assert token3 == "token-2"
        assert mock_post.call_count == 2


class TestMetadataTokenProvider:
    def test_implements_token_provider(self):
        assert isinstance(MetadataTokenProvider(), TokenProvider)

    @patch("infraverse.providers.yc_auth.httpx.get")
    def test_fetches_token_from_metadata(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "access_token": "metadata-token",
            "expires_in": 3600,
            "token_type": "Bearer",
        }
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        provider = MetadataTokenProvider()
        token = provider.get_token()

        assert token == "metadata-token"
        mock_get.assert_called_once_with(
            "http://169.254.169.254/computeMetadata/v1/instance/service-accounts/default/token",
            headers={"Metadata-Flavor": "Google"},
            timeout=5.0,
        )

    @patch("infraverse.providers.yc_auth.httpx.get")
    def test_caches_token(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "access_token": "cached-meta-token",
            "expires_in": 3600,
        }
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        provider = MetadataTokenProvider()
        token1 = provider.get_token()
        token2 = provider.get_token()

        assert token1 == token2 == "cached-meta-token"
        mock_get.assert_called_once()

    @patch("infraverse.providers.yc_auth.time.time")
    @patch("infraverse.providers.yc_auth.httpx.get")
    def test_refreshes_after_expiry(self, mock_get, mock_time):
        resp1 = MagicMock()
        resp1.json.return_value = {"access_token": "meta-1", "expires_in": 100}
        resp1.raise_for_status.return_value = None
        resp2 = MagicMock()
        resp2.json.return_value = {"access_token": "meta-2", "expires_in": 100}
        resp2.raise_for_status.return_value = None
        mock_get.side_effect = [resp1, resp2]

        provider = MetadataTokenProvider()

        # First call at time 1000
        mock_time.return_value = 1000.0
        token1 = provider.get_token()
        assert token1 == "meta-1"

        # Still valid (1000 + 100 - 60 = 1040)
        mock_time.return_value = 1039.0
        token2 = provider.get_token()
        assert token2 == "meta-1"
        assert mock_get.call_count == 1

        # Expired
        mock_time.return_value = 1041.0
        token3 = provider.get_token()
        assert token3 == "meta-2"
        assert mock_get.call_count == 2


class TestResolveTokenProvider:
    def test_sa_key_file(self, tmp_path):
        key_file = tmp_path / "sa-key.json"
        key_file.write_text(json.dumps(SA_KEY))

        provider = resolve_token_provider({"sa_key_file": str(key_file)})
        assert isinstance(provider, ServiceAccountKeyProvider)
        assert provider._key_id == SA_KEY["id"]

    def test_sa_key_inline(self):
        provider = resolve_token_provider({"sa_key": SA_KEY})
        assert isinstance(provider, ServiceAccountKeyProvider)
        assert provider._service_account_id == SA_KEY["service_account_id"]

    def test_token(self):
        provider = resolve_token_provider({"token": "my-token"})
        assert isinstance(provider, StaticTokenProvider)
        assert provider.get_token() == "my-token"

    def test_metadata(self):
        provider = resolve_token_provider({"metadata": True})
        assert isinstance(provider, MetadataTokenProvider)

    def test_metadata_false_raises(self):
        with pytest.raises(ValueError, match="No valid YC credentials"):
            resolve_token_provider({"metadata": False})

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="No valid YC credentials"):
            resolve_token_provider({})

    def test_priority_sa_key_file_over_token(self, tmp_path):
        key_file = tmp_path / "sa-key.json"
        key_file.write_text(json.dumps(SA_KEY))

        provider = resolve_token_provider({
            "sa_key_file": str(key_file),
            "token": "should-not-use",
        })
        assert isinstance(provider, ServiceAccountKeyProvider)

    def test_priority_sa_key_over_token(self):
        provider = resolve_token_provider({
            "sa_key": SA_KEY,
            "token": "should-not-use",
        })
        assert isinstance(provider, ServiceAccountKeyProvider)

    def test_sa_key_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            resolve_token_provider({"sa_key_file": "/nonexistent/key.json"})
