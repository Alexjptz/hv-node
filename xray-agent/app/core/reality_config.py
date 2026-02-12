"""Reality configuration management."""
import json
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.utils.reality import (
    generate_reality_keys,
    generate_short_id,
    get_default_fingerprints,
    get_default_sni_list,
    get_default_spx,
)

logger = get_logger(__name__)

# Path to Reality config file
REALITY_CONFIG_PATH = Path("/etc/xray/reality.json")


def load_reality_config() -> dict[str, Any]:
    """Load Reality configuration from file.

    Returns:
        Reality configuration dictionary with keys:
        - public_key: Public key for Reality
        - private_key: Private key for Reality
        - short_ids: List of short IDs
        - fingerprint: Fingerprint (chrome, firefox, etc.)
        - sni: Server Name Indication for masquerading
        - spx: Service path
    """
    if not REALITY_CONFIG_PATH.exists():
        logger.info("Reality config not found, creating new one")
        return create_reality_config()

    try:
        with open(REALITY_CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)
        logger.debug("Reality config loaded", path=str(REALITY_CONFIG_PATH))
        return config
    except Exception as e:
        logger.error("Failed to load Reality config, creating new one", error=str(e))
        return create_reality_config()


def save_reality_config(config: dict[str, Any]) -> None:
    """Save Reality configuration to file.

    Args:
        config: Reality configuration dictionary
    """
    REALITY_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(REALITY_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    logger.info("Reality config saved", path=str(REALITY_CONFIG_PATH))


def create_reality_config() -> dict[str, Any]:
    """Create new Reality configuration.

    Returns:
        New Reality configuration dictionary
        Note: private_key is stored in hex format (for XRay config)
              public_key is stored in base64 format (for VLESS URL)
    """
    public_key, private_key = generate_reality_keys()

    # Generate initial short ID
    short_id = generate_short_id()

    config = {
        "public_key": public_key,  # base64 format for VLESS URL
        "private_key": private_key,  # base64 format for XRay config
        "short_ids": [short_id],  # List of short IDs (can have multiple)
        "fingerprint": "chrome",  # Default fingerprint
        "sni": "nltimes.nl",  # Default SNI for masquerading
        "spx": get_default_spx(),  # Service path
    }

    save_reality_config(config)
    logger.info("Created new Reality config", public_key=public_key[:16] + "...")
    return config


def get_reality_config() -> dict[str, Any]:
    """Get current Reality configuration.

    Returns:
        Reality configuration dictionary
    """
    return load_reality_config()


def add_short_id(short_id: str | None = None) -> str:
    """Add new short ID to Reality configuration.

    Args:
        short_id: Optional short ID (if None, generates new one)

    Returns:
        Short ID that was added
    """
    config = load_reality_config()

    if short_id is None:
        short_id = generate_short_id()

    if short_id not in config.get("short_ids", []):
        config.setdefault("short_ids", []).append(short_id)
        save_reality_config(config)
        logger.info("Added short ID to Reality config", short_id=short_id)
    else:
        logger.debug("Short ID already exists", short_id=short_id)

    return short_id


def get_reality_public_key() -> str:
    """Get Reality public key.

    Returns:
        Public key in base64 format
    """
    config = load_reality_config()
    return config.get("public_key", "")


def get_reality_private_key() -> str:
    """Get Reality private key.

    Returns:
        Private key in base64 format
    """
    config = load_reality_config()
    return config.get("private_key", "")


def get_reality_sni() -> str:
    """Get Reality SNI (Server Name Indication).

    Returns:
        SNI string
    """
    config = load_reality_config()
    return config.get("sni", "nltimes.nl")


def get_reality_fingerprint() -> str:
    """Get Reality fingerprint.

    Returns:
        Fingerprint string
    """
    config = load_reality_config()
    return config.get("fingerprint", "chrome")


def get_reality_spx() -> str:
    """Get Reality service path.

    Returns:
        Service path string
    """
    config = load_reality_config()
    return config.get("spx", "/")
