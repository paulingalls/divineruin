import pytest
from _patron_engine_fixtures import configure
from _unbound_path_fixtures import row
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import game_tools

from query_tools import query_info
from zhael_fate import FATE


@pytest.mark.parametrize(
    "state",
    [
        pytest.param({}, id="empty"),
        pytest.param({"typo": 1}, id="unknown"),
        pytest.param({"uses_spent": 1, "spent": True}, id="mixed"),
        pytest.param({"spent": False, "extra": None}, id="legacy-extra"),
        pytest.param({"uses_spent": 1, "extra": None}, id="count-extra"),
        pytest.param({"spent": 1}, id="legacy-int"),
        pytest.param({"spent": "yes"}, id="legacy-string"),
        pytest.param({"uses_spent": True}, id="count-true"),
        pytest.param({"uses_spent": False}, id="count-false"),
        pytest.param({"uses_spent": 1.0}, id="count-float"),
        pytest.param({"uses_spent": -1}, id="count-negative"),
        pytest.param({"uses_spent": 3}, id="count-above-two"),
    ],
)
async def test_patron_query_rejects_malformed_fate_state(world, state):
    stored = {FATE: state}
    await configure(world, "zhael", "oracle", patron_gifts=stored)
    call = game_tools(world.ctx.userdata, query_info)
    with pytest.raises(ValueError, match=f"Malformed patron ability state: {FATE}"):
        await call("query_info", kind="patron")
    assert (await row(world, 0))["patron_gifts"] == stored
