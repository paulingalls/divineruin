from system_prompts import build_system_prompt


def _onboarding_prompt_surface() -> str:
    """The whole onboarding prompt surface a prompt-tool-drift scan must cover.

    story-013 split the prompt into an invariant body plus a beat-3/4 span rendered per
    assigned companion, so scanning one constant no longer sees the whole thing: an
    instruction to call a removed tool could hide in a span the scan never rendered. Union
    all five renderings (four companions + the unresolved case).
    """
    from onboarding_prompt import build_onboarding_instructions

    companions = ("companion_kael", "companion_lira", "companion_tam", "companion_sable", None)
    return "\n".join(build_onboarding_instructions(3, cid) for cid in companions)


def _companion_prompt_surfaces() -> dict[str, str]:
    """The per-companion span of the exploration prompt, one rendering per companion.

    `build_system_prompt(location)` omits it unless a companion is present, so a scan of
    that one call sees none of it — and it is where the DM is told which companion id
    begin_activity accepts.
    """
    from companion_prompts import build_companion_prompt

    companions = ("companion_kael", "companion_lira", "companion_tam", "companion_sable")
    return {f"companion:{cid}": build_companion_prompt(cid, 5) for cid in companions}


def _registered_tool_descriptions() -> dict[str, str]:
    """Every registered tool's description, per agent, joined into one blob.

    Tool docstrings are the OTHER half of the surface the LLM reads to decide what to call — the
    system prompts are not the whole of it. A fold that removes a verb has to clear both, and a
    prompt-only guard reports a fold as verified while the docstrings still cue the dead tool.
    """
    from blacksmith_agent import BLACKSMITH_TOOLS
    from combat_agent import COMBAT_AGENT_TOOLS
    from creation_agent import CREATION_TOOLS
    from dispatch_agent import DISPATCH_TOOLS
    from exploration_agent import EXPLORATION_TOOLS
    from onboarding_agent import ONBOARDING_TOOLS

    toolsets = {
        "exploration tools": EXPLORATION_TOOLS,
        "combat tools": COMBAT_AGENT_TOOLS,
        "dispatch tools": DISPATCH_TOOLS,
        "blacksmith tools": BLACKSMITH_TOOLS,
        "creation tools": CREATION_TOOLS,
        "onboarding tools": ONBOARDING_TOOLS,
    }
    descriptions = {name: "\n".join(t.info.description or "" for t in tools) for name, tools in toolsets.items()}
    for name, blob in descriptions.items():
        assert blob.strip(), f"{name} exposed no tool descriptions — the guard below would be vacuous"
    return descriptions


class TestPromptToolConsistency:
    def test_query_info_consolidation_consistency(self):
        from combat_agent import COMBAT_AGENT_TOOLS
        from dispatch_agent import DISPATCH_TOOLS
        from exploration_agent import EXPLORATION_TOOLS
        from mode_prompts import DISPATCH_SYSTEM_PROMPT
        from mode_tools import enter_mode
        from onboarding_agent import ONBOARDING_TOOLS
        from query_tools import query_info
        from system_prompts import COMBAT_SYSTEM_PROMPT

        agents = {
            "exploration": (build_system_prompt("loc"), EXPLORATION_TOOLS),
            "combat": (COMBAT_SYSTEM_PROMPT, COMBAT_AGENT_TOOLS),
            "training": (DISPATCH_SYSTEM_PROMPT, DISPATCH_TOOLS),
            "onboarding": (_onboarding_prompt_surface(), ONBOARDING_TOOLS),
        }
        for name, (prompt, tools) in agents.items():
            if "query_info" in prompt:
                assert query_info in tools, f"{name} prompt names query_info but lacks the tool"
            for removed in ("query_location", "query_npc", "query_lore", "query_inventory"):
                assert removed not in prompt, f"{name} prompt still names removed tool {removed}"
            assert ("enter_mode" in prompt) == (enter_mode in tools), (
                f"{name}: prompt names enter_mode but tool-holding differs"
            )

    def test_activity_fold_consistency(self):
        from activity_tools import begin_activity, resolve_activity
        from dispatch_agent import DISPATCH_TOOLS
        from mode_prompts import DISPATCH_SYSTEM_PROMPT

        removed_activity_tools = (
            "query_training_programs",
            "initiate_training_cycle",
            "resolve_training_midpoint",
            "dispatch_companion_errand",
            "resolve_companion_errand",
            "query_recipe_requirements",
            "query_available_workspaces",
            "rent_workspace",
            "start_crafting_project",
            "experiment_with_materials",
        )
        for removed in removed_activity_tools:
            assert removed not in DISPATCH_SYSTEM_PROMPT, f"dispatch prompt still names removed tool {removed}"
        assert ("begin_activity" in DISPATCH_SYSTEM_PROMPT) == (begin_activity in DISPATCH_TOOLS)
        assert ("resolve_activity" in DISPATCH_SYSTEM_PROMPT) == (resolve_activity in DISPATCH_TOOLS)

    def test_dispatch_narrates_all_begin_activity_kinds(self):
        """Derive declaration kinds from the registered variants."""
        import typing

        from activity_payloads import ACTIVITY_VARIANTS
        from mode_prompts import DISPATCH_SYSTEM_PROMPT

        kinds = tuple(typing.get_args(v.model_fields["kind"].annotation)[0] for v in ACTIVITY_VARIANTS)
        # Guard the reflection itself: if the Literal ever stops resolving (e.g. the param
        # becomes `str`), kinds would be () and the loop below would pass vacuously.
        assert len(kinds) >= 5, f"reflection returned too few begin_activity kinds ({kinds}) — guard would be vacuous"
        for kind in kinds:
            assert kind in DISPATCH_SYSTEM_PROMPT, f"dispatch prompt omits begin_activity kind {kind!r}"

    def test_audio_tool_fold_consistency(self):
        from mode_prompts import DISPATCH_SYSTEM_PROMPT
        from system_prompts import COMBAT_SYSTEM_PROMPT

        prompts = {
            "exploration": build_system_prompt("loc"),
            "combat": COMBAT_SYSTEM_PROMPT,
            "training": DISPATCH_SYSTEM_PROMPT,
            "onboarding": _onboarding_prompt_surface(),
        }
        for name, prompt in prompts.items():
            for removed in ("play_sound", "set_music_state"):
                assert removed not in prompt, f"{name} prompt still names removed tool {removed}"

    def test_reward_tool_fold_consistency(self):
        """Tool descriptions are an LLM-facing surface, so inspect the actual installed tools."""
        from mode_prompts import DISPATCH_SYSTEM_PROMPT
        from system_prompts import COMBAT_SYSTEM_PROMPT

        prompts = {
            "exploration": build_system_prompt("loc"),
            "combat": COMBAT_SYSTEM_PROMPT,
            "training": DISPATCH_SYSTEM_PROMPT,
            "onboarding": _onboarding_prompt_surface(),
        }
        for name, prompt in prompts.items():
            for removed in ("award_xp", "award_divine_favor"):
                assert removed not in prompt, f"{name} prompt still names removed tool {removed}"

        for agent_name, docstring in _registered_tool_descriptions().items():
            for removed in ("award_xp", "award_divine_favor"):
                assert removed not in docstring, f"{agent_name} still names removed tool {removed}"

    def test_no_surface_teaches_a_reshaped_verb_a_dead_parameter_shape(self):
        """A live tool name can still carry a dead parameter shape."""
        from mode_prompts import DISPATCH_SYSTEM_PROMPT
        from system_prompts import COMBAT_SYSTEM_PROMPT
        from warm_prompts import REGION_REGISTER

        # The old call shape, verbatim. `mode=` is still the INTERNAL router's parameter
        # (_check_impl), so these are the LLM-facing spellings only.
        dead_shapes = ("check(mode", "check with mode", "begin_activity(kind=", '{"type": "')
        surfaces = {
            "exploration": build_system_prompt("loc"),
            "combat": COMBAT_SYSTEM_PROMPT,
            "training": DISPATCH_SYSTEM_PROMPT,
            "onboarding": _onboarding_prompt_surface(),
            **{f"region_register:{region}": text for region, text in REGION_REGISTER.items()},
            **_companion_prompt_surfaces(),
            **_registered_tool_descriptions(),
        }
        # The warm-layer register is a fifth LLM-facing surface the other guards in this class
        # do not scan, and it carried one of the stale `check with mode="save"` instructions.
        assert any(k.startswith("region_register:") for k in surfaces), "REGION_REGISTER scan went vacuous"
        assert any(k.startswith("companion:") for k in surfaces), "companion-span scan went vacuous"
        for name, text in surfaces.items():
            for dead in dead_shapes:
                assert dead not in text, f"{name} still teaches the pre-ADR-0008 shape {dead!r}"

    def test_combat_prompt_teaches_every_empty_string_sentinel_field(self):
        """Vendor required-string fields need an explicit empty sentinel for absence."""
        from declaration_payloads import DECL_VARIANTS
        from system_prompts import COMBAT_SYSTEM_PROMPT

        sentinels = sorted(
            {
                name
                for variant in DECL_VARIANTS
                for name, field in variant.model_fields.items()
                if "empty string" in (field.description or "").lower()
            }
        )
        assert sentinels, "no ''-means-none variant field found — the guard would be vacuous"
        for name in sentinels:
            assert name in COMBAT_SYSTEM_PROMPT, f"combat prompt never names the ''-sentinel field {name!r}"
        assert "empty string" in COMBAT_SYSTEM_PROMPT.lower(), (
            "combat prompt names the sentinel fields but never teaches the '' convention"
        )

    def test_combat_prompt_names_consume_legendary_action(self):
        from combat_agent import COMBAT_AGENT_TOOLS
        from combat_turn import consume_legendary_action
        from system_prompts import COMBAT_SYSTEM_PROMPT

        assert "consume_legendary_action" in COMBAT_SYSTEM_PROMPT
        assert consume_legendary_action in COMBAT_AGENT_TOOLS
