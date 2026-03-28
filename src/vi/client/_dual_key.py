"""Base client with dual-key support: Ed25519 (ARS events) + ES256 (VI credentials)."""

from __future__ import annotations

import os
from typing import Optional

from cryptography.hazmat.primitives.asymmetric.ec import EllipticCurvePrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    load_pem_private_key,
)

from ars_client._base import BaseClient
from vi.server.crypto import (
    generate_es256_keypair,
    private_key_to_jwk,
    public_key_to_jwk,
)


def _load_es256_key(
    key: Optional[EllipticCurvePrivateKey] = None,
    key_pem: Optional[str] = None,
    key_file: Optional[str] = None,
    env_var: str = "VI_ES256_KEY",
) -> EllipticCurvePrivateKey:
    """Resolve an ES256 private key from various sources.

    Priority: key > key_pem > key_file > env_var > auto-generate.
    """
    if key is not None:
        return key
    if key_pem is not None:
        return load_pem_private_key(key_pem.encode(), password=None)
    if key_file is not None:
        with open(key_file, "rb") as f:
            return load_pem_private_key(f.read(), password=None)
    env_val = os.environ.get(env_var)
    if env_val:
        return load_pem_private_key(env_val.encode(), password=None)
    # Auto-generate if no key provided
    private_key, _ = generate_es256_keypair()
    return private_key


class VIDualKeyClient(BaseClient):
    """Base for VI clients that need both Ed25519 (ARS) and ES256 (VI) keys.

    Inherits Ed25519 signing from BaseClient. Adds ES256 for credential operations.
    """

    def __init__(
        self,
        *,
        es256_private_key: Optional[EllipticCurvePrivateKey] = None,
        es256_key_pem: Optional[str] = None,
        es256_key_file: Optional[str] = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._es256_key = _load_es256_key(
            key=es256_private_key, key_pem=es256_key_pem, key_file=es256_key_file,
        )

    @property
    def es256_private_key(self) -> EllipticCurvePrivateKey:
        return self._es256_key

    @property
    def jwk(self) -> dict:
        """ES256 public key as JWK dict."""
        return public_key_to_jwk(self._es256_key.public_key())

    @property
    def private_jwk(self) -> dict:
        """ES256 private key as JWK dict (includes 'd')."""
        return private_key_to_jwk(self._es256_key)
