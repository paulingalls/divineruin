from unittest.mock import Mock

import pytest
from sample_fixtures import make_db_mod

import choir_scene
import combat_round_checkpoint
import db


@pytest.fixture(autouse=True)
def checkpoint_fake_connections(monkeypatch) -> None:
    read_party = combat_round_checkpoint.read_party
    start = choir_scene.start

    async def read_on_connection(conn, ids: list[str]) -> dict[str, dict]:
        if isinstance(conn, Mock):
            return {pid: {"data": {}, "inventory": []} for pid in ids}
        return await read_party(conn, ids)

    async def start_on_connection(session, state, retained, *, mutations, queries, db_mod):
        if db_mod is db and isinstance(mutations.save_combat_state, Mock):
            db_mod, _ = make_db_mod()
        return await start(session, state, retained, mutations=mutations, queries=queries, db_mod=db_mod)

    monkeypatch.setattr(combat_round_checkpoint, "read_party", read_on_connection)
    monkeypatch.setattr(choir_scene, "start", start_on_connection)
