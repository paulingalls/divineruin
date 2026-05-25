"""Tests for the crafting workspace substrate (story-001, M5.2).

Pure deterministic functions — plain args, no DB. WorkspaceType ordering feeds
the three-check pipeline's Check 3 (story-003); rental pricing + settlement
availability mirror the spec (game_mechanics_crafting.md §Workspace Access).
"""

import pytest

import workspace as ws


class TestWorkspaceType:
    def test_all_four_types_present(self):
        names = {w.value for w in ws.WorkspaceType}
        assert names == {"field", "workshop", "forge", "laboratory"}

    def test_recipe_workspace_values_round_trip(self):
        # Recipe.workspace_required uses these exact string values (recipes.py).
        for value in ("field", "workshop", "forge", "laboratory"):
            assert ws.WorkspaceType(value).value == value

    def test_field_is_the_floor(self):
        # Field is always available and ranks below every other workspace.
        field = ws.workspace_rank(ws.WorkspaceType.FIELD)
        assert field < ws.workspace_rank(ws.WorkspaceType.WORKSHOP)
        assert field < ws.workspace_rank(ws.WorkspaceType.FORGE)
        assert field < ws.workspace_rank(ws.WorkspaceType.LABORATORY)

    def test_advanced_workspaces_rank_above_workshop(self):
        # Forge and Laboratory are the advanced (Expert-tier) workspaces; both
        # rank above Workshop, which ranks above Field.
        workshop = ws.workspace_rank(ws.WorkspaceType.WORKSHOP)
        assert ws.workspace_rank(ws.WorkspaceType.FORGE) > workshop
        assert ws.workspace_rank(ws.WorkspaceType.LABORATORY) > workshop

    def test_forge_and_laboratory_are_parallel_not_subsuming(self):
        # Forge and Laboratory are co-equal specializations: a forge cannot brew
        # potions, a lab cannot smith metal. Equal rank documents that neither
        # subsumes the other — Check 3 (story-003) gates on exact-type access,
        # not rank >=.
        assert ws.workspace_rank(ws.WorkspaceType.FORGE) == ws.workspace_rank(ws.WorkspaceType.LABORATORY)

    def test_workspace_type_rejects_unknown_string(self):
        # The fail-loud boundary: downstream code converts a raw DB string
        # (recipe.workspace_required) via WorkspaceType(value); an unknown
        # workspace raises rather than silently mis-gating Check 3.
        with pytest.raises(ValueError):
            ws.WorkspaceType("smithy")
