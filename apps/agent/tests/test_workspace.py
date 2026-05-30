"""Tests for the crafting workspace substrate (story-001, M5.2).

Pure deterministic functions — plain args, no DB. WorkspaceType ordering feeds
the three-check pipeline's Check 3 (story-003); rental pricing + settlement
availability mirror the spec (game_mechanics_crafting.md §Workspace Access).
"""

import pytest

import workspace as ws

# Disposition multipliers from the pricing SSOT (content/pricing.json economy row),
# injected into compute_rental_price so it stays a pure rules-engine fn (story-011).
_MULT = {"friendly": 0.8, "trusted": 0.6}


class TestWorkspaceType:
    def test_all_four_types_present(self):
        names = {w.value for w in ws.WorkspaceType}
        assert names == {"field", "workshop", "forge", "laboratory"}

    def test_recipe_workspace_values_round_trip(self):
        # Recipe.workspace_required uses these exact string values (recipes.py).
        for value in ("field", "workshop", "forge", "laboratory"):
            assert ws.WorkspaceType(value).value == value

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
        quote = ws.compute_rental_price(5, "neutral", multipliers=_MULT)
        assert quote.available is True
        assert quote.price_sp == pytest.approx(5.0)
        assert quote.reason == ""

    def test_friendly_pays_80_percent(self):
        quote = ws.compute_rental_price(5, "friendly", multipliers=_MULT)
        assert quote.available is True
        assert quote.price_sp == pytest.approx(4.0)

    def test_trusted_pays_60_percent(self):
        # 12sp combined bundle at Trusted: 12 * 0.6 = 7.2.
        quote = ws.compute_rental_price(ws.COMBINED_FORGE_LAB_RENTAL_SP, "trusted", multipliers=_MULT)
        assert quote.available is True
        assert quote.price_sp == pytest.approx(7.2)

    def test_cautious_alias_pays_full_price(self):
        # 'cautious' is a neutral alias (tool_support.DISPOSITION_TIERS).
        quote = ws.compute_rental_price(10, "cautious", multipliers=_MULT)
        assert quote.available is True
        assert quote.price_sp == pytest.approx(10.0)

    @pytest.mark.parametrize("disposition", ["wary", "hostile"])
    def test_below_neutral_refuses_no_surcharge(self, disposition):
        # Adopt spec: below Neutral the NPC refuses outright — no rental, no
        # surcharge (not the milestone's hostile-surcharge wording).
        quote = ws.compute_rental_price(5, disposition, multipliers=_MULT)
        assert quote.available is False
        assert quote.price_sp == 0.0
        assert quote.reason  # explains the refusal

    def test_case_insensitive_disposition(self):
        assert ws.compute_rental_price(5, "FRIENDLY", multipliers=_MULT).price_sp == pytest.approx(4.0)

    def test_unknown_disposition_fails_loud(self):
        with pytest.raises(ValueError):
            ws.compute_rental_price(5, "ecstatic", multipliers=_MULT)


class TestSettlementAvailability:
    def test_availability_levels_are_ordered(self):
        assert (
            ws.Availability.NEVER
            < ws.Availability.RARELY
            < ws.Availability.SOMETIMES
            < ws.Availability.USUALLY
            < ws.Availability.ALWAYS
        )

    def test_all_five_settlement_sizes_present(self):
        assert {s.value for s in ws.SettlementSize} == {
            "hamlet",
            "village",
            "town",
            "city",
            "keldaran_hold",
        }

    @pytest.mark.parametrize("size", list(ws.SettlementSize))
    def test_field_always_available_everywhere(self, size):
        # Field is the universal floor — every settlement, always.
        assert ws.settlement_workspace_availability(size, ws.WorkspaceType.FIELD) == ws.Availability.ALWAYS

    def test_hamlet_has_no_forge_or_laboratory(self):
        A = ws.Availability
        assert ws.settlement_workspace_availability(ws.SettlementSize.HAMLET, ws.WorkspaceType.WORKSHOP) == A.SOMETIMES
        assert ws.settlement_workspace_availability(ws.SettlementSize.HAMLET, ws.WorkspaceType.FORGE) == A.NEVER
        assert ws.settlement_workspace_availability(ws.SettlementSize.HAMLET, ws.WorkspaceType.LABORATORY) == A.NEVER

    def test_village_matrix(self):
        A = ws.Availability
        S = ws.SettlementSize
        assert ws.settlement_workspace_availability(S.VILLAGE, ws.WorkspaceType.WORKSHOP) == A.USUALLY
        assert ws.settlement_workspace_availability(S.VILLAGE, ws.WorkspaceType.FORGE) == A.RARELY
        assert ws.settlement_workspace_availability(S.VILLAGE, ws.WorkspaceType.LABORATORY) == A.NEVER

    def test_town_matrix(self):
        A = ws.Availability
        S = ws.SettlementSize
        assert ws.settlement_workspace_availability(S.TOWN, ws.WorkspaceType.WORKSHOP) == A.ALWAYS
        assert ws.settlement_workspace_availability(S.TOWN, ws.WorkspaceType.FORGE) == A.USUALLY
        assert ws.settlement_workspace_availability(S.TOWN, ws.WorkspaceType.LABORATORY) == A.RARELY

    def test_city_has_all_workspaces(self):
        A = ws.Availability
        S = ws.SettlementSize
        assert ws.settlement_workspace_availability(S.CITY, ws.WorkspaceType.WORKSHOP) == A.ALWAYS
        assert ws.settlement_workspace_availability(S.CITY, ws.WorkspaceType.FORGE) == A.ALWAYS
        assert ws.settlement_workspace_availability(S.CITY, ws.WorkspaceType.LABORATORY) == A.USUALLY

    def test_keldaran_hold_forges_renowned_lab_limited(self):
        A = ws.Availability
        S = ws.SettlementSize
        assert ws.settlement_workspace_availability(S.KELDARAN_HOLD, ws.WorkspaceType.FORGE) == A.ALWAYS
        assert ws.settlement_workspace_availability(S.KELDARAN_HOLD, ws.WorkspaceType.LABORATORY) == A.SOMETIMES

    def test_settlement_size_rejects_unknown_string(self):
        with pytest.raises(ValueError):
            ws.SettlementSize("metropolis")
