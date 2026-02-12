"""XRay Reality utilities for generating keys and parameters."""
import base64
import secrets
from typing import Tuple

try:
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False

from app.core.logging import get_logger

logger = get_logger(__name__)


def generate_reality_keys() -> Tuple[str, str]:
    """Generate Reality public and private keys using X25519 curve.

    Uses cryptography library to generate X25519 keys compatible with XRay.
    XRay requires base64 format for both keys.

    Returns:
        Tuple of (public_key_base64, private_key_base64):
        - public_key_base64: Public key in base64 format (for VLESS URL)
        - private_key_base64: Private key in base64 format (for XRay config)
    """
    if CRYPTO_AVAILABLE:
        # Use X25519 curve for proper key generation
        private_key_obj = X25519PrivateKey.generate()
        public_key_obj = private_key_obj.public_key()

        # Get raw bytes (32 bytes each)
        private_key_bytes = private_key_obj.private_bytes_raw()
        public_key_bytes = public_key_obj.public_bytes_raw()

        # XRay requires URL-safe base64 format without padding (same as output of 'xray x25519' command)
        # The 'xray x25519' command outputs keys in URL-safe base64 format (uses _ and - instead of + and /)
        # and without '=' padding
        public_key = base64.urlsafe_b64encode(public_key_bytes).decode('utf-8').rstrip('=')
        private_key = base64.urlsafe_b64encode(private_key_bytes).decode('utf-8').rstrip('=')

        logger.debug("Generated Reality keys using cryptography", public_key_length=len(public_key), private_key_length=len(private_key))
    else:
        # Fallback: generate random bytes
        logger.warning("cryptography library not available, using random bytes")
        private_key_bytes = secrets.token_bytes(32)
        public_key_bytes = secrets.token_bytes(32)

        # Use URL-safe base64 without padding (same format as XRay expects)
        public_key = base64.urlsafe_b64encode(public_key_bytes).decode('utf-8').rstrip('=')
        private_key = base64.urlsafe_b64encode(private_key_bytes).decode('utf-8').rstrip('=')

        logger.warning("Using random bytes - keys may not work correctly with XRay Reality")

    return public_key, private_key


def generate_short_id() -> str:
    """Generate Reality short ID (6 hex characters).

    Returns:
        Short ID as hex string (6 characters)
    """
    # Generate 3 random bytes = 6 hex characters (matches competitor format)
    short_id_bytes = secrets.token_bytes(3)
    short_id = short_id_bytes.hex()

    logger.debug("Generated short ID", short_id=short_id)
    return short_id


def get_default_fingerprints() -> list[str]:
    """Get list of default fingerprints for Reality.

    Returns:
        List of fingerprint options
    """
    return [
        "chrome",
        "firefox",
        "safari",
        "edge",
        "ios",
        "android",
        "random",
        "randomized",
    ]


def get_default_sni_list() -> list[str]:
    """Get list of default SNI (Server Name Indication) for Reality masquerading.

    Returns:
        List of SNI options (popular legitimate services)
    """
    return [
        "nltimes.nl",
        "www.microsoft.com",
        "www.apple.com",
        "www.google.com",
        "www.cloudflare.com",
        "www.amazon.com",
        "www.github.com",
        "www.stackoverflow.com",
    ]


def get_default_spx() -> str:
    """Get default service path for Reality.

    Returns:
        Default service path
    """
    return "/"
