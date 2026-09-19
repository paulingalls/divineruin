import event_types as E
from combat_events import EventSink, emit_or_publish
from combat_sound_content import COMBAT_SOUND_IDS
from session_data import SessionData


class UnknownCombatSoundError(ValueError):
    pass


async def publish_combat_sounds(session: SessionData, sounds: list[str], *, sink: EventSink | None = None) -> None:
    unknown = [sound for sound in sounds if sound not in COMBAT_SOUND_IDS]
    if unknown:
        raise UnknownCombatSoundError(f"unknown combat sound: {unknown[0]}")
    for sound in sounds:
        await emit_or_publish(
            sink,
            session.room,
            E.PLAY_SOUND,
            {"sound_name": sound},
            event_bus=session.event_bus,
        )
