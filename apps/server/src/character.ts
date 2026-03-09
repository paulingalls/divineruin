import { sql } from "./db.ts";
import { logError } from "./env.ts";
import { generateImage } from "./image-gen.ts";

interface CharacterRow {
  player_id: string;
  data: {
    name?: string;
    race?: string;
    class?: string;
    level?: number;
    xp?: number;
    location_id?: string;
    hp?: { current?: number; max?: number };
    portrait_url?: string;
  };
  location_name: string | null;
}

export async function handleGetCharacter(_req: Request, playerId: string): Promise<Response> {
  try {
    const rows: CharacterRow[] = await sql`
      SELECT
        p.player_id,
        p.data,
        l.data->>'name' AS location_name
      FROM players p
      LEFT JOIN locations l ON l.id = p.data->>'location_id'
      WHERE p.player_id = ${playerId}
      LIMIT 1
    `;

    if (rows.length === 0) {
      return Response.json({ error: "Player not found" }, { status: 404 });
    }

    const row = rows[0]!;
    const data =
      typeof row.data === "string" ? (JSON.parse(row.data) as CharacterRow["data"]) : row.data;

    if (!data.name) {
      return Response.json({ error: "Character not created" }, { status: 404 });
    }

    const hp = data.hp ?? {};
    const locationId = data.location_id ?? "unknown";

    return Response.json({
      player_id: row.player_id,
      name: data.name,
      class: data.class ?? "Adventurer",
      level: data.level ?? 1,
      xp: data.xp ?? 0,
      location_id: locationId,
      location_name: row.location_name ?? locationId,
      hp_current: hp.current ?? 0,
      hp_max: hp.max ?? 0,
      portrait_url: data.portrait_url ?? null,
    });
  } catch (err) {
    logError("[character] DB query failed:", err);
    return Response.json({ error: "Internal server error" }, { status: 500 });
  }
}

export async function handleRegeneratePortrait(_req: Request, playerId: string): Promise<Response> {
  try {
    const rows: CharacterRow[] = await sql`
      SELECT player_id, data, NULL AS location_name
      FROM players
      WHERE player_id = ${playerId}
      LIMIT 1
    `;

    if (rows.length === 0) {
      return Response.json({ error: "Player not found" }, { status: 404 });
    }

    const row = rows[0]!;
    const data =
      typeof row.data === "string" ? (JSON.parse(row.data) as CharacterRow["data"]) : row.data;

    const className = data.class ?? "adventurer";
    const raceName = data.race ?? "adventurer";

    // Random seed so the hash differs from previous portrait
    const seed = Math.random().toString(36).substring(2, 8);

    const result = await generateImage("player_character_creation", {
      class: className,
      key_feature: raceName,
      seed,
    });

    const portraitUrl = `/api/assets/images/${result.assetId}`;

    // Update player data
    await sql`
      UPDATE players
      SET data = jsonb_set(data, '{portrait_url}', ${JSON.stringify(portraitUrl)}::jsonb)
      WHERE player_id = ${playerId}
    `;

    return Response.json({ portrait_url: portraitUrl });
  } catch (err) {
    logError("[character] Portrait regeneration failed:", err);
    return Response.json({ error: "Internal server error" }, { status: 500 });
  }
}
