"""Main FastAPI application."""
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.agent import router as agent_router
from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.services.core_api_client import CoreAPIClient
from app.services.user_cache import user_cache

# Setup logging
setup_logging(log_level=settings.log_level)
logger = get_logger(__name__)

# Global client
core_api_client: CoreAPIClient | None = None


async def register_with_core_api() -> None:
    """Register agent with Core API on startup."""
    global core_api_client

    if not settings.agent_api_key or not settings.server_id:
        logger.warning("Agent API key or server ID not set, skipping registration")
        return

    if not settings.core_api_url:
        logger.warning("Core API URL not set, skipping registration")
        return

    # Determine agent URL
    # В продакшене это должен быть публичный IP/домен
    agent_url = settings.agent_url or f"http://localhost:{settings.agent_port}"

    core_api_client = CoreAPIClient(
        base_url=settings.core_api_url,
        api_key=settings.agent_api_key,
    )

    success = await core_api_client.register_agent(
        agent_url=agent_url,
        version="0.1.0",
    )

    if success:
        logger.info("Agent registered successfully", agent_url=agent_url)
    else:
        logger.error("Failed to register agent")


async def send_metrics_periodically() -> None:
    """Send metrics to Core API periodically."""
    from app.services.xray_manager import get_xray_status

    while True:
        try:
            await asyncio.sleep(settings.metrics_interval)

            if core_api_client:
                status_info = get_xray_status()
                # Get system load average (1-minute load average)
                try:
                    import os
                    load_avg = os.getloadavg()[0]  # 1-minute load average
                except (OSError, AttributeError):
                    # Fallback if getloadavg not available (Windows or older systems)
                    load_avg = 0.0

                # Get XRay uptime (approximate, based on process start time)
                uptime_seconds = 0
                try:
                    import subprocess
                    # Try to get XRay container uptime
                    result = subprocess.run(
                        "docker inspect -f '{{.State.StartedAt}}' homevpn_xray_server 2>/dev/null || docker inspect -f '{{.State.StartedAt}}' xray-server 2>/dev/null || echo ''",
                        shell=True,
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    if result.returncode == 0 and result.stdout.strip():
                        from datetime import datetime
                        try:
                            started_at = datetime.fromisoformat(result.stdout.strip().replace('Z', '+00:00'))
                            uptime_seconds = int((datetime.now(started_at.tzinfo) - started_at).total_seconds())
                        except Exception:
                            pass
                except Exception:
                    pass

                metrics = {
                    "load": load_avg,
                    "users_count": status_info.get("users_count", 0),
                    "xray_status": "running" if status_info.get("xray_running") else "stopped",
                    "uptime": uptime_seconds,
                }

                await core_api_client.send_metrics(metrics)
                logger.debug("Metrics sent", metrics=metrics)

        except Exception as e:
            logger.error("Error sending metrics", exc_info=True)


async def monitor_xray_status() -> None:
    """Monitor XRay status and send alerts."""
    from app.services.xray_manager import get_xray_status

    last_status = None

    while True:
        try:
            await asyncio.sleep(settings.xray_check_interval)

            if core_api_client:
                status_info = get_xray_status()
                xray_running = status_info.get("xray_running", False)

                # Check if XRay stopped
                if last_status is True and not xray_running:
                    logger.warning("XRay stopped!")
                    await core_api_client.send_event("xray_stopped", data=status_info)

                last_status = xray_running

        except Exception as e:
            logger.error("Error monitoring XRay status", error=str(e))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager."""
    # Startup
    logger.info("Starting XRay Agent", version="0.1.0")

    # Initialize user cache by syncing from config file
    try:
        user_cache.sync_from_config()
        logger.info("User cache initialized", users_count=user_cache.count())
    except Exception as e:
        logger.warning("Failed to initialize user cache, will sync on first use", error=str(e))

    # Register with Core API
    await register_with_core_api()

    # Start background tasks
    metrics_task = asyncio.create_task(send_metrics_periodically())
    monitor_task = asyncio.create_task(monitor_xray_status())

    yield

    # Shutdown
    logger.info("Shutting down XRay Agent")
    metrics_task.cancel()
    monitor_task.cancel()

    if core_api_client:
        await core_api_client.close()


# Create FastAPI app
app = FastAPI(
    title="XRay Agent",
    description="Agent service for managing XRay on VPN servers",
    version="0.1.0",
    lifespan=lifespan,
)

# Include routers
app.include_router(agent_router)


@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint.

    Returns basic metrics in Prometheus format.
    For full Prometheus integration, consider using prometheus_client library.
    """
    from fastapi import Response
    from app.services.xray_manager import get_xray_status

    try:
        status_info = get_xray_status()
        # Get system load average
        try:
            import os
            load_avg = os.getloadavg()[0]
        except (OSError, AttributeError):
            load_avg = 0.0

        # Format Prometheus metrics
        metrics_text = f"""# XRay Agent Metrics
xray_agent_users_count {status_info.get("users_count", 0)}
xray_agent_xray_running {1 if status_info.get("xray_running") else 0}
xray_agent_system_load {load_avg}
"""
        return Response(content=metrics_text, media_type="text/plain")
    except Exception as e:
        logger.error("Error generating metrics", error=str(e))
        return Response(
            content="# XRay Agent Metrics\n# Error generating metrics\n",
            media_type="text/plain"
        )


@app.on_event("startup")
async def startup_event() -> None:
    """Startup event handler."""
    logger.info("XRay Agent started", version="0.1.0")


@app.on_event("shutdown")
async def shutdown_event() -> None:
    """Shutdown event handler."""
    logger.info("XRay Agent shutting down")
