import { sql } from "./db.ts";

interface CharacterRow {
  player_id: string;
  data: {
    name?: string;
    level?: number;
    xp?: number;
    hp?: { current?: number; max?: number };
  };
  location_id: string;
  location_name: string | null;
}

export async function handleGetCharacter(_req: Request, playerId: string): Promise<Response> {
  try {
    const rows = await sql`
      SELECT
        p.player_id,
        p.data,
        p.location_id,
        l.data->>'name' AS location_name
      FROM players p
      LEFT JOIN locations l ON l.location_id = p.location_id
      WHERE p.player_id = ${playerId}
      LIMIT 1
    `;

    if (rows.length === 0) {
      return Response.json({ error: "Player not found" }, { status: 404 });
    }

    const row = rows[0] as CharacterRow;
    const data = typeof row.data === "string" ? JSON.parse(row.data) : row.data;
    const hp = data.hp ?? {};

    return Response.json({
      player_id: row.player_id,
      name: data.name ?? "Unknown",
      level: data.level ?? 1,
      xp: data.xp ?? 0,
      location_id: row.location_id,
      location_name: row.location_name ?? row.location_id,
      hp_current: hp.current ?? 0,
      hp_max: hp.max ?? 0,
    });
  } catch (err) {
    console.error("[character] DB query failed:", err);
    return Response.json({ error: "Internal server error" }, { status: 500 });
  }
}
