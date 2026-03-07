"""Push notification helper — sends via the server's internal push endpoint."""

import logging
import os

logger = logging.getLogger("divineruin.push")


async def send_push_notification(player_id: str, title: str, body: str) -> None:
    """Send push notification via the server's push endpoint."""
    import aiohttp

    server_url = os.environ.get("SERVER_URL", "http://localhost:3001")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{server_url}/api/internal/push",
                json={"player_id": player_id, "title": title, "body": body},
                headers={"X-Internal-Secret": os.environ.get("INTERNAL_SECRET", "")},
            ) as resp:
                if resp.status != 200:
                    logger.warning("Push notification failed: %s", resp.status)
    except Exception:
        logger.warning("Could not reach server for push notification")
