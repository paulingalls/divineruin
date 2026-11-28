import pytest

from purchase_pricing import purchase_price


@pytest.mark.parametrize(
    ("rate", "frontier", "expected"),
    [(0.2, 2, 5), (2, 2, 30), (0.25, 2, 5), (1.5, 2, 30), (0.7585, 1.1207, 9)],
    ids=["lower-clamp", "upper-clamp", "lower-bound", "upper-bound", "fractional-composition"],
)
def test_purchase_clamps_composed_multiplier(rate: float, frontier: float, expected: int) -> None:
    assert (
        purchase_price(
            10,
            1,
            "neutral",
            ("frontier",),
            pricing={
                "purchase_disposition_multipliers": {"neutral": rate},
                "purchase_frontier_multiplier": frontier,
            },
        )
        == expected
    )
