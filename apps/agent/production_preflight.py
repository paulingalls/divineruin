"""Production startup checks run before LiveKit registration or worker polling."""

import asyncio
import importlib
import logging
import os
from contextlib import nullcontext

import db

logger = logging.getLogger("divineruin.preflight")
DEADLINE = 15
CATALOGS = (
    ("archetypes", "load_archetypes"),
    ("spells", "load_spells"),
    ("racial_resonance", "load_racial_resonance"),
    ("abilities", "load_abilities"),
    ("milestones", "load_milestones"),
    ("mentor_variants", "load_mentor_variants"),
    ("role_archetypes", "load_role_archetypes"),
    ("settlement_templates", "load_settlement_templates"),
    ("npcs", "load_npcs"),
    ("companion_profiles", "load_companion_profiles"),
)


class PreflightError(RuntimeError):
    """Safe startup diagnostic; its cause can contain credentials from a malformed URL."""


def is_production() -> bool:
    return os.getenv("AGENT_ENV", "development") == "production"


def validate_production_env() -> None:
    if not is_production():
        return
    missing = [
        name
        for name in (
            "SERVER_URL",
            "DATABASE_URL",
            "REDIS_URL",
            "INTERNAL_SECRET",
            "ANTHROPIC_API_KEY",
            "INWORLD_API_KEY",
        )
        if not os.getenv(name, "").strip()
    ]
    if missing:
        raise OSError("Missing required production environment variables: " + ", ".join(missing))


async def load_catalogs(command: str, *, require_nonempty: bool = False) -> None:
    catalogs = list(CATALOGS)
    if command == "worker":
        catalogs = [("training_rules", "load_training_activity_types")] + [
            row for row in catalogs if row[0] != "settlement_templates"
        ]
    for name, loader in catalogs:
        try:
            module = importlib.import_module(name)
            async with asyncio.timeout(DEADLINE) if require_nonempty else nullcontext():
                await getattr(module, loader)()
            if require_nonempty:
                loaded = bool(module.TRAINING_ACTIVITY_CONFIG) if name == "training_rules" else module.is_loaded()
                if not loaded:
                    raise ValueError("required catalog is empty")
        except Exception as exc:
            raise PreflightError(f"Content preflight failed: {name}") from exc
    if require_nonempty:
        from _gods_content import load_gods
        from action_sound_content import _load_action_sounds
        from combat_sound_content import _load_combat_sounds

        load_gods()
        _load_combat_sounds()
        _load_action_sounds()
        logger.info("Preflight content validated: %s", command)


async def production_preflight(command: str) -> None:
    try:
        await _production_preflight(command)
    except PreflightError as exc:
        logger.error("%s", exc)
        raise SystemExit(1) from None


async def _production_preflight(command: str) -> None:
    validate_production_env()
    logger.info("Preflight environment validated")
    try:
        try:
            async with asyncio.timeout(DEADLINE):
                pool = await db.get_pool()
                async with pool.acquire() as connection:
                    await connection.fetchval("SELECT 1")
        except Exception as exc:
            raise PreflightError("Postgres preflight failed") from exc
        logger.info("Preflight Postgres query succeeded")
        await load_catalogs(command, require_nonempty=True)
        try:
            async with asyncio.timeout(DEADLINE):
                redis = await db.get_redis()
                await redis.ping()
        except Exception as exc:
            raise PreflightError("Valkey preflight failed") from exc
        logger.info("Preflight Valkey PING succeeded")
    finally:
        try:
            async with asyncio.timeout(DEADLINE):
                await db.close_all()
        except Exception as exc:
            raise PreflightError("Preflight resource cleanup failed") from exc
    logger.info("Preflight resources closed; preflight complete")
