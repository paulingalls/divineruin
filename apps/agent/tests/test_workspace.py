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


class TestRentalPricing:
    def test_base_prices_match_spec(self):
        # Spec §Workspace Access rental table: per calendar day, in silver.
        assert ws.RENTAL_BASE_PRICE_SP[ws.WorkspaceType.WORKSHOP] == 2
        assert ws.RENTAL_BASE_PRICE_SP[ws.WorkspaceType.FORGE] == 5
        assert ws.RENTAL_BASE_PRICE_SP[ws.WorkspaceType.LABORATORY] == 10
        assert ws.COMBINED_FORGE_LAB_RENTAL_SP == 12

    def test_field_has_no_rental_price(self):
        # Field is free and always available — never rented.
        assert ws.WorkspaceType.FIELD not in ws.RENTAL_BASE_PRICE_SP

    def test_neutral_pays_full_price(self):
        quote = ws.compute_rental_price(5, "neutral")
        assert quote.available is True
        assert quote.price_sp == pytest.approx(5.0)
        assert quote.reason == ""

    def test_friendly_pays_80_percent(self):
        quote = ws.compute_rental_price(5, "friendly")
        assert quote.available is True
        assert quote.price_sp == pytest.approx(4.0)

    def test_trusted_pays_60_percent(self):
        # 12sp combined bundle at Trusted: 12 * 0.6 = 7.2.
        quote = ws.compute_rental_price(ws.COMBINED_FORGE_LAB_RENTAL_SP, "trusted")
        assert quote.available is True
        assert quote.price_sp == pytest.approx(7.2)

    def test_cautious_alias_pays_full_price(self):
        # 'cautious' is a neutral alias (tool_support.DISPOSITION_TIERS).
        quote = ws.compute_rental_price(10, "cautious")
        assert quote.available is True
        assert quote.price_sp == pytest.approx(10.0)

    @pytest.mark.parametrize("disposition", ["wary", "hostile"])
    def test_below_neutral_refuses_no_surcharge(self, disposition):
        # Adopt spec: below Neutral the NPC refuses outright — no rental, no
        # surcharge (not the milestone's hostile-surcharge wording).
        quote = ws.compute_rental_price(5, disposition)
        assert quote.available is False
        assert quote.price_sp == 0.0
        assert quote.reason  # explains the refusal

    def test_case_insensitive_disposition(self):
        assert ws.compute_rental_price(5, "FRIENDLY").price_sp == pytest.approx(4.0)

    def test_unknown_disposition_fails_loud(self):
        with pytest.raises(ValueError):
            ws.compute_rental_price(5, "ecstatic")
