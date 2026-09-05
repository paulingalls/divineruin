import { parseSpellRows } from "@/utils/spell-display";
import { sessionStore } from "@/stores/session-store";
import { characterStore } from "@/stores/character-store";
import { panelStore } from "@/stores/panel-store";
import { portraitStore } from "@/stores/portrait-store";
import type { QuestView, QuestStage, CharacterDetail } from "@/stores/panel-store";
import { parseInventoryItems, extractExitConnections } from "./game-event-parsing";
import type { DataChannelEvent } from "./game-event-parsing";

export function handleSessionInit(event: DataChannelEvent): void {
  const character = event.character as Record<string, unknown> | null | undefined;
  if (character && typeof character === "object") {
    characterStore.getState().setCharacter({
      playerId: typeof character.player_id === "string" ? character.player_id : "",
      name: typeof character.name === "string" ? character.name : "",
      race: typeof character.race === "string" ? character.race : "",
      className: typeof character.class === "string" ? character.class : "Adventurer",
      level: typeof character.level === "number" ? character.level : 1,
      xp: typeof character.xp === "number" ? character.xp : 0,
      locationId: typeof character.location_id === "string" ? character.location_id : "",
      locationName: typeof character.location_name === "string" ? character.location_name : "",
      hpCurrent:
        character.hp && typeof (character.hp as Record<string, unknown>).current === "number"
          ? ((character.hp as Record<string, unknown>).current as number)
          : 0,
      hpMax:
        character.hp && typeof (character.hp as Record<string, unknown>).max === "number"
          ? ((character.hp as Record<string, unknown>).max as number)
          : 0,
      deity: typeof character.deity === "string" ? character.deity : "",
      portraitUrl: typeof character.portrait_url === "string" ? character.portrait_url : null,
    });
  }

  const location = event.location as Record<string, unknown> | null | undefined;
  const worldState = event.world_state as Record<string, unknown> | undefined;
  const initTimeOfDay = worldState && typeof worldState.time === "string" ? worldState.time : "";
  if (location && typeof location === "object") {
    sessionStore.getState().setLocationContext({
      locationId: typeof location.id === "string" ? location.id : "",
      locationName: typeof location.name === "string" ? location.name : "",
      atmosphere: typeof location.atmosphere === "string" ? location.atmosphere : "",
      region: typeof location.region === "string" ? location.region : "",
      tags: Array.isArray(location.tags) ? (location.tags as string[]) : [],
      ambientSounds: typeof location.ambient_sounds === "string" ? location.ambient_sounds : "",
      timeOfDay: initTimeOfDay,
    });
  }

  // --- Populate panel-store ---
  if (character && typeof character === "object") {
    const attrs = character.attributes as Record<string, number> | undefined;
    const equip = character.equipment as Record<string, unknown> | undefined;
    const favor = character.divine_favor as Record<string, unknown> | undefined;
    const detail: CharacterDetail = {
      race: typeof character.race === "string" ? character.race : "",
      attributes: {
        strength: attrs?.strength ?? 10,
        dexterity: attrs?.dexterity ?? 10,
        constitution: attrs?.constitution ?? 10,
        intelligence: attrs?.intelligence ?? 10,
        wisdom: attrs?.wisdom ?? 10,
        charisma: attrs?.charisma ?? 10,
      },
      ac: typeof character.ac === "number" ? character.ac : 10,
      proficiencies: Array.isArray(character.proficiencies)
        ? (character.proficiencies as string[])
        : [],
      savingThrowProficiencies: Array.isArray(character.saving_throw_proficiencies)
        ? (character.saving_throw_proficiencies as string[])
        : [],
      equipment: {
        main_hand: (equip?.main_hand as Record<string, unknown> | null) ?? null,
        armor: (equip?.armor as Record<string, unknown> | null) ?? null,
        shield: (equip?.shield as Record<string, unknown> | null) ?? null,
      },
      gold: typeof character.gold === "number" ? character.gold : 0,
      divineFavor: favor
        ? {
            patron: typeof favor.patron === "string" ? favor.patron : "",
            level: typeof favor.level === "number" ? favor.level : 0,
            max: typeof favor.max === "number" ? favor.max : 0,
          }
        : null,
    };
    // Spells are a top-level session_init sibling (event.spells), not nested under
    // character — publish_game_event flat-merges the payload. (story-007)
    const spellsPayload = event.spells as Record<string, unknown> | undefined;
    if (spellsPayload && typeof spellsPayload === "object") {
      detail.spells = {
        core: parseSpellRows(spellsPayload.core),
        learned: parseSpellRows(spellsPayload.learned),
      };
    }
    panelStore.getState().setCharacterDetail(detail);
  }

  if (Array.isArray(event.inventory)) {
    panelStore
      .getState()
      .setInventory(parseInventoryItems(event.inventory as Record<string, unknown>[]));
  }

  if (Array.isArray(event.quests)) {
    const quests: QuestView[] = (event.quests as Record<string, unknown>[]).map((raw) => {
      const currentStage = typeof raw.current_stage === "number" ? raw.current_stage : 0;
      const rawStages = Array.isArray(raw.stages) ? (raw.stages as Record<string, unknown>[]) : [];
      const stages: QuestStage[] = rawStages.map((s, i) => ({
        id: typeof s.id === "string" ? s.id : `stage_${i}`,
        name: typeof s.name === "string" ? s.name : "",
        objective: typeof s.objective === "string" ? s.objective : "",
        completed: i < currentStage,
        ...(typeof s.target_location_id === "string"
          ? { targetLocationId: s.target_location_id }
          : {}),
      }));
      return {
        questId: typeof raw.quest_id === "string" ? raw.quest_id : "",
        questName: typeof raw.quest_name === "string" ? raw.quest_name : "",
        type: typeof raw.type === "string" ? raw.type : "",
        currentStage,
        stages,
        hints: Array.isArray(raw.hints) ? (raw.hints as string[]) : [],
        status: "active" as const,
      };
    });
    panelStore.getState().setQuests(quests);
  }

  // Seed map from map_progress — batch into a single setMapProgress to avoid O(n^2)
  if (Array.isArray(event.map_progress) && (event.map_progress as unknown[]).length > 0) {
    const nodes: import("@/stores/panel-store").MapNode[] = [];
    const seen = new Set<string>();
    for (const entry of event.map_progress as Record<string, unknown>[]) {
      const locId = typeof entry.location_id === "string" ? entry.location_id : "";
      const conns = Array.isArray(entry.connections) ? (entry.connections as string[]) : [];
      if (locId && !seen.has(locId)) {
        seen.add(locId);
        nodes.push({ locationId: locId, visited: true, connections: conns });
        for (const connId of conns) {
          if (!seen.has(connId)) {
            seen.add(connId);
            nodes.push({ locationId: connId, visited: false, connections: [] });
          }
        }
      }
    }
    panelStore.getState().setMapProgress(nodes);
  }
  // Also ensure current location from session_init location data is visited
  if (location && typeof location === "object" && typeof location.id === "string") {
    const locExits = location.exits as Record<string, unknown> | undefined;
    const exitConns =
      locExits && typeof locExits === "object" ? extractExitConnections(locExits) : [];
    panelStore.getState().addVisitedLocation(location.id, exitConns);
  }

  // --- Companion identity: the name the HUD shows and the voice tag its portrait gate matches ---
  const companionIdentity = event.companion as Record<string, unknown> | null | undefined;
  portraitStore
    .getState()
    .setCompanionIdentity(
      typeof companionIdentity?.name === "string" ? companionIdentity.name : null,
      typeof companionIdentity?.voice_id === "string" ? companionIdentity.voice_id : null,
    );

  // --- Populate portrait store ---
  const portraits = event.portraits as Record<string, unknown> | undefined;
  if (portraits && typeof portraits === "object") {
    // An explicit branch, not a typeof guard that falls through: a companion with no generated
    // asset set arrives as null, and falling through leaves the PREVIOUS companion's face in
    // the HUD.
    const companion = portraits.companion as Record<string, unknown> | null | undefined;
    const primary = typeof companion?.primary === "string" ? companion.primary : null;
    const alert = typeof companion?.alert === "string" ? companion.alert : null;
    portraitStore.getState().setCompanionPortraits(primary, alert);

    const npcs = portraits.npcs as Record<string, string> | undefined;
    if (npcs && typeof npcs === "object") {
      portraitStore.getState().setNpcPortraitMap(npcs);
    }
  }

  // Extract player portrait_url from character data
  if (character && typeof character === "object") {
    const portraitUrl = character.portrait_url;
    if (typeof portraitUrl === "string") {
      characterStore.getState().updatePortraitUrl(portraitUrl);
      portraitStore.getState().setPlayerPortraitUrl(portraitUrl);
    }
  }

  console.log("[game-events] session_init processed", {
    quests: Array.isArray(event.quests) ? (event.quests as unknown[]).length : 0,
    inventory: Array.isArray(event.inventory) ? (event.inventory as unknown[]).length : 0,
  });
}
