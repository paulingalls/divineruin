"""Owned native patron acceptance: real database, registered verbs and LiveKit."""

import argparse
import asyncio
import json
import sys
import threading
import traceback
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).parent / "tests"))

from acceptance._livekit import ensure_livekit_server
from acceptance._livekit_client import connect_room, mint_access_token, wait_for_peer
from acceptance.seeds import seed_player_with_pools
from acceptance.voice_condition_harness import ScenarioModel
from livekit.agents import Agent, AgentSession

import db
import db_queries
import db_session_queries
import event_types as E
from activate_tools import activate
from game_events import publish_game_event
from native_transport.lifecycle import run_cancellable
from participant_lifecycle import _setup_party_join
from progression_tools import _award_divine_favor_core
from query_tools import query_info
from rest_tools import rest
from session_data import SessionData
from session_hydration import apply_session_favor_decay


async def run(args):
    from abilities import load_abilities
    from archetypes import load_archetypes
    from companion_profiles import load_companion_profiles
    from npcs import load_npcs
    from spells import load_spells

    pool = await db.get_pool()
    await load_archetypes()
    await load_spells()
    await load_abilities()
    await load_npcs()
    await load_companion_profiles()
    server = ensure_livekit_server()
    room_name = "patron-native-" + args.run_id
    primary, secondary = ("patron-native-" + args.run_id + suffix for suffix in ("-primary", "-secondary"))
    publisher = await connect_room(
        server.ws_url,
        mint_access_token(
            api_key=server.api_key,
            api_secret=server.api_secret,
            room_name=room_name,
            identity="patron-publisher-" + args.run_id,
            participant_kind="agent",
        ),
    )
    sd = SessionData(player_id=primary, location_id="millhaven_inn", room=publisher)
    model = ScenarioModel([])
    voice = AgentSession(llm=model, userdata=sd, max_tool_steps=5)
    current = primary
    loop = asyncio.get_running_loop()
    lock = asyncio.Lock()
    steps = []
    observed = []

    async def patch_player(pid, **data):
        await pool.execute("UPDATE players SET data=data || $2::jsonb WHERE player_id=$1", pid, json.dumps(data))

    async def command(name, arguments):
        model.commands.append((name, arguments))
        with sd._bind_authenticated_actor(current, 1, lambda *_: None):
            await voice.run(user_input="Execute the command.")
        receipt = list(model.receipts.values())[-1]
        if receipt.is_error:
            raise RuntimeError(receipt.output)

    async def initial():
        await wait_for_peer(publisher, identity=current, timeout=15)
        await publish_game_event(
            publisher,
            E.SESSION_INIT,
            await db_session_queries.get_session_init_payload(current),
            destination_identities=[current],
        )

    async def action(name):
        nonlocal current
        async with lock:
            if name == "initial":
                if current == primary:
                    await initial()
            elif name == "activate":
                await command("activate", {"id": "veythar_lorekeepers_library"})
            elif name in ("short", "long"):
                await command("rest", {"rest_type": name, "use_song_of_rest": False})
            elif name == "promote":
                pending = []
                async with db.transaction() as conn:
                    await _award_divine_favor_core(
                        player_id=current, amount=20, reason="native quest", conn=conn, pending_events=pending
                    )
                for kind, payload in pending:
                    await publish_game_event(publisher, kind, payload, sd.event_bus)
            elif name == "regress":
                now = datetime.now(UTC)
                await patch_player(
                    current,
                    divine_favor={
                        "patron": "veythar",
                        "level": 25,
                        "max": 61,
                        "last_whisper_level": 0,
                        "last_served_at": (now - timedelta(days=8)).isoformat(),
                    },
                )
                player = await db_queries.get_player(current)
                if player is None:
                    raise RuntimeError("Native follower disappeared")
                await apply_session_favor_decay(sd, current, player, now=now)
            elif name == "secondary":
                current = secondary
            elif name == "entry":
                await wait_for_peer(publisher, identity=secondary, timeout=15)
                owner = _setup_party_join(publisher, sd)
                try:
                    if await owner.authorize(secondary) is None:
                        raise RuntimeError("Secondary member failed session entry")
                finally:
                    await owner.aclose()
            elif name == "unbound":
                await patch_player(current, divine_favor={"patron": "none", "level": 0, "max": 61})
                await initial()
            else:
                raise ValueError(f"Unknown step {name}")
            steps.append(name)
            Path(args.evidence).write_text(json.dumps({"run_id": args.run_id, "steps": steps}))
            return {"ok": True, "step": name}

    def fixture():
        return {
            "run_id": args.run_id,
            "player_id": current,
            "url": server.ws_url,
            "token": mint_access_token(
                api_key=server.api_key, api_secret=server.api_secret, room_name=room_name, identity=current, ttl_s=1800
            ),
        }

    class Handler(BaseHTTPRequestHandler):
        def respond(self, status, result):
            payload = json.dumps(result).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            if parse_qs(urlparse(self.path).query).get("run_id") != [args.run_id]:
                return self.respond(403, {"error": "wrong run"})
            self.respond(200, fixture())

        def do_POST(self):
            query = parse_qs(urlparse(self.path).query)
            if query.get("run_id") != [args.run_id]:
                return self.respond(403, {"error": "wrong run"})
            if urlparse(self.path).path == "/received":
                observed.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                Path(args.evidence).with_name("received.json").write_text(json.dumps(observed))
                return self.respond(200, {"ok": True})
            try:
                result = asyncio.run_coroutine_threadsafe(action(query["step"][0]), loop).result(45)
                self.respond(200, result)
            except Exception as error:
                traceback.print_exc()
                self.respond(500, {"error": str(error)})

    http = None
    try:
        for pid, patron, level, gifts in (
            (primary, "veythar", 40, {}),
            (secondary, "zhael", 60, {"zhael_fates_thread": {"spent": True}}),
        ):
            await seed_player_with_pools(pool, player_id=pid)
            await patch_player(
                pid,
                location_id="millhaven_inn",
                divine_favor={"patron": patron, "level": level, "max": 61, "last_whisper_level": 0},
                patron_gifts=gifts,
            )
        from _gods_content import load_gods

        zhael = next(p for p in load_gods() if p["god_id"] == "zhael")
        gift = zhael["layer_3_tier_abilities"]["devoted"]["id"]
        await patch_player(secondary, patron_gifts={gift: {"spent": True}})
        await voice.start(Agent(instructions="Execute commands.", tools=[activate, query_info, rest]))
        http = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
        thread = threading.Thread(target=http.serve_forever, daemon=True)
        thread.start()
        Path(args.ready).write_text(json.dumps({"run_id": args.run_id, "port": http.server_port}))
        await asyncio.Future()
    finally:
        if http:
            await asyncio.to_thread(http.shutdown)
            http.server_close()
        await voice.aclose()
        await publisher.disconnect()
        for pid in (primary, secondary):
            await pool.execute("DELETE FROM players WHERE player_id=$1", pid)
        await db.close_all()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for option in ("run-id", "ready", "evidence"):
        parser.add_argument("--" + option, required=True)
    parser.add_argument("--port", type=int, default=0)
    arguments = parser.parse_args()
    asyncio.run(run_cancellable(lambda: run(arguments)))
