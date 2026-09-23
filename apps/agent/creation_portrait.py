"""Background portrait generation for a newly created player."""

import logging
import os

import db_mutations
import event_types as E
from asset_utils import slug_asset_url
from creation_classes import CLASSES
from creation_races import RACES
from game_events import publish_game_event
from session_data import SessionData

logger = logging.getLogger("divineruin.creation")
SERVER_URL = os.environ.get("SERVER_URL", "http://localhost:3001")


async def generate_player_portrait(sd: SessionData, cs: object) -> None:
    """Async fire-and-forget: generate player portrait via server API."""
    try:
        import httpx

        race_id = getattr(cs, "race", None)
        class_id = getattr(cs, "class_choice", None)
        class_data = CLASSES.get(class_id) if class_id else None
        class_name = class_data.name if class_data else "Adventurer"
        class_fantasy = class_data.card_description if class_data else "A versatile wanderer."
        race_data = RACES.get(race_id) if race_id else None
        race_name = race_data.name if race_data else "Human"
        physical_features = race_data.card_description if race_data else "Adaptable and determined."

        template_vars = {
            "class": class_name,
            "class_fantasy": class_fantasy,
            "race_name": race_name,
            "physical_features": physical_features,
        }

        internal_secret = os.environ.get("INTERNAL_SECRET", "")
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{SERVER_URL}/api/images/generate",
                json={"templateId": "player_character_creation", "vars": template_vars},
                headers={"X-Internal-Secret": internal_secret},
            )
            if resp.status_code != 200:
                logger.warning("Portrait generation failed: %s", resp.text)
                return

            result = resp.json()
            asset_id = result.get("assetId", "")
            if not asset_id:
                return

            portrait_url = slug_asset_url(asset_id)

            # Update player record
            await db_mutations.update_player_portrait(sd.player_id, portrait_url)

            # Notify client
            await publish_game_event(
                sd.room,
                E.PLAYER_PORTRAIT_READY,
                {"url": portrait_url},
                sd.event_bus,
            )
            logger.info("Player portrait generated: %s", portrait_url)
    except Exception:
        logger.exception("Failed to generate player portrait")
