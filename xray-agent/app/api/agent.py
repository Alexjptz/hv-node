"""Agent API endpoints."""
import uuid
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Security, status

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import verify_api_key
from app.schemas.commands import CommandRequest
from app.services.xray_manager import (
    add_user_to_config,
    get_xray_status,
    regenerate_user_in_config,
    reload_xray,
    remove_user_from_config,
    restart_xray,
)
from app.services.xray_api import (
    add_user_via_api,
    remove_user_via_api,
    regenerate_user_via_api,
)
from app.services.user_cache import user_cache

logger = get_logger(__name__)
router = APIRouter()


@router.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy", "service": "xray-agent"}


@router.post("/commands")
async def receive_command(
    request: CommandRequest,
    api_key: str = Security(verify_api_key),
) -> dict[str, Any]:
    """Receive command from Core API.

    Commands: add_user, remove_user, restart_xray
    """
    logger.info("Command received", command=request.command, user_uuid=request.user_uuid if hasattr(request, 'user_uuid') else None)

    # Handle commands that don't require UUID
    if request.command == "restart_xray":
        success = restart_xray()
        if success:
            logger.info("XRay restarted successfully")
            return {"success": True, "message": "XRay restarted successfully"}
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to restart XRay",
            )

    # Handle regenerate_user command (requires both old and new UUID)
    if request.command == "regenerate_user":
        if not request.old_user_uuid or not request.user_uuid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Both old_user_uuid and user_uuid are required for regenerate_user command",
            )
        try:
            uuid.UUID(request.old_user_uuid)
            uuid.UUID(request.user_uuid)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid UUID format",
            )

        # Try to regenerate via API first (no reload needed)
        success, short_id = regenerate_user_via_api(
            old_user_uuid=request.old_user_uuid,
            new_user_uuid=request.user_uuid,
            email=request.email,
        )
        if success:
            logger.info(
                "User regenerated via API (no reload)",
                old_user_uuid=request.old_user_uuid,
                new_user_uuid=request.user_uuid,
                short_id=short_id,
            )
        else:
            # Fallback to config update + reload
            success, short_id = regenerate_user_in_config(
                old_user_uuid=request.old_user_uuid,
                new_user_uuid=request.user_uuid,
                email=request.email,
            )
            if success:
                reload_success = reload_xray()
                if reload_success:
                    logger.info(
                        "User regenerated and XRay reloaded",
                        old_user_uuid=request.old_user_uuid,
                        new_user_uuid=request.user_uuid,
                        short_id=short_id,
                    )
                else:
                    logger.warning("User regenerated but XRay reload failed", new_user_uuid=request.user_uuid)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to regenerate user",
            )

        response = {"success": True, "message": "User regenerated successfully"}
        if short_id:
            response["short_id"] = short_id
        return response

    # Validate UUID format for other user-related commands
    if not hasattr(request, 'user_uuid') or not request.user_uuid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="user_uuid is required for this command",
        )

    try:
        uuid.UUID(request.user_uuid)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid UUID format",
        )

    # Execute command
    success = False
    short_id = None
    if request.command == "add_user":
        # Check cache first - if user already exists, skip operation (no reload needed)
        if user_cache.exists(request.user_uuid, check_sync=True):
            logger.info("User already exists in cache and XRay, skipping add operation (no reload needed)", user_uuid=request.user_uuid)
            # Get short_id from Reality config
            from app.core.reality_config import get_reality_config
            reality_config = get_reality_config()
            short_ids = reality_config.get("short_ids", [])
            short_id = short_ids[0] if short_ids else None
            success = True
            used_grpc = False  # User already exists, no operation needed, no reload needed
            # Don't reload XRay - user already exists
        else:
            # Add user via API (will add to config file and via gRPC if available)
            success, used_grpc = add_user_via_api(request.user_uuid, request.email)

        if success:
            # Get short_id from Reality config
            from app.core.reality_config import get_reality_config
            reality_config = get_reality_config()
            short_ids = reality_config.get("short_ids", [])
            short_id = short_ids[0] if short_ids else None

            # Если gRPC был использован - reload НЕ нужен (zero downtime)
            if used_grpc:
                logger.info("User added via gRPC API (zero downtime, no reload)", user_uuid=request.user_uuid, short_id=short_id)
            elif not user_cache.exists(request.user_uuid, check_sync=False):
                # Fallback на SIGHUP reload только если пользователь был добавлен (не существовал ранее)
                # Если пользователь уже существовал в кэше, reload не нужен
                reload_success = reload_xray()
                if reload_success:
                    logger.info("User added and XRay reloaded via SIGHUP", user_uuid=request.user_uuid, short_id=short_id)
                else:
                    logger.warning("User added but XRay reload failed", user_uuid=request.user_uuid)
                    success = False
            else:
                # User was already in cache, no reload needed
                logger.info("User already exists, no reload needed", user_uuid=request.user_uuid, short_id=short_id)
        else:
            logger.warning("Failed to add user", user_uuid=request.user_uuid)
            success = False
    elif request.command == "remove_user":
        # Check cache first - if user doesn't exist, skip operation
        if not user_cache.exists(request.user_uuid, check_sync=True):
            logger.info("User doesn't exist in cache, skipping remove operation", user_uuid=request.user_uuid)
            success = True  # Already removed, consider it success
        else:
            # Try to remove via API (gRPC first, then fallback)
            success, used_grpc = remove_user_via_api(request.user_uuid)
            if success:
                # Если gRPC был использован - reload НЕ нужен (zero downtime)
                if used_grpc:
                    logger.info("User removed via gRPC API (zero downtime, no reload)", user_uuid=request.user_uuid)
                else:
                    # Fallback на SIGHUP reload (если gRPC не использовался)
                    reload_success = reload_xray()
                    if reload_success:
                        logger.info("User removed and XRay reloaded via SIGHUP", user_uuid=request.user_uuid)
                    else:
                        logger.warning("User removed but XRay reload failed", user_uuid=request.user_uuid)
                        success = False
            else:
                # Fallback to config update + reload
                success = remove_user_from_config(request.user_uuid)
                if success:
                    reload_success = reload_xray()
                    if reload_success:
                        logger.info("User removed and XRay reloaded", user_uuid=request.user_uuid)
                    else:
                        logger.warning("User removed but XRay reload failed", user_uuid=request.user_uuid)
                        success = False
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown command: {request.command}",
        )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to execute command: {request.command}",
        )

    response = {"success": True, "message": f"Command {request.command} executed successfully"}
    if request.command == "add_user" and short_id:
        response["short_id"] = short_id

    return response


@router.get("/status")
async def get_status(api_key: str = Security(verify_api_key)) -> dict[str, Any]:
    """Get agent and XRay status."""
    status_info = get_xray_status()
    return {
        "agent_version": "0.1.0",
        "server_id": settings.server_id,
        "xray": status_info,
    }


@router.get("/reality")
async def get_reality_config(api_key: str = Security(verify_api_key)) -> dict[str, Any]:
    """Get Reality configuration parameters.

    Returns:
        Dictionary with Reality parameters:
        - public_key: Public key for Reality
        - fingerprint: Fingerprint (chrome, firefox, etc.)
        - sni: Server Name Indication for masquerading
        - spx: Service path
        - short_ids: List of short IDs for Reality
    """
    from app.core.reality_config import (
        get_reality_public_key,
        get_reality_fingerprint,
        get_reality_sni,
        get_reality_spx,
        get_reality_config,
    )

    reality_config = get_reality_config()
    short_ids = reality_config.get("short_ids", [])

    # Use first short_id (all users share the same short_id for masquerading)
    # This allows adding/removing users without Xray restart
    if not short_ids:
        logger.warning("No short_ids found in Reality config, this should not happen")
        short_ids = []

    return {
        "public_key": get_reality_public_key(),
        "fingerprint": get_reality_fingerprint(),
        "sni": get_reality_sni(),
        "spx": get_reality_spx(),
        "short_ids": short_ids,  # Return all short_ids (usually just one shared short_id)
    }
