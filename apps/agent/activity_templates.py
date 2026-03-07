"""NPC personalities and context data for async activity narration prompts."""

# Crafting NPCs
CRAFTING_NPCS = {
    "grimjaw_blacksmith": {
        "name": "Grimjaw",
        "role": "blacksmith",
        "personality": "gruff, perfectionist, secretly proud of students who show promise",
        "speech_style": "short grunts, metaphors about metal and fire, calls mistakes 'offenses to the forge'",
        "voice_id": "GRIMJAW_BLACKSMITH",
    },
}

# Training mentors
TRAINING_MENTORS = {
    "guildmaster_torin": {
        "name": "Guildmaster Torin",
        "personality": "pragmatic, decisive, privately exhausted",
        "speech_style": "direct, wastes no words, occasional dry humor, calls everyone 'recruit'",
        "voice_id": "GUILDMASTER_TORIN",
    },
    "scholar_emris": {
        "name": "Emris of the Diaspora",
        "personality": "brilliant, socially awkward, haunted by Aelindra's fall",
        "speech_style": "rapid and precise when discussing scholarship, halting in casual conversation",
        "voice_id": "SCHOLAR_EMRIS",
    },
}

# Companion errand context
COMPANION_CONTEXT = {
    "companion_kael": {
        "name": "Kael",
        "personality": "steady, practical, quietly haunted, dry humor when relaxed",
        "speech_style": "measured and deliberate, short sentences when tense, warmer when relaxed",
        "voice_id": "COMPANION_KAEL",
        "errand_frames": {
            "scout": "Kael moves through the area with the quiet efficiency of a former caravan guard, eyes tracking every shadow.",
            "social": "Kael settles into a corner, listening more than talking, picking up threads of conversation.",
            "acquire": "Kael browses the stalls with a practiced eye, weighing value against need.",
            "relationship": "Kael takes the time to simply be present, sharing stories over a drink.",
        },
    },
}

# Narration prompt templates per activity type
NARRATION_PROMPTS = {
    "crafting": """You are {npc_name}, {npc_role} in the world of Divine Ruin.
Personality: {npc_personality}
Speech style: {npc_speech_style}

The player attempted to craft: {recipe_name}
Outcome: {tier} (roll: {roll}, DC: {dc})
Quality bonus: {quality_bonus}

Write a short narration (60-120 words) of this crafting outcome, speaking as {npc_name}.
Include sensory details — the sound of the hammer, the smell of hot metal, the feel of the work.
End with the decision point the player must make.

Decision options:
{decision_options}

Use dialogue tags for voice routing: [NPC:{npc_name}] before NPC speech, [NARRATOR] before narration.
Keep it concise and in-character.""",
    "training": """You are {mentor_name}, training mentor in the world of Divine Ruin.
Personality: {mentor_personality}
Speech style: {mentor_speech_style}

The player trained: {training_stat}{skill_note}
Outcome: {tier} (roll: {roll}, DC: {dc})
Stat gains: {stat_gains}

Write a short narration (60-120 words) of this training session, speaking as {mentor_name}.
Include physical sensory details — sweat, exertion, the moment of clarity or frustration.
End with the decision point.

Decision options:
{decision_options}

Use dialogue tags: [NPC:{mentor_name}] before mentor speech, [NARRATOR] before narration.
Keep it concise and in-character.""",
    "companion_errand": """You are narrating {companion_name}'s return from an errand in the world of Divine Ruin.
Companion personality: {companion_personality}
Speech style: {companion_speech_style}
Errand frame: {errand_frame}

Errand type: {errand_type} at {destination}
Outcome: {tier}
Information gained: {information}

Write a short narration (60-120 words) of {companion_name} returning and reporting.
Include details of what they saw, heard, or found. Stay in character.
End with the decision point.

Decision options:
{decision_options}

Use dialogue tags: [NPC:{companion_name}] before companion speech, [NARRATOR] before narration.
Keep it concise and in-character.""",
}


def get_crafting_npc(npc_id: str) -> dict:
    return CRAFTING_NPCS.get(npc_id, CRAFTING_NPCS["grimjaw_blacksmith"])


def get_training_mentor(mentor_id: str) -> dict:
    return TRAINING_MENTORS.get(mentor_id, TRAINING_MENTORS["guildmaster_torin"])


def get_companion_context(companion_id: str) -> dict:
    return COMPANION_CONTEXT.get(companion_id, COMPANION_CONTEXT["companion_kael"])


def build_narration_prompt(activity_type: str, outcome: dict, activity_data: dict) -> str:
    """Build a narration prompt from outcome and activity data."""
    template = NARRATION_PROMPTS[activity_type]
    ctx = outcome.get("narrative_context", {})
    decisions = outcome.get("decision_options", [])
    decision_text = "\n".join(f"- {d['label']}" for d in decisions)

    if activity_type == "crafting":
        npc = get_crafting_npc(ctx.get("npc_id", "grimjaw_blacksmith"))
        return template.format(
            npc_name=npc["name"],
            npc_role=npc["role"],
            npc_personality=npc["personality"],
            npc_speech_style=npc["speech_style"],
            recipe_name=ctx.get("recipe_name", "unknown item"),
            tier=ctx.get("tier", "unknown"),
            roll=ctx.get("roll", "?"),
            dc=ctx.get("dc", "?"),
            quality_bonus=ctx.get("quality_bonus", 0),
            decision_options=decision_text,
        )
    elif activity_type == "training":
        mentor = get_training_mentor(ctx.get("mentor_id", "guildmaster_torin"))
        skill_note = f" (skill: {ctx['training_skill']})" if ctx.get("training_skill") else ""
        return template.format(
            mentor_name=mentor["name"],
            mentor_personality=mentor["personality"],
            mentor_speech_style=mentor["speech_style"],
            training_stat=ctx.get("training_stat", "unknown"),
            skill_note=skill_note,
            tier=ctx.get("tier", "unknown"),
            roll=ctx.get("roll", "?"),
            dc=ctx.get("dc", "?"),
            stat_gains=outcome.get("stat_gains", {}),
            decision_options=decision_text,
        )
    else:  # companion_errand
        companion = get_companion_context(ctx.get("companion_id", "companion_kael"))
        errand_type = ctx.get("errand_type", "scout")
        errand_frame = companion.get("errand_frames", {}).get(errand_type, "")
        return template.format(
            companion_name=companion["name"],
            companion_personality=companion["personality"],
            companion_speech_style=companion["speech_style"],
            errand_frame=errand_frame,
            errand_type=errand_type,
            destination=ctx.get("destination", "unknown"),
            tier=ctx.get("tier", "unknown"),
            information=outcome.get("information_gained", []),
            decision_options=decision_text,
        )
