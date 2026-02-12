"""XRay API client for dynamic user management."""
import json
import subprocess
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.services.user_cache import user_cache

logger = get_logger(__name__)


def update_inbound_via_api(inbound_config: dict[str, Any], tag: str = "vless") -> bool:
    """Update inbound configuration via HandlerService API (dynamic, no reload needed).

    Args:
        inbound_config: Complete inbound configuration dictionary
        tag: Inbound tag (default: "vless")

    Returns:
        True if successful, False otherwise
    """
    try:
        # Используем прямой вызов gRPC клиента для добавления/удаления пользователей
        # Для полного обновления inbound используем fallback на SIGHUP
        # (так как это сложная операция и редко используется)
        logger.debug("Full inbound update not supported via API, using fallback", tag=tag)
        return False

    except Exception as e:
        logger.error("Error updating inbound via API", tag=tag, error=str(e))
        return False


def add_user_via_api(user_uuid: str, email: str | None = None) -> tuple[bool, bool]:
    """Add user to Xray via HandlerService API (dynamic, no reload needed).

    Args:
        user_uuid: UUID for VLESS user
        email: Optional email for user identification

    Returns:
        Tuple of (success: bool, used_grpc: bool)
        - success: True if user was added successfully
        - used_grpc: True if gRPC was used (zero downtime), False if fallback to SIGHUP
    """
    from app.services.xray_manager import load_xray_config, save_xray_config

    # Load current config
    config = load_xray_config()

    # Find VLESS inbound
    vless_inbound = None
    inbound_tag = "vless"
    for inbound in config.get("inbounds", []):
        if inbound.get("protocol") == "vless":
            vless_inbound = inbound
            inbound_tag = inbound.get("tag", "vless")  # Get tag from config or use default
            break

    if not vless_inbound:
        logger.error("VLESS inbound not found")
        return False, False  # success=False, used_grpc=False

    # Check if user already exists (by UUID)
    clients = vless_inbound.get("settings", {}).get("clients", [])
    for client in clients:
        if client.get("id") == user_uuid:
            logger.info("User already exists in XRay - this is OK", user_uuid=user_uuid)
            # User already exists - this is OK, return True (no gRPC needed, no reload needed)
            return True, False  # success=True, used_grpc=False

    # 3. Добавление нового пользователя
    email_to_use = email or f"user-{user_uuid[:8]}"
    # Remove any duplicate emails before adding
    clients = [c for c in clients if not (c.get("email") == email_to_use and c.get("id") != user_uuid)]

    # Remove any duplicate emails before adding (XRay doesn't allow duplicate emails)
    email_to_use = email or f"user-{user_uuid[:8]}"
    # Remove clients with same email but different UUID (keep only the one with matching UUID)
    clients = [c for c in clients if not (c.get("email") == email_to_use and c.get("id") != user_uuid)]

    # Add new user
    from app.core.reality_config import get_reality_config
    reality_config = get_reality_config()
    short_ids = reality_config.get("short_ids", [])
    short_id = short_ids[0] if short_ids else None

    new_client = {
        "id": user_uuid,
        "email": email_to_use,
        "flow": "xtls-rprx-vision",  # Used with Reality (as competitor config shows)
    }
    clients.append(new_client)
    vless_inbound["settings"]["clients"] = clients

    # Попытка добавить через gRPC API (zero downtime)
    from app.services.xray_grpc_client import grpc_client

    if grpc_client.is_available():
        if grpc_client.add_user(tag=inbound_tag, user_uuid=user_uuid, email=email_to_use):
            # Сохраняем в конфиг для persistence (после перезапуска XRay)
            save_xray_config(config)
            # Обновляем кэш
            user_cache.add(user_uuid)
            logger.info("User added via gRPC API (zero downtime, no reload)", user_uuid=user_uuid, short_id=short_id)
            return True, True  # success=True, used_grpc=True
        else:
            logger.warning("gRPC add_user failed, falling back to SIGHUP reload", user_uuid=user_uuid)

    # Fallback to config file update + SIGHUP reload (если gRPC недоступен или не сработал)
    save_xray_config(config)
    # Update cache
    user_cache.add(user_uuid)
    logger.info("User added via config update (SIGHUP reload fallback)", user_uuid=user_uuid)
    return True, False  # success=True, used_grpc=False


def remove_user_via_api(user_uuid: str) -> tuple[bool, bool]:
    """Remove user from Xray via HandlerService API (dynamic, no reload needed).

    Args:
        user_uuid: UUID for VLESS user

    Returns:
        Tuple of (success: bool, used_grpc: bool)
        - success: True if user was removed successfully
        - used_grpc: True if gRPC was used (zero downtime), False if fallback to SIGHUP
    """
    from app.services.xray_manager import load_xray_config, save_xray_config

    # Load current config
    config = load_xray_config()

    # Find VLESS inbound
    vless_inbound = None
    inbound_tag = "vless"
    for inbound in config.get("inbounds", []):
        if inbound.get("protocol") == "vless":
            vless_inbound = inbound
            inbound_tag = inbound.get("tag", "vless")  # Get tag from config or use default
            break

    if not vless_inbound:
        logger.error("VLESS inbound not found")
        return False, False

    # Найти email пользователя перед удалением (нужен для gRPC)
    clients = vless_inbound.get("settings", {}).get("clients", [])
    user_email = None
    user_found = False

    for client in clients:
        if client.get("id") == user_uuid:
            user_email = client.get("email")
            user_found = True
            break

    if not user_found:
        logger.warning("User not found in config", user_uuid=user_uuid)
        return False, False

    # Попытка удалить через gRPC API (zero downtime)
    from app.services.xray_grpc_client import grpc_client

    if grpc_client.is_available() and user_email:
        if grpc_client.remove_user(tag=inbound_tag, user_uuid=user_uuid, email=user_email):
            # Удаляем из конфига для синхронизации
            clients[:] = [c for c in clients if c.get("id") != user_uuid]
            vless_inbound["settings"]["clients"] = clients
            save_xray_config(config)
            # Обновляем кэш
            user_cache.remove(user_uuid)
            logger.info("User removed via gRPC API (zero downtime, no reload)", user_uuid=user_uuid)
            return True, True  # success=True, used_grpc=True

    # Fallback to config file update + SIGHUP reload (если gRPC недоступен или не сработал)
    logger.warning("gRPC remove_user failed or unavailable, falling back to SIGHUP reload", user_uuid=user_uuid)
    clients[:] = [c for c in clients if c.get("id") != user_uuid]
    vless_inbound["settings"]["clients"] = clients
    save_xray_config(config)
    # Update cache
    user_cache.remove(user_uuid)
    logger.info("User removed via config update (SIGHUP reload fallback)", user_uuid=user_uuid)
    return True, False  # success=True, used_grpc=False


def regenerate_user_via_api(old_user_uuid: str, new_user_uuid: str, email: str | None = None) -> tuple[bool, str | None]:
    """Regenerate user via HandlerService API (dynamic, no reload needed).

    Args:
        old_user_uuid: UUID of old user to remove
        new_user_uuid: UUID of new user to add
        email: Email for new user (optional)

    Returns:
        Tuple of (success: bool, short_id: str | None)
    """
    from app.services.xray_manager import load_xray_config, save_xray_config
    from app.core.reality_config import get_reality_config

    # Load current config
    config = load_xray_config()

    # Find VLESS inbound
    vless_inbound = None
    inbound_tag = "vless"
    for inbound in config.get("inbounds", []):
        if inbound.get("protocol") == "vless":
            vless_inbound = inbound
            inbound_tag = inbound.get("tag", "vless")  # Get tag from config or use default
            break

    if not vless_inbound:
        logger.error("VLESS inbound not found")
        return False, None

    clients = vless_inbound.get("settings", {}).get("clients", [])

    # Remove old user
    original_count = len(clients)
    clients[:] = [c for c in clients if c.get("id") != old_user_uuid]
    removed = len(clients) < original_count

    # Add new user
    reality_config = get_reality_config()
    short_ids = reality_config.get("short_ids", [])
    short_id = short_ids[0] if short_ids else None

    new_client = {
        "id": new_user_uuid,
        "email": email or f"user-{new_user_uuid[:8]}",
        "flow": "xtls-rprx-vision",  # Used with Reality (as competitor config shows)
    }
    clients.append(new_client)
    vless_inbound["settings"]["clients"] = clients

    # Try to update via API first (no reload needed!)
    if update_inbound_via_api(vless_inbound, tag=inbound_tag):
        # Also save to config file for persistence
        save_xray_config(config)
        # Update cache
        user_cache.remove(old_user_uuid)
        user_cache.add(new_user_uuid)
        logger.info(
            "User regenerated via API (no reload)",
            old_user_uuid=old_user_uuid,
            new_user_uuid=new_user_uuid,
            short_id=short_id,
        )
        return True, short_id
    else:
        # Fallback to config file update + SIGHUP reload
        save_xray_config(config)
        # Update cache
        user_cache.remove(old_user_uuid)
        user_cache.add(new_user_uuid)
        logger.info(
            "User regenerated via config update (SIGHUP reload)",
            old_user_uuid=old_user_uuid,
            new_user_uuid=new_user_uuid,
        )
        return True, short_id
