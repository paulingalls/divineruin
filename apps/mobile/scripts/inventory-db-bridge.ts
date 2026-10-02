import assert from "node:assert/strict";
import { SQL } from "bun";
import { Participant, ParticipantKind } from "livekit-client";
type Snapshot = {
  player_id: string;
  inventory_revision: string;
  inventory: Record<string, unknown>[];
};
const producerPath = "../../server/src/inventory_snapshot.ts";
const { inventorySnapshot } = (await import(producerPath)) as {
  inventorySnapshot: (owner: string, tx: SQL) => Promise<Snapshot>;
};
import { authStore } from "@/stores/auth-store";
import { panelStore } from "@/stores/panel-store";
import { handleGameEventMessage } from "@/audio/game-event-handler";
import { applyInventorySnapshot, parseHttpInventory } from "@/audio/inventory-refresh";

{
  const path = process.env.INVENTORY_FRESHNESS_FIXTURE;
  if (!path)
    throw new Error("Run through tests/test_inventory_revision.py with its real DB fixture");
  const { buffered, current } = (await Bun.file(path).json()) as {
    buffered: Awaited<ReturnType<typeof inventorySnapshot>>;
    current: Awaited<ReturnType<typeof inventorySnapshot>>;
  };
  const sql = new SQL(process.env.DATABASE_URL!);
  try {
    const actual = await inventorySnapshot(current.player_id, sql);
    assert.deepEqual(actual, current);
    const rollback = new Error("capture rollback");
    try {
      await sql.begin(async (tx) => {
        let calls = 0;
        const boundary = (async (strings: TemplateStringsArray, ...values: unknown[]) => {
          calls++;
          const rows = await tx<Record<string, unknown>[]>(strings, ...values);
          if (calls === 1)
            await tx`UPDATE player_inventory SET data='{"quantity":4}'::jsonb WHERE player_id=${current.player_id}`;
          return rows;
        }) as unknown as typeof sql;
        assert.deepEqual(await inventorySnapshot(current.player_id, boundary), current);
        assert.equal(calls, 1);
        throw rollback;
      });
    } catch (error) {
      if (error !== rollback) throw error;
    }
    panelStore.getState().reset();
    authStore.setState({ playerId: current.player_id, phase: "authenticated", token: "fixture" });
    applyInventorySnapshot(parseHttpInventory(actual, current.player_id));
    handleGameEventMessage({
      payload: new TextEncoder().encode(JSON.stringify({ type: "inventory_updated", ...buffered })),
      from: new Participant(
        "agent",
        "dm",
        undefined,
        undefined,
        undefined,
        undefined,
        ParticipantKind.AGENT,
      ),
    });
    assert.equal(panelStore.getState().inventory[0]?.quantity, 3);
    assert.equal(panelStore.getState().inventoryRevision, "9007199254740993");
  } finally {
    await sql.close();
  }
}
