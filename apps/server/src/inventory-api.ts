import { inventorySnapshot } from "./inventory_snapshot.ts";
import { logError } from "./env.ts";

export async function handleGetInventory(_req: Request, playerId: string): Promise<Response> {
  try {
    return Response.json(await inventorySnapshot(playerId));
  } catch (error) {
    logError("[inventory] refresh failed:", error);
    return Response.json({ error: "Inventory refresh failed" }, { status: 500 });
  }
}
