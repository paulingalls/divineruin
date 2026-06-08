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
    # M9 per-culture martial mentors — one per cultural variant style (story-003). Personas
    # mirror their content/npcs.json entries so the DM voice stays coherent when narrating a
    # variant; without these the variant narration would fall back to guildmaster_torin.
    "mentor_drathian_warleader": {
        "name": "Warleader Hessa Stormhand",
        "personality": "blunt, commanding, fiercely proud of clan honor, privately grieving the warriors she has spent",
        "speech_style": "short declarative commands at a steady carrying volume; thins and slows when she speaks of the dead",
        "voice_id": "drathian_hessa_v1",
    },
    "mentor_keldaran_forgemaster": {
        "name": "Forge-Master Doran Ironvein",
        "personality": "precise, unhurried, pragmatic, finds genuine beauty in efficiency",
        "speech_style": "short level sentences, no wasted word; explains fighting through metalwork, warms only for good craft",
        "voice_id": "keldaran_doran_v1",
    },
    "mentor_thornwarden_elder": {
        "name": "Elder Senna Rootwarden",
        "personality": "patient to stillness, listens more than she speaks, gently immovable when the forest is threatened",
        "speech_style": "long flowing sentences broken by unhurried pauses; disapproval drops to a whisper rather than a shout",
        "voice_id": "thornwarden_senna_v1",
    },
    "mentor_tidecaller_bosun": {
        "name": "Bosun Marek Tideborn",
        "personality": "restless, adaptable, fiercely independent, sees patterns in movement others miss",
        "speech_style": "sentences that flow and wander like a current but reach the point; quickens when danger at sea comes up",
        "voice_id": "tidecaller_marek_v1",
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
    "companion_lira": {
        "name": "Lira",
        "personality": "brilliant, curious, socially cautious, excited by discovery",
        "speech_style": "precise and rapid when discussing findings, halting in casual talk",
        "voice_id": "COMPANION_LIRA",
        "errand_frames": {
            "scout": "Lira surveys the area methodically, pausing to examine anything that glows, hums, or feels wrong.",
            "social": "Lira listens carefully, asking pointed questions that make people reveal more than they intended.",
            "acquire": "Lira checks every vendor for arcane reagents and forgotten texts, ignoring mundane stock entirely.",
            "relationship": "Lira brings a small gift — a pressed flower or a copied passage — and asks earnest questions.",
        },
    },
    "companion_tam": {
        "name": "Tam",
        "personality": "energetic, impulsive, warm-hearted, easily distracted",
        "speech_style": "fast and enthusiastic, jumps between topics, speaks with hands",
        "voice_id": "COMPANION_TAM",
        "errand_frames": {
            "scout": "Tam covers ground fast, climbing anything climbable and poking into places others would avoid.",
            "social": "Tam charms their way into conversations easily, though sometimes says the wrong thing at the wrong time.",
            "acquire": "Tam knows every back trail and hidden grove, but gets lost in cities and comes back with the wrong thing.",
            "relationship": "Tam shows up with food, sits too close, and talks until the other person can't help but laugh.",
        },
    },
    "companion_sable": {
        "name": "Sable",
        "personality": "alert, protective, primal intelligence, distrustful of strangers",
        "speech_style": "communicates through body language, growls, and pointed looks",
        "voice_id": "COMPANION_SABLE",
        "errand_frames": {
            "scout": "Sable moves low through the underbrush, nose to the ground, ears tracking every sound.",
            "acquire": "Sable follows scent trails to find natural materials — herbs, bones, mineral deposits.",
        },
    },
}

# Narration prompt templates per activity type.
# Structure (segments, emotions) is enforced by the tool schema, not the prompt.
NARRATION_PROMPTS = {
    "crafting": """You are {npc_name}, {npc_role} in the world of Divine Ruin.
Personality: {npc_personality}
Speech style: {npc_speech_style}

The player attempted to craft: {recipe_name}
Outcome: {tier} (roll: {roll}, DC: {dc})
{recipe_cue}
{quality_note}

Write a short narration (60-120 words) of this crafting outcome.
Include sensory details — the sound of the hammer, the smell of hot metal, the feel of the work.
End with the decision point the player must make.

Decision options:
{decision_options}

Use DM_NARRATOR for narration and {voice_id} for {npc_name}'s dialogue.
Keep it concise and in-character.""",
    "training": """You are {mentor_name}, training mentor in the world of Divine Ruin.
Personality: {mentor_personality}
Speech style: {mentor_speech_style}

The player trained: {training_stat}{skill_note}
Outcome: {tier} (roll: {roll}, DC: {dc})
Stat gains: {stat_gains}
{cultural_attribution_line}
Write a short narration (60-120 words) of this training session.
Include physical sensory details — sweat, exertion, the moment of clarity or frustration.
End with the decision point.

Decision options:
{decision_options}

Use DM_NARRATOR for narration and {voice_id} for {mentor_name}'s dialogue.
Keep it concise and in-character.""",
    "training_completion": """You are {mentor_name}, training mentor in the world of Divine Ruin.
Personality: {mentor_personality}
Speech style: {mentor_speech_style}

The player completed training: {training_stat}{skill_note}
Outcome tier: {tier} (DC: {dc})
Stat gains: {stat_gains}
{cultural_attribution_line}{replacement_line}
Write a short narration (60-120 words) of the training conclusion.
Include physical sensory details — sweat, exertion, the moment of clarity or frustration.
Describe the outcome: breakthrough means real progress was made, plateau means steady effort with no leap forward.
{advancement_line}
Use DM_NARRATOR for narration and {voice_id} for {mentor_name}'s dialogue.
Keep it concise and in-character.""",
    "companion_errand": """You are narrating {companion_name}'s return from an errand in the world of Divine Ruin.
Companion personality: {companion_personality}
Speech style: {companion_speech_style}
Errand frame: {errand_frame}

Errand type: {errand_type} at {destination}
Outcome: {tier}
Information gained: {information}
{risk_line}
Write a short narration (60-120 words) of {companion_name} returning and reporting.
Include details of what they saw, heard, or found. Stay in character.
End with the decision point.

Decision options:
{decision_options}

Use DM_NARRATOR for narration and {voice_id} for {companion_name}'s dialogue.
Keep it concise and in-character.""",
}


def get_crafting_npc(npc_id: str) -> dict:
    return CRAFTING_NPCS.get(npc_id, CRAFTING_NPCS["grimjaw_blacksmith"])


def get_training_mentor(mentor_id: str) -> dict:
    return TRAINING_MENTORS.get(mentor_id, TRAINING_MENTORS["guildmaster_torin"])


def get_companion_context(companion_id: str) -> dict:
    return COMPANION_CONTEXT.get(companion_id, COMPANION_CONTEXT["companion_kael"])


def _format_recipe_cue(ctx: dict) -> str:
    """Render the per-recipe band cue (narration_cues[band]) for the narration prompt.

    The base sensory description of THIS recipe's outcome at the resolved band (decision
    crafting-narration-ssot), complementary to the per-category quality note. Empty when
    the recipe omits the resolved band (exceptional/partial are optional).
    """
    cue = ctx.get("recipe_cue")
    return f"The result: {cue}" if cue else ""


def _format_cultural_attribution(ctx: dict) -> str:
    """Render the mentor-variant cultural-attribution line for the training narration prompt.

    Present only for mentor-variant training (cultural_attribution in the activity data, M9
    story-003); empty for stat/skill training so those prompts are byte-unchanged. Tells the DM
    to voice the technique's cultural lineage when narrating the variant (AC4).
    """
    attribution = ctx.get("cultural_attribution")
    return f"This technique is a {attribution} — let its cultural lineage colour the telling.\n" if attribution else ""


def _format_replacement_notice(ctx: dict) -> str:
    """Render the variant-replacement line for the training-completion prompt.

    Present only when a newly-trained variant supplants a prior active variant on the same
    technique (concern 25b663d3e245); empty otherwise. Tells the DM to voice the swap so the
    player learns their form changed — audio-first, never a silent state change.
    """
    replaced = ctx.get("replaced_cultural_attribution")
    return (
        f"This new form supplants the {replaced} they had been practising — make the shift felt.\n" if replaced else ""
    )


def _format_quality_note(ctx: dict) -> str:
    """Render the M5.3 crafting quality property for the narration prompt.

    Exceptional rolls carry a bonus_property, Partial rolls a flaw (both narration-only
    {id,name,description} from quality_outcomes); Success/Failure carry neither. Returns a
    sensory cue line for the DM to weave in, or "" when there's nothing to surface.
    """
    bonus = ctx.get("bonus_property")
    if bonus:
        return f"Exceptional touch — {bonus['name']}: {bonus['description']}"
    flaw = ctx.get("flaw")
    if flaw:
        return f"A flaw mars it — {flaw['name']}: {flaw['description']}"
    return ""


def build_narration_prompt(activity_type: str, outcome: dict) -> tuple[str, list[str]]:
    """Build a narration prompt and return (prompt, npc_voice_ids).

    The voice IDs are used to constrain the tool schema's character enum.
    """
    template = NARRATION_PROMPTS[activity_type]
    ctx = outcome.get("narrative_context", {})
    decisions = outcome.get("decision_options", [])
    decision_text = "\n".join(f"- {d['label']}" for d in decisions)

    if activity_type == "crafting":
        npc = get_crafting_npc(ctx.get("npc_id", "grimjaw_blacksmith"))
        prompt = template.format(
            npc_name=npc["name"],
            npc_role=npc["role"],
            npc_personality=npc["personality"],
            npc_speech_style=npc["speech_style"],
            voice_id=npc["voice_id"],
            recipe_name=ctx.get("recipe_name", "unknown item"),
            tier=ctx.get("tier", "unknown"),
            roll=ctx.get("roll", "?"),
            dc=ctx.get("dc", "?"),
            recipe_cue=_format_recipe_cue(ctx),
            quality_note=_format_quality_note(ctx),
            decision_options=decision_text,
        )
        return prompt, [npc["voice_id"]]

    elif activity_type in ("training", "training_completion"):
        mentor = get_training_mentor(ctx.get("mentor_id", "guildmaster_torin"))
        skill_note = f" (skill: {ctx['training_skill']})" if ctx.get("training_skill") else ""
        format_args: dict = {
            "mentor_name": mentor["name"],
            "mentor_personality": mentor["personality"],
            "mentor_speech_style": mentor["speech_style"],
            "voice_id": mentor["voice_id"],
            "training_stat": ctx.get("training_stat", "unknown"),
            "skill_note": skill_note,
            "tier": ctx.get("tier", "unknown"),
            "stat_gains": outcome.get("stat_gains", {}),
            "dc": ctx.get("dc", "?"),
            "cultural_attribution_line": _format_cultural_attribution(ctx),
            "replacement_line": _format_replacement_notice(ctx),
        }
        if activity_type == "training":
            format_args["roll"] = ctx.get("roll", "?")
            format_args["decision_options"] = decision_text
        else:
            stat_gains = outcome.get("stat_gains", {})
            if stat_gains.get("skill_advanced"):
                format_args["advancement_line"] = (
                    f"The player's skill advanced to {stat_gains['new_tier']}! Make this feel momentous.\n"
                )
            else:
                format_args["advancement_line"] = ""
        prompt = template.format(**format_args)
        return prompt, [mentor["voice_id"]]

    else:  # companion_errand
        companion = get_companion_context(ctx.get("companion_id", "companion_kael"))
        errand_type = ctx.get("errand_type", "scout")
        errand_frame = companion.get("errand_frames", {}).get(errand_type, "")
        risk = ctx.get("risk_outcome", "none")
        risk_line = "Companion was injured during the errand.\n" if risk == "injured" else ""
        if risk == "emergency":
            risk_line = "Companion ran into serious trouble and needs rescue.\n"
        prompt = template.format(
            companion_name=companion["name"],
            companion_personality=companion["personality"],
            companion_speech_style=companion["speech_style"],
            voice_id=companion["voice_id"],
            errand_frame=errand_frame,
            errand_type=errand_type,
            destination=ctx.get("destination", "unknown"),
            tier=ctx.get("tier", "unknown"),
            information=outcome.get("information_gained", []),
            risk_line=risk_line,
            decision_options=decision_text,
        )
        return prompt, [companion["voice_id"]]
