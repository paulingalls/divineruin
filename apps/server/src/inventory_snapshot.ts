import { sql } from "./db.ts";
import { parseJsonb } from "./parse-jsonb.ts";

function pythonString(value: string): string {
  return JSON.stringify(value).replace(
    /[\u007f-\uffff]/g,
    (c) => `\\u${c.charCodeAt(0).toString(16).padStart(4, "0")}`,
  );
}

function itemImage(item: Record<string, unknown>): string | undefined {
  const art = item.art_template as
    { template_id?: string; vars?: Record<string, string> } | undefined;
  if (!art?.template_id) return;
  // Python json.dumps uses ASCII escapes and spaces in its content-addressed payload.
  const entries = Object.entries(art.vars ?? {}).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
  const payload =
    art.template_id +
    `[${entries.map(([k, v]) => `[${pythonString(k)}, ${pythonString(v)}]`).join(", ")}]`;
  const hash = new Bun.CryptoHasher("sha256").update(payload).digest("hex").slice(0, 16);
  return `/api/assets/images/img_${hash}`;
}

export async function inventorySnapshot(playerId: string, tx = sql) {
  const rows: {
    inventory_revision: string;
    item_id: string | null;
    item_data: unknown;
    material_data: unknown;
    slot_data: unknown;
  }[] = await tx`
    SELECT p.inventory_revision::text, pi.item_id, i.data AS item_data, m.data AS material_data, pi.data AS slot_data
    FROM players p
    LEFT JOIN player_inventory pi ON pi.player_id = p.player_id
    LEFT JOIN items i ON i.id = pi.item_id
    LEFT JOIN materials_catalog m ON m.id = pi.item_id
    WHERE p.player_id = ${playerId}
  `;
  if (!rows.length) throw new Error(`Unknown inventory owner ${playerId}`);
  const inventory = rows
    .filter((row) => row.item_id !== null)
    .map((row) => {
      if (row.item_data == null && row.material_data == null)
        throw new Error(`Inventory id ${row.item_id} has no catalog entry`);
      const item = { ...parseJsonb(row.item_data ?? row.material_data) };
      if (row.item_data == null) item.type = "material";
      item.slot_info = parseJsonb(row.slot_data);
      const image = itemImage(item);
      if (image) item.image_url = image;
      return item;
    });
  return { player_id: playerId, inventory_revision: rows[0]!.inventory_revision, inventory };
}
