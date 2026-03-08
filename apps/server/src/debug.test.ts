import { test, expect, describe, beforeAll } from "bun:test";
import "./test-env.ts";

const { handleDebugRooms, handleDebugSendEvent, handleDebugPage } = await import("./debug.ts");

function eventRequest(body: Record<string, unknown>): Request {
  return new Request("http://localhost/api/debug/event", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

describe("handleDebugRooms", () => {
  test("returns empty room list from mock", async () => {
    const res = await handleDebugRooms();
    expect(res.status).toBe(200);
    const body = (await res.json()) as unknown[];
    expect(body).toEqual([]);
  });
});

describe("handleDebugSendEvent", () => {
  test("returns 400 for missing room", async () => {
    const res = await handleDebugSendEvent(eventRequest({ event: { type: "test" } }));
    expect(res.status).toBe(400);
  });

  test("returns 400 for missing event type", async () => {
    const res = await handleDebugSendEvent(eventRequest({ room: "test", event: {} }));
    expect(res.status).toBe(400);
  });
});

describe("handleDebugPage", () => {
  let html: string;

  beforeAll(async () => {
    html = await handleDebugPage().text();
  });

  test("returns HTML with correct Content-Type", () => {
    const res = handleDebugPage();
    expect(res.status).toBe(200);
    expect(res.headers.get("Content-Type")).toBe("text/html; charset=utf-8");
  });

  test("HTML contains expected elements", () => {
    expect(html).toContain("<!DOCTYPE html>");
    expect(html).toContain("Debug Event Console");
    expect(html).toContain("dice_result");
    expect(html).toContain("combat_ui_update");
    expect(html).toContain("item_acquired");
    expect(html).toContain("/api/debug/rooms");
    expect(html).toContain("/api/debug/event");
  });

  test("HTML contains all event types", () => {
    const requiredEventTypes = [
      "session_init",
      "session_end",
      "set_music_state",
      "transcript_entry",
      "creation_cards",
      "creation_card_selected",
      "divine_favor_changed",
      "hollow_corruption_changed",
      "play_narration",
      "inventory_updated",
      "player_portrait_ready",
      "location_changed",
      "quest_update",
    ];
    for (const eventType of requiredEventTypes) {
      expect(html).toContain(eventType);
    }
  });

  test("combat_started payloads include difficulty", () => {
    expect(html).toContain("difficulty:'moderate'");
    expect(html).toContain("difficulty:'hard'");
  });

  test("HTML contains navigation anchor IDs", () => {
    const sectionIds = [
      "sec-session",
      "sec-creation",
      "sec-combat",
      "sec-items",
      "sec-inventory",
      "sec-quest",
      "sec-location",
      "sec-portraits",
      "sec-status",
      "sec-divine",
      "sec-music",
      "sec-sound",
      "sec-transcript",
      "sec-narration",
      "sec-custom",
    ];
    for (const id of sectionIds) {
      expect(html).toContain(`id="${id}"`);
    }
  });

  test("includes security headers", () => {
    const res = handleDebugPage();
    expect(res.headers.get("X-Content-Type-Options")).toBe("nosniff");
    expect(res.headers.get("X-Frame-Options")).toBe("DENY");
    expect(res.headers.get("Content-Security-Policy")).toContain("default-src 'self'");
    expect(res.headers.get("Content-Security-Policy")).toContain("script-src 'unsafe-inline'");
  });

  test("HTML contains all 20 SFX names", () => {
    const allSfx = [
      "dice_roll",
      "sword_clash",
      "tavern",
      "quest_sting",
      "level_up_sting",
      "item_pickup",
      "notification",
      "success_sting",
      "fail_sting",
      "menu_open",
      "menu_close",
      "spell_cast",
      "arrow_loose",
      "hit_taken",
      "critical_hit_sting",
      "shield_block",
      "potion_use",
      "door_creak",
      "discovery_chime",
      "god_whisper_stinger",
    ];
    for (const sfx of allSfx) {
      expect(html).toContain(`sound_name:'${sfx}'`);
    }
  });

  test("location IDs match art registry", () => {
    const artRegistryIds = [
      "accord_market_square",
      "accord_guild_hall",
      "accord_temple_row",
      "accord_dockside",
      "accord_hearthstone_tavern",
      "accord_forge",
      "torin_quarters",
      "emris_study",
      "grimjaw_quarters",
      "greyvale_south_road",
      "greyvale_wilderness_north",
      "greyvale_ruins_exterior",
      "millhaven",
      "millhaven_inn",
      "yanna_farmhouse",
      "greyvale_ruins_entrance",
      "greyvale_ruins_inner",
      "hollow_incursion_site",
    ];
    for (const locId of artRegistryIds) {
      expect(html).toContain(locId);
    }
  });

  test("HTML contains all 11 soundscape names", () => {
    const soundscapes = [
      "market_bustle",
      "harbor_quiet",
      "rural_town_uneasy",
      "dungeon_ancient_hum",
      "hollow_wrongness",
      "guild_hall_bustle",
      "temple_row_chanting",
      "harbor_activity",
      "tavern_busy",
      "wind_ruins",
      "dungeon_resonance_deep",
    ];
    for (const sc of soundscapes) {
      expect(html).toContain(sc);
    }
  });

  test("session_init includes portraits and world_state", () => {
    expect(html).toContain("portraits:");
    expect(html).toContain("world_state:");
    expect(html).toContain("companion:");
    expect(html).toContain("npcs:");
  });

  test("session_end includes story_moments", () => {
    expect(html).toContain("story_moments:");
    expect(html).toContain("moment_key:");
    expect(html).toContain("image_url:");
  });

  test("item_acquired buttons include image_url variants", () => {
    expect(html).toContain("Common Item (no art)");
    expect(html).toContain("(with art)");
  });

  test("quest section includes quest advancement with quest_id and new_stage", () => {
    expect(html).toContain("quest_id:'q_greyvale_anomaly'");
    expect(html).toContain("new_stage:");
  });

  test("location section includes time of day controls", () => {
    expect(html).toContain("setTimeOfDay");
    expect(html).toContain("tod-day");
    expect(html).toContain("tod-dusk");
    expect(html).toContain("tod-night");
    expect(html).toContain("tod-dawn");
    expect(html).toContain("time_of_day");
  });

  test("creation cards include image_url", () => {
    expect(html).toContain("Race Cards (with art)");
    expect(html).toContain("Class Cards (with art)");
  });
});
