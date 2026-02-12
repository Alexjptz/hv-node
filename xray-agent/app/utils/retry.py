"""Retry utilities for API calls."""
import asyncio
from typing import Callable, TypeVar, Any
from functools import wraps

from app.core.logging import get_logger

logger = get_logger(__name__)

T = TypeVar('T')


async def retry_with_backoff(
    func: Callable[..., T],
    max_retries: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
    *args,
    **kwargs
) -> T | None:
    """Retry function with exponential backoff.

    Args:
        func: Async function to retry
        max_retries: Maximum number of retries
        initial_delay: Initial delay in seconds
        backoff_factor: Backoff multiplier
        *args: Positional arguments for func
        **kwargs: Keyword arguments for func

    Returns:
        Function result or None if all retries failed
    """
    delay = initial_delay

    for attempt in range(max_retries):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            if attempt == max_retries - 1:
                logger.error(
                    "Max retries reached",
                    function=func.__name__,
                    error=str(e),
                    attempts=max_retries
                )
                raise  # Re-raise on final attempt

            logger.warning(
                "Retry attempt",
                function=func.__name__,
                attempt=attempt + 1,
                max_retries=max_retries,
                delay=delay,
                error=str(e)
            )
            await asyncio.sleep(delay)
            delay *= backoff_factor

    return None
