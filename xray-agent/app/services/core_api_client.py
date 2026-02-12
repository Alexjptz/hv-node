"""Core API client for agent communication."""
import httpx
from datetime import datetime

from app.core.config import settings
from app.core.logging import get_logger
from app.utils.retry import retry_with_backoff

logger = get_logger(__name__)


class CoreAPIClient:
    """Client for communicating with Core API."""

    def __init__(self, base_url: str, api_key: str):
        """Initialize Core API client.

        Args:
            base_url: Base URL of Core API
            api_key: API key for authentication
        """
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.client = httpx.AsyncClient(
            timeout=30.0,
            headers={"X-API-Key": api_key},
        )

    async def register_agent(self, agent_url: str, version: str) -> bool:
        """Register agent in Core API.

        Args:
            agent_url: URL of this agent
            version: Agent version

        Returns:
            True if registered successfully, False otherwise
        """
        try:
            response = await self.client.post(
                f"{self.base_url}/api/v1/servers/{settings.server_id}/agent/register",
                json={
                    "agent_url": agent_url,
                    "version": version,
                },
            )

            if response.status_code == 201:
                logger.info("Agent registered in Core API", agent_url=agent_url, version=version)
                return True
            else:
                logger.error(
                    "Failed to register agent",
                    status_code=response.status_code,
                    response=response.text,
                )
                return False

        except Exception as e:
            logger.error("Error registering agent", error=str(e))
            return False

    async def send_event(
        self,
        event: str,
        data: dict | None = None,
    ) -> bool:
        """Send event to Core API.

        Args:
            event: Event name (metrics, user_added, user_removed, xray_stopped, etc.)
            data: Event data

        Returns:
            True if sent successfully, False otherwise
        """
        async def _send():
            response = await self.client.post(
                f"{self.base_url}/api/v1/agents/webhook",
                json={
                    "event": event,
                    "server_id": settings.server_id,
                    "data": data or {},
                },
            )

            if response.status_code == 200:
                logger.debug("Event sent to Core API", event_type=event)
                return True
            else:
                logger.error(
                    "Failed to send event",
                    event_type=event,
                    status_code=response.status_code,
                    response=response.text,
                )
                response.raise_for_status()  # Raise for retry logic
                return False

        try:
            # Use retry with exponential backoff for resilience
            result = await retry_with_backoff(_send, max_retries=2, initial_delay=1.0)
            return result if result is not None else False
        except (httpx.HTTPError, httpx.ConnectError, httpx.TimeoutException) as e:
            # For connection errors, log warning instead of error (less noisy)
            logger.warning(
                "Failed to send event after retries - Core API may be temporarily unavailable",
                event_type=event,
                error=str(e)
            )
            return False
        except Exception as e:
            logger.error("Error sending event", exc_info=True, event_type=event)
            return False

    async def send_metrics(self, metrics: dict) -> bool:
        """Send metrics to Core API.

        Args:
            metrics: Metrics dictionary

        Returns:
            True if sent successfully, False otherwise
        """
        return await self.send_event("metrics", data=metrics)

    async def close(self):
        """Close HTTP client."""
        await self.client.aclose()
