from unittest.mock import AsyncMock, MagicMock

import pytest

from rest_mechanics import apply_rest, apply_short_rest, swap_elective_on_long_rest


class TestApplyShortRest:
    def test_pools_already_full(self) -> None:
        stamina, focus = apply_short_rest(current_stamina=10, max_stamina=10, current_focus=10, max_focus=10)
        assert stamina == 10
        assert focus == 10

    def test_pools_at_zero(self) -> None:
        stamina, focus = apply_short_rest(current_stamina=0, max_stamina=20, current_focus=0, max_focus=20)
        assert stamina == 20
        assert focus == 10


class TestApplyRest:
    def test_invalid_rest_type_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown rest type"):
            apply_rest(
                rest_type="nap",  # type: ignore[arg-type]
                current_stamina=5,
                max_stamina=10,
                current_focus=5,
                max_focus=10,
                current_hp=5,
                max_hp=10,
            )


def _make_persistence(known: list[dict]) -> MagicMock:
    """Mock ability_persistence with the player's current character_abilities rows."""
    persistence = MagicMock()
    persistence.get_character_abilities = AsyncMock(return_value=known)
    persistence.set_elective_equipped = AsyncMock()
    return persistence


class TestSwapElectiveOnLongRest:
    async def test_swap_replaces_and_keeps_old_technique(self) -> None:
        persistence = _make_persistence([{"ability_id": "warrior_cleaving_blow", "equipped": True}])
        await swap_elective_on_long_rest(
            "player_1",
            "warrior_cleaving_blow",
            "warrior_precision_strike",
            persistence_mod=persistence,
        )
        calls = {c.args[1]: c.args[2] for c in persistence.set_elective_equipped.call_args_list}
        assert calls == {"warrior_precision_strike": True, "warrior_cleaving_blow": False}

    async def test_swap_to_different_level_pool_rejected(self) -> None:
        persistence = _make_persistence([{"ability_id": "warrior_cleaving_blow", "equipped": True}])
        with pytest.raises(ValueError):
            await swap_elective_on_long_rest(
                "player_1", "warrior_cleaving_blow", "warrior_war_cry", persistence_mod=persistence
            )
        persistence.set_elective_equipped.assert_not_called()

    async def test_swap_to_different_archetype_rejected(self) -> None:
        persistence = _make_persistence([{"ability_id": "warrior_cleaving_blow", "equipped": True}])
        with pytest.raises(ValueError):
            await swap_elective_on_long_rest(
                "player_1", "warrior_cleaving_blow", "rogue_dirty_trick", persistence_mod=persistence
            )
        persistence.set_elective_equipped.assert_not_called()

    async def test_swap_to_non_elective_rejected(self) -> None:
        persistence = _make_persistence([{"ability_id": "warrior_cleaving_blow", "equipped": True}])
        with pytest.raises(ValueError):
            await swap_elective_on_long_rest(
                "player_1", "warrior_cleaving_blow", "warrior_devastating_strike", persistence_mod=persistence
            )
        persistence.set_elective_equipped.assert_not_called()

    async def test_swap_from_unknown_technique_rejected(self) -> None:
        persistence = _make_persistence([])
        with pytest.raises(ValueError):
            await swap_elective_on_long_rest(
                "player_1", "warrior_cleaving_blow", "warrior_precision_strike", persistence_mod=persistence
            )
        persistence.set_elective_equipped.assert_not_called()
