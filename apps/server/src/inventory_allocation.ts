import { sql } from "./db.ts";
import { displayName } from "@divineruin/shared";

export interface InventoryStack {
  item_id: string;
  tainted: boolean;
  quantity: number;
}

function eligibleStacks(rows: InventoryStack[], allowTainted: boolean) {
  return rows.filter((row) => allowTainted || !row.tainted);
}

export function eligibleTotals(rows: InventoryStack[], allowTainted: boolean) {
  const totals: Record<string, number> = {};
  for (const row of eligibleStacks(rows, allowTainted))
    totals[row.item_id] = (totals[row.item_id] ?? 0) + row.quantity;
  return totals;
}

export async function consumeMaterials(
  tx: typeof sql,
  playerId: string,
  materials: string[],
  allowTainted: boolean,
): Promise<string | undefined> {
  const required: Record<string, number> = {};
  for (const id of materials) required[id] = (required[id] ?? 0) + 1;
  const ids = Object.keys(required).sort();
  const rows = await tx<InventoryStack[]>`
    SELECT item_id, tainted, COALESCE((data->>'quantity')::int, 1) AS quantity
    FROM player_inventory WHERE player_id=${playerId} AND item_id IN ${sql(ids)}
    ORDER BY item_id, tainted FOR UPDATE
  `;
  const owned = eligibleTotals(rows, allowTainted);
  const usable = eligibleStacks(rows, allowTainted);
  for (const id of ids) {
    if ((owned[id] ?? 0) < required[id]!)
      return `Insufficient material: ${displayName(id)} (need ${required[id]}, have ${owned[id] ?? 0})`;
  }
  for (const id of ids) {
    let need = required[id]!;
    for (const row of usable
      .filter((r) => r.item_id === id)
      .sort((a, b) => Number(b.tainted) - Number(a.tainted))) {
      const take = Math.min(need, row.quantity);
      if (!take) continue;
      const remaining = row.quantity - take;
      need -= take;
      if (remaining) {
        await tx`UPDATE player_inventory SET data=jsonb_set(data,'{quantity}',${remaining}::text::jsonb)
          WHERE player_id=${playerId} AND item_id=${id} AND tainted=${row.tainted}`;
      } else {
        await tx`DELETE FROM player_inventory WHERE player_id=${playerId} AND item_id=${id} AND tainted=${row.tainted}`;
      }
    }
  }
}
