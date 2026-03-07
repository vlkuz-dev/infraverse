"""Yandex Cloud authentication token providers.

Supports three authentication methods:
- Static token (OAuth/IAM token string)
- Service account authorized key (JWT exchange for IAM token)
- VM metadata service (for instances running inside YC)
"""

import json
import logging
import time
from abc import ABC, abstractmethod

import httpx
import jwt

logger = logging.getLogger(__name__)

IAM_TOKEN_ENDPOINT = "https://iam.api.cloud.yandex.net/iam/v1/tokens"
METADATA_TOKEN_URL = "http://169.254.169.254/computeMetadata/v1/instance/service-accounts/default/token"

# Refresh IAM token when older than 50 minutes (tokens live up to 12h, YC recommends hourly)
_TOKEN_REFRESH_SECONDS = 50 * 60


class TokenProvider(ABC):
    """Abstract base class for Yandex Cloud token providers."""

    @abstractmethod
    def get_token(self) -> str:
        """Return a valid IAM/OAuth token string."""


class StaticTokenProvider(TokenProvider):
    """Wraps a plain token string (OAuth or IAM)."""

    def __init__(self, token: str):
        self._token = token

    def get_token(self) -> str:
        return self._token


class ServiceAccountKeyProvider(TokenProvider):
    """Exchanges a service account authorized key for IAM tokens via JWT.

    The SA key JSON must contain: id, service_account_id, private_key.
    Tokens are cached and refreshed when older than 50 minutes.
    """

    def __init__(self, sa_key: dict):
        self._key_id = sa_key["id"]
        self._service_account_id = sa_key["service_account_id"]
        self._private_key = sa_key["private_key"]
        self._cached_token: str | None = None
        self._token_obtained_at: float = 0.0

    def _create_jwt(self) -> str:
        now = int(time.time())
        payload = {
            "iss": self._service_account_id,
            "aud": IAM_TOKEN_ENDPOINT,
            "iat": now,
            "exp": now + 3600,
        }
        return jwt.encode(
            payload,
            self._private_key,
            algorithm="PS256",
            headers={"kid": self._key_id},
        )

    def _exchange_jwt_for_iam_token(self, encoded_jwt: str) -> str:
        resp = httpx.post(
            IAM_TOKEN_ENDPOINT,
            json={"jwt": encoded_jwt},
            timeout=10.0,
        )
        resp.raise_for_status()
        return resp.json()["iamToken"]

    def get_token(self) -> str:
        now = time.time()
        if self._cached_token and (now - self._token_obtained_at) < _TOKEN_REFRESH_SECONDS:
            return self._cached_token

        logger.info("Refreshing IAM token for service account %s", self._service_account_id)
        encoded_jwt = self._create_jwt()
        self._cached_token = self._exchange_jwt_for_iam_token(encoded_jwt)
        self._token_obtained_at = time.time()
        return self._cached_token


class MetadataTokenProvider(TokenProvider):
    """Fetches IAM tokens from the VM metadata service (for instances running inside YC)."""

    def __init__(self):
        self._cached_token: str | None = None
        self._token_expires_at: float = 0.0

    def get_token(self) -> str:
        now = time.time()
        if self._cached_token and now < self._token_expires_at:
            return self._cached_token

        logger.info("Fetching IAM token from metadata service")
        resp = httpx.get(
            METADATA_TOKEN_URL,
            headers={"Metadata-Flavor": "Google"},
            timeout=5.0,
        )
        resp.raise_for_status()
        data = resp.json()
        self._cached_token = data["access_token"]
        # Refresh 60 seconds before expiry
        self._token_expires_at = now + data.get("expires_in", 3600) - 60
        return self._cached_token


def resolve_token_provider(credentials: dict) -> TokenProvider:
    """Create the appropriate TokenProvider from a credentials dict.

    Priority:
        1. sa_key_file — path to SA key JSON file
        2. sa_key — inline SA key dict
        3. token — plain token string
        4. metadata — use VM metadata service
    """
    if "sa_key_file" in credentials:
        path = credentials["sa_key_file"]
        with open(path) as f:
            sa_key = json.load(f)
        return ServiceAccountKeyProvider(sa_key)

    if "sa_key" in credentials:
        return ServiceAccountKeyProvider(credentials["sa_key"])

    if "token" in credentials:
        return StaticTokenProvider(credentials["token"])

    if credentials.get("metadata"):
        return MetadataTokenProvider()

    raise ValueError(
        "No valid YC credentials found. Provide one of: "
        "sa_key_file, sa_key, token, or metadata=true"
    )
