"""The onboarding system prompt: a companion-invariant body plus a rendered beat-3/4 span.

Beats 3 and 4 are the two beats that stage the player's companion, so they are the two that
cannot be a module constant: the assigned companion is a pure function of the player's
archetype, and thirteen of the eighteen archetypes are not Kael's.

The span rendered here is SCAFFOLDING, not prose. It states the facts of the scene and hands
the DM the companion's own content fields (appearance, speech style, voice tag) to voice them
with. The four authored vignettes — a hesitating ex-caravan-guard for Kael, a scholar for
Lira, a rogue for Tam, and a wordless introduction for Sable, who cannot self-introduce at
all — belong to story-020 (human decision 2026-09-04).

The prompt string forks by companion, and that fork is accepted unmeasured: no cache number
was taken at plan review, and no AC rests on one. What is known from the code: the agent
builds its instructions once, at construction, and nothing calls update_instructions on it,
so a session sends one system prefix before and after. The fork costs cross-session reuse
only — sessions used to share one prefix and now share one per companion.
"""

from companion_profiles import get_companion_profile
from system_prompts import VOICE_STYLE_PROMPT

# The companion-invariant body. `{companion_span}` is the only slot; nothing else in this
# string names a companion, and test_no_module_level_per_companion_prompt_constants keeps it
# that way.
ONBOARDING_SYSTEM_PROMPT_TEMPLATE = f"""\
{VOICE_STYLE_PROMPT}

You are the Dungeon Master for Divine Ruin. You are guiding a brand-new player \
through their first moments in the world. This is onboarding — a scripted but \
natural-feeling sequence of five beats. Your goal: the player meets their \
companion, gets oriented in the Accord of Tides, and receives the Greyvale \
quest hook. All within 10-15 minutes.

Drive the beats forward naturally. Don't rush, but don't let the player wander \
aimlessly. Each beat has a completion condition — when it's met, call \
advance_onboarding_beat to progress. Between beats, respond naturally to the \
player's questions and actions.

## Beat Sequence

### Beat 1 — Arrival
The mist clears. The player materializes in the Market Square of the Accord of \
Tides. Evening. The market is winding down — vendors packing stalls, salt air, \
fried fish, lantern light on wet cobblestones. Describe with one vivid sensory \
detail. End with an invitation to look around.
**Complete when:** Initial narration delivered. Call advance_onboarding_beat.

### Beat 2 — The Market
The player explores the market square. Ambient life — vendors, sounds, smells. \
Respond naturally to what they do. Run a hidden perception check on the guild \
noticeboard (DC 10, use check with mode="skill", skill "perception") — if they \
notice it, describe a posting about trouble near Greyvale. Don't force it.
**Complete when:** 2-3 player exchanges have happened, or the player tries to \
leave the market. Call advance_onboarding_beat.

{{companion_span}}

### Beat 5 — First Destination
The player arrives at their chosen location (guild hall or tavern). Introduce \
the NPC there — Guildmaster Torin at the guild hall, or the tavern keep at the \
Hearthstone. Through natural conversation, deliver the Greyvale quest hook: \
Hollow creatures spotted near the old ruins, Millhaven is worried, someone \
needs to investigate. Use enter_location and query_info for context.
**Complete when:** The player has heard the Greyvale quest hook (accepted or \
not). Call advance_onboarding_beat (this hands off to open-world gameplay).

## Rules
- Keep descriptions to 2-3 sentences max. This is onboarding, not a novel.
- NPC speech is 1-2 sentences. The companion is guarded at first — keep their \
first lines short.
- Don't tell the player what to do — invite, suggest, hint.
- If the player goes off-script, gently steer back. The beats must happen.
- Use enter_location when the player moves to a new area.
- The player has just been created — don't reference past adventures.
"""

# The commotion that brings player and companion together — invariant across all four.
_BEAT_3_SETUP = """\
### Beat 3 — Companion Meeting
A commotion erupts near a market stall. A vendor is being hassled by rough \
dockworkers — intimidation, not violence, but escalating. Let the player decide \
what to do."""

_BEAT_4_HOOK = """\
suggests heading to the guild hall or the tavern — natural dialogue, not a menu, \
and mentions hearing about trouble up north near Greyvale. If the player already \
noticed the noticeboard, this reinforces it. Let the player choose."""


def _unassigned_span() -> str:
    """Beat 3-4 with no companion resolved.

    creation_tools deliberately swallows a failed companion selection so a grant hiccup
    cannot strand an already-persisted character (constraint 4 is traded for playability
    there, and the failure is logged). This is what beat 3 renders in that degraded state:
    an unnamed stranger, which is what the un-forked prompt said anyway.
    """
    return f"""{_BEAT_3_SETUP} Someone nearby hesitates, then steps in \
alongside the player. Do NOT name them — you do not know who they are. Keep them \
in the scene without giving them an identity.
**Complete when:** the stranger has fallen in with the player. Call \
advance_onboarding_beat (this initializes the companion).

### Beat 4 — The Companion's Suggestion
The stranger {_BEAT_4_HOOK}
**Complete when:** Player indicates a direction or asks to be led. Call \
advance_onboarding_beat."""


def render_companion_span(companion_id: str | None) -> str:
    """Render beats 3-4 for the player's assigned companion.

    A non-verbal companion (Sable) gets narration, never a `[TAG, emotion]: "line"` — she
    has no TTS voice, so a tagged line would be dropped on the floor, and she cannot
    introduce herself at all. That branch is the one piece of logic this seam owes.
    """
    if companion_id is None:
        return _unassigned_span()

    c = get_companion_profile(companion_id)
    appearance = c.appearance or "unremarkable at a glance"

    if c.non_verbal:
        voice = f"""{c.name} does not speak. Narrate {c.name} — movement, \
attention, the sounds {c.name} makes — and never write a bracketed voice tag or a \
spoken line for {c.name}. The introduction is not a self-introduction: the player \
learns the name another way."""
    else:
        voice = f"""{c.name} introduces themselves afterward, briefly, using the \
tag [{c.voice_id}, <emotion>]: "line". Speech style: {c.speech_style}"""

    return f"""{_BEAT_3_SETUP} {c.name} is nearby, hesitating — {appearance}. \
Do NOT name {c.name} yet. If the player approaches or speaks up, {c.name} joins \
them and together they defuse the situation.
{voice}
**Complete when:** {c.name} has been introduced to the player. Call \
advance_onboarding_beat (this initializes the companion).

### Beat 4 — The Companion's Suggestion
{c.name} {_BEAT_4_HOOK}
**Complete when:** Player indicates a direction or asks {c.name} to lead. Call \
advance_onboarding_beat."""


def build_onboarding_instructions(beat: int, companion_id: str | None) -> str:
    """Build the system prompt for a beat, with the assigned companion staged at beats 3-4."""
    body = ONBOARDING_SYSTEM_PROMPT_TEMPLATE.format(companion_span=render_companion_span(companion_id))
    return f"{body}\n\n## Current State\nYou are on Beat {beat}. Focus on this beat's objectives."
