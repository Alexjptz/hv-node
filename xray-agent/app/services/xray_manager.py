"""XRay configuration management."""
import json
import subprocess
import uuid
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def load_xray_config() -> dict[str, Any]:
    """Load XRay configuration from file.

    Returns:
        XRay configuration dictionary

    Raises:
        FileNotFoundError: If config file doesn't exist
        json.JSONDecodeError: If config is invalid JSON
    """
    config_path = Path(settings.xray_config_path)
    if not config_path.exists():
        logger.warning("XRay config file not found, creating default", path=str(config_path))
        return get_default_config()

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    # Миграция: maxTimeDiff 0, 30, 300 → 10 (строгая replay protection)
    for inbound in config.get("inbounds", []):
        if inbound.get("protocol") == "vless":
            reality = inbound.get("streamSettings", {}).get("realitySettings", {})
            current = reality.get("maxTimeDiff")
            if current in (0, 30, 300):
                reality["maxTimeDiff"] = 10
                logger.info("Migrated maxTimeDiff %s→10 (replay protection)", current)
                try:
                    save_xray_config(config)
                    reload_xray()
                except Exception as e:
                    logger.warning("Migration save/reload failed", error=str(e))
                break

    logger.debug("XRay config loaded", path=str(config_path))
    return config


def validate_xray_config(config: dict[str, Any]) -> tuple[bool, str | None]:
    """Validate XRay configuration before saving.

    Args:
        config: XRay configuration dictionary

    Returns:
        Tuple of (is_valid: bool, error_message: str | None)
    """
    try:
        # Save config to temporary file for validation
        import tempfile
        import os
        tmp_fd, tmp_path = tempfile.mkstemp(suffix='.json', text=True)
        try:
            with os.fdopen(tmp_fd, 'w') as tmp_file:
                json.dump(config, tmp_file, indent=2, ensure_ascii=False)

            # Copy temp file to container's filesystem for validation
            # Or validate directly by copying config content
            # Try both container names (development and production)
            # Use docker cp to copy file into container, then test
            container_name = None
            for name in ['homevpn_xray_server', 'xray-server']:
                result = subprocess.run(
                    f"docker ps --format '{{{{.Names}}}}' | grep -q '^{name}$'",
                    shell=True,
                    capture_output=True,
                )
                if result.returncode == 0:
                    container_name = name
                    break

            if container_name:
                # Copy temp file to container
                container_tmp_path = f"/tmp/xray_config_validate_{os.getpid()}.json"
                copy_result = subprocess.run(
                    f"docker cp {tmp_path} {container_name}:{container_tmp_path}",
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )

                if copy_result.returncode == 0:
                    # Validate using xray -test command inside container
                    test_result = subprocess.run(
                        f"docker exec {container_name} xray -test -config {container_tmp_path}",
                        shell=True,
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )

                    # Clean up temp file in container
                    subprocess.run(
                        f"docker exec {container_name} rm -f {container_tmp_path}",
                        shell=True,
                        capture_output=True,
                    )

                    if test_result.returncode == 0:
                        return True, None
                    else:
                        error_msg = test_result.stderr or test_result.stdout or "Unknown validation error"
                        return False, error_msg
                else:
                    logger.warning("Failed to copy config to container for validation", error=copy_result.stderr)
            else:
                logger.warning("XRay container not found for validation")

        finally:
            # Clean up temporary file
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

        # If validation mechanism fails, allow save but log warning
        logger.warning("Config validation skipped (container not available or validation failed)")
        return True, None

    except Exception as e:
        logger.warning("Config validation failed, will proceed with save", error=str(e))
        # If validation fails (e.g., docker not available), allow save but log warning
        return True, None  # Allow save if validation mechanism fails


def save_xray_config(config: dict[str, Any], validate: bool = True) -> None:
    """Save XRay configuration to file.

    Args:
        config: XRay configuration dictionary
        validate: Whether to validate config before saving (default: True)

    Raises:
        ValueError: If config validation fails
        IOError: If file cannot be written
    """
    # Validate config before saving
    if validate:
        is_valid, error_msg = validate_xray_config(config)
        if not is_valid:
            logger.error("XRay config validation failed", error=error_msg)
            raise ValueError(f"Invalid XRay configuration: {error_msg}")

    config_path = Path(settings.xray_config_path)
    config_path.parent.mkdir(parents=True, exist_ok=True)

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    logger.info("XRay config saved", path=str(config_path))


def _convert_private_key_to_hex(private_key_base64: str) -> str:
    """Convert private key from base64 to hex format for XRay.

    Args:
        private_key_base64: Private key in URL-safe base64 format (without padding)

    Returns:
        Private key in hex format (64 characters) for XRay config
    """
    import base64
    try:
        # XRay Reality uses URL-safe base64 format (with _ and - instead of + and /)
        # and without padding. We need to decode it properly.
        # Add padding if needed for base64 decoding
        padding = 4 - len(private_key_base64) % 4
        if padding != 4:
            private_key_base64 += '=' * padding

        # Use urlsafe_b64decode to handle URL-safe base64 format
        private_key_bytes = base64.urlsafe_b64decode(private_key_base64)
        return private_key_bytes.hex()
    except Exception as e:
        logger.error("Failed to convert private key to hex", error=str(e))
        return ""


def get_default_config() -> dict[str, Any]:
    """Get default XRay configuration with Reality support.

    Returns:
        Default XRay configuration with Reality
    """
    from app.core.reality_config import (
        get_reality_config,
        get_reality_fingerprint,
        get_reality_sni,
        get_reality_spx,
    )

    # Load Reality configuration
    reality_config = get_reality_config()
    public_key = reality_config.get("public_key", "")
    private_key_base64 = reality_config.get("private_key", "")
    short_ids = reality_config.get("short_ids", [])
    fingerprint = get_reality_fingerprint()
    sni = get_reality_sni()
    spx = get_reality_spx()

    # Use only the primary SNI from Reality config (single SNI like competitor)
    # Multiple SNIs can cause connection issues with some clients
    server_names = [sni] if sni else []

    # If no short IDs, generate one
    if not short_ids:
        from app.utils.reality import generate_short_id
        short_id = generate_short_id()
        short_ids = [short_id]
        reality_config["short_ids"] = short_ids
        from app.core.reality_config import save_reality_config
        save_reality_config(reality_config)

    # Preserve existing users from current config if it exists
    existing_clients = []
    try:
        config_path = Path(settings.xray_config_path)
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                existing_config = json.load(f)
            # Extract clients from existing VLESS inbound
            for inbound in existing_config.get("inbounds", []):
                if inbound.get("protocol") == "vless":
                    existing_clients = inbound.get("settings", {}).get("clients", [])
                    logger.info("Preserving existing users in default config", users_count=len(existing_clients))
                    break
    except Exception as e:
        logger.warning("Failed to load existing config to preserve users", error=str(e))
        # Continue with empty clients list if config is corrupted
        existing_clients = []

    return {
        "log": {
            "loglevel": "warning"  # Changed to "warning" to reduce noise from scanning attempts (only show warnings and errors)
        },
        "stats": {},  # Enable stats for dynamic user management
        "api": {
            "tag": "api",
            "services": ["HandlerService", "StatsService"]  # HandlerService for dynamic user management
        },
        "inbounds": [
            {
                "tag": "vless",
                "listen": "0.0.0.0",  # Listen on all interfaces
                "port": 433,  # Non-standard port to reduce scanning and attacks (like competitor)
                "protocol": "vless",
                "settings": {
                    "clients": existing_clients,  # Preserve existing users
                    "decryption": "none",
                    "fallbacks": [
                        {
                            "dest": f"{sni}:443",  # Fallback to masquerading destination for invalid requests
                            "xver": 0
                        }
                    ]
                },
                "streamSettings": {
                    "network": "tcp",  # TCP instead of WebSocket
                    "security": "reality",  # Reality instead of TLS
                    "realitySettings": {
                        "show": False,
                        "dest": f"{sni}:443",  # Destination for masquerading (keep 443 for SNI)
                        "xver": 0,
                        "serverNames": server_names,  # Multiple SNIs for better masquerading (all accessible from Russia)
                        "publicKey": public_key,  # Public key in base64 format for XRay Reality (required for authentication)
                        "privateKey": private_key_base64,  # Private key in base64 format for XRay Reality (XRay requires base64, not hex!)
                        "minClientVer": "",
                        "maxClientVer": "",
                        "maxTimeDiff": 10,  # 10 sec — строгая replay protection (0=off)
                        "shortIds": short_ids  # List of short IDs
                    },
                    "tcpSettings": {
                        "acceptProxyProtocol": False,
                        "header": {
                            "type": "none"
                        },
                        "keepAlive": True,  # Enable TCP keepalive to detect dead connections
                        "tcpKeepAliveInterval": 10,  # Send keepalive every 10 seconds
                        "tcpKeepAliveIdle": 30,  # Start keepalive after 30 seconds of idle
                        "tcpKeepAliveCount": 3  # Close connection after 3 failed keepalive attempts
                    }
                },
                "sniffing": {
                    "enabled": True,  # Required for proper routing
                    "destOverride": ["http", "tls"]
                }
            },
            {
                "listen": "0.0.0.0",  # Listen on all interfaces to allow gRPC access from other containers
                "port": 10085,
                "protocol": "dokodemo-door",
                "settings": {
                    "address": "127.0.0.1"
                },
                "tag": "api"
            }
        ],
        "outbounds": [
            {
                "protocol": "freedom",
                "settings": {}
            }
        ],
        "routing": {
            "rules": [
                {
                    "inboundTag": ["api"],
                    "outboundTag": "api",
                    "type": "field"
                }
            ]
        }
    }


def add_user_to_config(user_uuid: str, email: str | None = None) -> tuple[bool, str | None]:
    """Add user to XRay configuration.

    Args:
        user_uuid: UUID for VLESS user
        email: Optional email for user identification

    Returns:
        Tuple of (success, short_id):
        - success: True if user added successfully, False if user already exists
        - short_id: Reality short ID for this user (if Reality is enabled)
    """
    config = load_xray_config()

    # Find VLESS inbound
    vless_inbound = None
    for inbound in config.get("inbounds", []):
        if inbound.get("protocol") == "vless":
            vless_inbound = inbound
            break

    if not vless_inbound:
        logger.error("VLESS inbound not found in config")
        return False, None

    clients = vless_inbound.get("settings", {}).get("clients", [])

    # Check if user already exists (by UUID)
    for client in clients:
        if client.get("id") == user_uuid:
            logger.info("User already exists in XRay config - this is OK", user_uuid=user_uuid)
            # Try to get existing short_id from Reality config
            from app.core.reality_config import get_reality_config
            reality_config = get_reality_config()
            short_ids = reality_config.get("short_ids", [])
            existing_short_id = short_ids[0] if short_ids else None
            # User already exists - this is OK, return True to indicate success
            return True, existing_short_id

    # Remove any duplicate emails before adding (XRay doesn't allow duplicate emails)
    email_to_use = email or f"user-{user_uuid[:8]}"
    # Remove clients with same email but different UUID (keep only the one with matching UUID)
    clients = [c for c in clients if not (c.get("email") == email_to_use and c.get("id") != user_uuid)]

    # Add new user with Reality flow
    # Use existing short_id from config (no need to generate new one)
    from app.core.reality_config import get_reality_config

    # Get existing short_id from Reality config (use first one)
    reality_config = get_reality_config()
    short_ids = reality_config.get("short_ids", [])
    short_id = short_ids[0] if short_ids else None

    # No need to update shortIds in XRay config - they don't change
    logger.debug("Using existing short_id", short_id=short_id)

    new_client = {
        "id": user_uuid,
        "email": email_to_use,
        "flow": "xtls-rprx-vision",  # Used with Reality (as competitor config shows)
    }
    clients.append(new_client)
    vless_inbound["settings"]["clients"] = clients

    save_xray_config(config)
    logger.info("User added to XRay config", user_uuid=user_uuid, email=email, short_id=short_id)

    # Update cache
    user_cache.add(user_uuid)

    return True, short_id


def remove_user_from_config(user_uuid: str) -> bool:
    """Remove user from XRay configuration.

    Args:
        user_uuid: UUID of user to remove

    Returns:
        True if user removed successfully, False if user not found
    """
    config = load_xray_config()

    # Find VLESS inbound
    vless_inbound = None
    for inbound in config.get("inbounds", []):
        if inbound.get("protocol") == "vless":
            vless_inbound = inbound
            break

    if not vless_inbound:
        logger.error("VLESS inbound not found in config")
        return False

    clients = vless_inbound.get("settings", {}).get("clients", [])

    # Remove user
    original_count = len(clients)
    clients[:] = [c for c in clients if c.get("id") != user_uuid]

    if len(clients) == original_count:
        logger.warning("User not found in config", user_uuid=user_uuid)
        return False

    vless_inbound["settings"]["clients"] = clients
    save_xray_config(config)
    logger.info("User removed from XRay config", user_uuid=user_uuid)
    return True


def regenerate_user_in_config(old_user_uuid: str, new_user_uuid: str, email: str | None = None) -> tuple[bool, str | None]:
    """Regenerate user in XRay configuration (remove old and add new in one operation).

    This function removes the old user and adds a new user with a new UUID in a single operation,
    which allows reloading XRay only once instead of twice.

    Args:
        old_user_uuid: UUID of old user to remove
        new_user_uuid: UUID of new user to add
        email: Email for new user (optional)

    Returns:
        Tuple of (success: bool, short_id: str | None)
    """
    config = load_xray_config()

    # Find VLESS inbound
    vless_inbound = None
    for inbound in config.get("inbounds", []):
        if inbound.get("protocol") == "vless":
            vless_inbound = inbound
            break

    if not vless_inbound:
        logger.error("VLESS inbound not found in config")
        return False, None

    clients = vless_inbound.get("settings", {}).get("clients", [])

    # Remove old user (if exists)
    original_count = len(clients)
    clients[:] = [c for c in clients if c.get("id") != old_user_uuid]
    removed = len(clients) < original_count
    if removed:
        logger.info("Old user removed from config", old_user_uuid=old_user_uuid)
    else:
        logger.debug("Old user not found in config (may not exist)", old_user_uuid=old_user_uuid)

    # Add new user with Reality flow
    # Use existing short_id from config (no need to generate new one)
    from app.core.reality_config import get_reality_config

    # Get existing short_id from Reality config (use first one)
    reality_config = get_reality_config()
    short_ids = reality_config.get("short_ids", [])
    short_id = short_ids[0] if short_ids else None

    # No need to update shortIds in XRay config - they don't change
    logger.debug("Using existing short_id", short_id=short_id)

    new_client = {
        "id": new_user_uuid,
        "email": email or f"user-{new_user_uuid[:8]}",
        # Note: flow parameter is not used for Reality protocol
    }
    clients.append(new_client)
    vless_inbound["settings"]["clients"] = clients

    save_xray_config(config)
    logger.info(
        "User regenerated in XRay config",
        old_user_uuid=old_user_uuid,
        new_user_uuid=new_user_uuid,
        email=email,
        short_id=short_id,
    )

    # Update cache
    user_cache.remove(old_user_uuid)
    user_cache.add(new_user_uuid)

    return True, short_id


def reload_xray() -> bool:
    """Reload XRay configuration.

    Returns:
        True if reload successful, False otherwise
    """
    try:
        result = subprocess.run(
            settings.xray_reload_command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            logger.info("XRay reloaded successfully")
            return True
        else:
            logger.error("XRay reload failed", stderr=result.stderr, stdout=result.stdout)
            return False
    except subprocess.TimeoutExpired:
        logger.error("XRay reload timeout")
        return False
    except Exception as e:
        logger.error("Error reloading XRay", error=str(e))
        return False


def restart_xray() -> bool:
    """Restart XRay service completely.

    Returns:
        True if restart successful, False otherwise
    """
    try:
        # Try docker restart first (if XRay runs in Docker)
        result = subprocess.run(
            "docker restart xray-server || docker restart homevpn_xray_server || systemctl restart xray || service xray restart",
            shell=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0:
            logger.info("XRay restarted successfully")
            # Mark XRay reload in cache and sync cache from config
            user_cache.mark_xray_reloaded()
            user_cache.sync_from_config()
            return True
        else:
            logger.error("XRay restart failed", stderr=result.stderr, stdout=result.stdout)
            return False
    except subprocess.TimeoutExpired:
        logger.error("XRay restart timeout")
        return False
    except Exception as e:
        logger.error("Error restarting XRay", error=str(e))
        return False


def get_xray_status() -> dict[str, Any]:
    """Get XRay status.

    Returns:
        Dictionary with XRay status information
    """
    config_path = Path(settings.xray_config_path)
    config_exists = config_path.exists()

    # Try to check if XRay process is running
    # Use gRPC API instead of direct TCP connection to avoid Reality protocol errors
    xray_running = False
    try:
        # Check via gRPC API (port 10085) instead of VPN port (433)
        # This avoids "failed to read client hello" errors from healthcheck
        from app.services.xray_grpc_client import grpc_client
        xray_running = grpc_client.is_available()
    except Exception:
        # Fallback: check if config file exists and is valid
        try:
            if config_exists:
                config = load_xray_config()
                xray_running = bool(config.get("inbounds"))
        except Exception:
            pass

    # Count users
    users_count = 0
    if config_exists:
        try:
            config = load_xray_config()
            for inbound in config.get("inbounds", []):
                if inbound.get("protocol") == "vless":
                    clients = inbound.get("settings", {}).get("clients", [])
                    users_count = len(clients)
                    break
        except Exception:
            pass

    return {
        "xray_running": xray_running,
        "config_exists": config_exists,
        "users_count": users_count,
    }
