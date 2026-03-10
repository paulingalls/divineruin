"""Push notification helper — sends via the server's internal push endpoint."""

import logging
import os

import aiohttp

logger = logging.getLogger("divineruin.push")

_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=5)

_INTERNAL_SECRET = os.environ.get("INTERNAL_SECRET", "")
if not _INTERNAL_SECRET:
    logger.warning("INTERNAL_SECRET is not set — push notifications will send empty auth headers")


async def send_push_notification(player_id: str, title: str, body: str) -> None:
    """Send push notification via the server's push endpoint."""
    server_url = os.environ.get("SERVER_URL", "http://localhost:3001")
    if not server_url.startswith(("http://", "https://")):
        logger.error("SERVER_URL has invalid protocol: %s", server_url[:32])
        return
    try:
        async with aiohttp.ClientSession(timeout=_REQUEST_TIMEOUT) as session:
            async with session.post(
                f"{server_url}/api/internal/push",
                json={"player_id": player_id, "title": title, "body": body},
                headers={"X-Internal-Secret": _INTERNAL_SECRET},
            ) as resp:
                if resp.status != 200:
                    logger.warning("Push notification failed: %s", resp.status)
    except Exception:
        logger.warning("Could not reach server for push notification")
