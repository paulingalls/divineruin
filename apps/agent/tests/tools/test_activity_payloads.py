"""Payload mapping alone does not prove router acceptance; test_activity_tools drives the router."""

from activity_payloads import (
    ACTIVITY_VARIANTS,
    CompanionErrand,
    Crafting,
    Experiment,
    MaterialQuantity,
    Training,
    WorkspaceRental,
    to_impl_kwargs,
)


def test_training_variant_maps_to_the_training_impl_kwargs():
    assert to_impl_kwargs(Training(kind="training", program_id="combat_basics")) == (
        "training",
        {"program_id": "combat_basics", "spell_id": None},
    )


def test_companion_errand_variant_maps_to_the_errand_impl_kwargs():
    assert to_impl_kwargs(
        CompanionErrand(
            kind="companion_errand",
            companion_id="companion_kael",
            errand_type="scout",
            destination="accord_market_square",
        )
    ) == (
        "companion_errand",
        {"companion_id": "companion_kael", "errand_type": "scout", "destination": "accord_market_square"},
    )


def test_crafting_variant_maps_to_the_crafting_impl_kwargs():
    assert to_impl_kwargs(Crafting(kind="crafting", recipe_id="iron_dagger_recipe")) == (
        "crafting",
        {"recipe_id": "iron_dagger_recipe"},
    )


def test_workspace_variant_maps_to_the_rental_impl_kwargs():
    assert to_impl_kwargs(
        WorkspaceRental(kind="workspace", workspace_type="forge", npc_id="guildmaster_torin", days=3)
    ) == ("workspace", {"workspace_type": "forge", "npc_id": "guildmaster_torin", "days": 3})


def test_experiment_variant_unzips_its_materials_into_the_positional_lists():
    """The mapper unzips paired materials into the implementation's aligned lists."""
    assert to_impl_kwargs(
        Experiment(
            kind="experiment",
            materials=[
                MaterialQuantity(material_id="iron_ore", quantity=2),
                MaterialQuantity(material_id="coal", quantity=1),
            ],
            intended_output="iron_ingot",
        )
    ) == (
        "experiment",
        {"material_ids": ["iron_ore", "coal"], "quantities": [2, 1], "intended_output": "iron_ingot"},
    )


def test_variant_optional_fields_are_pinned():
    """ADR 0008 permits only Training.spell_id as the sanctioned optional-field exception."""
    optional = {
        variant.__name__: {name for name, field in variant.model_fields.items() if not field.is_required()}
        for variant in ACTIVITY_VARIANTS
    }
    assert optional == {
        "Training": {"spell_id"},
        "CompanionErrand": set(),
        "Crafting": set(),
        "WorkspaceRental": set(),
        "Experiment": set(),
    }
