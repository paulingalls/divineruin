import { playSfx } from "./sfx-player";
import { hapticDiceRoll, hapticItemAcquired, hapticLevelUp } from "./haptics";
import { sessionStore } from "@/stores/session-store";
import { characterStore } from "@/stores/character-store";
import { transcriptStore } from "@/stores/transcript-store";
import { hudStore } from "@/stores/hud-store";
import { panelStore } from "@/stores/panel-store";
import type { Combatant, CombatTrackerState, CreationCard } from "@/stores/hud-store";
import type {
  InventoryItem,
  QuestView,
  QuestStage,
  CharacterDetail,
  ItemRarity,
} from "@/stores/panel-store";

export interface DataChannelEvent {
  type: string;
  [key: string]: unknown;
}

const decoder = new TextDecoder();

const VALID_RARITIES = new Set<ItemRarity>(["common", "uncommon", "rare", "legendary"]);

function parseRarity(value: unknown): ItemRarity {
  return typeof value === "string" && VALID_RARITIES.has(value as ItemRarity)
    ? (value as ItemRarity)
    : "common";
}

function parseInventoryItems(rawItems: Record<string, unknown>[]): InventoryItem[] {
  return rawItems.map((raw) => {
    const slotInfo = raw.slot_info as Record<string, unknown> | undefined;
    return {
      id: typeof raw.id === "string" ? raw.id : "",
      name: typeof raw.name === "string" ? raw.name : "",
      type: typeof raw.type === "string" ? raw.type : "",
      rarity: parseRarity(raw.rarity),
      description: typeof raw.description === "string" ? raw.description : "",
      weight: typeof raw.weight === "number" ? raw.weight : 0,
      effects: Array.isArray(raw.effects) ? (raw.effects as Record<string, unknown>[]) : [],
      lore: typeof raw.lore === "string" ? raw.lore : "",
      value_base: typeof raw.value_base === "number" ? raw.value_base : 0,
      quantity: typeof slotInfo?.quantity === "number" ? slotInfo.quantity : 1,
      equipped: slotInfo?.equipped === true,
    };
  });
}

function extractExitConnections(exits: Record<string, unknown>): string[] {
  const connections: string[] = [];
  for (const exitData of Object.values(exits)) {
    if (typeof exitData === "string") {
      if (exitData) connections.push(exitData);
    } else if (exitData && typeof exitData === "object") {
      const dest = (exitData as Record<string, unknown>).destination;
      if (typeof dest === "string" && dest) connections.push(dest);
    }
  }
  return connections;
}

/** Delay before playing dice result stinger (matches tumble animation duration). */
export const DICE_STINGER_DELAY_MS = 600;
let _diceStingerTimer: ReturnType<typeof setTimeout> | null = null;

export function parseGameEvent(payload: Uint8Array): DataChannelEvent | null {
  try {
    const text = decoder.decode(payload);
    const data: unknown = JSON.parse(text);
    if (data && typeof data === "object" && "type" in data) {
      return data as DataChannelEvent;
    }
    console.warn("[game-events] Missing type field:", data);
    return null;
  } catch {
    console.warn("[game-events] Failed to parse message");
    return null;
  }
}

export function handleGameEvent(event: DataChannelEvent): void {
  switch (event.type) {
    case "play_sound":
      if (typeof event.sound_name === "string") {
        playSfx(event.sound_name);
      }
      break;

    case "dice_roll":
    case "dice_result":
      playSfx("dice_roll");
      hapticDiceRoll();
      hudStore.getState().pushOverlay("dice_result", {
        roll: event.roll,
        modifier: event.modifier,
        total: event.total,
        success: event.success,
        rollType: event.roll_type,
        narrative: event.narrative,
      });
      if (_diceStingerTimer) clearTimeout(_diceStingerTimer);
      _diceStingerTimer = setTimeout(() => {
        _diceStingerTimer = null;
        playSfx(event.success ? "success_sting" : "fail_sting");
      }, DICE_STINGER_DELAY_MS);
      break;

    case "session_init": {
      const character = event.character as Record<string, unknown> | null | undefined;
      if (character && typeof character === "object") {
        characterStore.getState().setCharacter({
          playerId: typeof character.player_id === "string" ? character.player_id : "",
          name: typeof character.name === "string" ? character.name : "",
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
        });
      }

      const location = event.location as Record<string, unknown> | null | undefined;
      if (location && typeof location === "object") {
        sessionStore.getState().setLocationContext({
          locationId: typeof location.id === "string" ? location.id : "",
          locationName: typeof location.name === "string" ? location.name : "",
          atmosphere: typeof location.atmosphere === "string" ? location.atmosphere : "",
          region: typeof location.region === "string" ? location.region : "",
          tags: Array.isArray(location.tags) ? (location.tags as string[]) : [],
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
          const rawStages = Array.isArray(raw.stages)
            ? (raw.stages as Record<string, unknown>[])
            : [];
          const stages: QuestStage[] = rawStages.map((s, i) => ({
            id: typeof s.id === "string" ? s.id : `stage_${i}`,
            name: typeof s.name === "string" ? s.name : "",
            objective: typeof s.objective === "string" ? s.objective : "",
            completed: i < currentStage,
          }));
          return {
            questId: typeof raw.quest_id === "string" ? raw.quest_id : "",
            questName: typeof raw.quest_name === "string" ? raw.quest_name : "",
            type: typeof raw.type === "string" ? raw.type : "",
            currentStage,
            stages,
            globalHints:
              raw.global_hints &&
              typeof raw.global_hints === "object" &&
              !Array.isArray(raw.global_hints)
                ? (raw.global_hints as Record<string, string>)
                : {},
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

      console.log("[game-events] session_init processed", {
        quests: Array.isArray(event.quests) ? (event.quests as unknown[]).length : 0,
        inventory: Array.isArray(event.inventory) ? (event.inventory as unknown[]).length : 0,
      });
      break;
    }

    case "location_changed":
      if (typeof event.new_location === "string") {
        const locationName =
          typeof event.location_name === "string" ? event.location_name : event.new_location;
        const atmosphere = typeof event.atmosphere === "string" ? event.atmosphere : "";
        const region = typeof event.region === "string" ? event.region : "";
        sessionStore.getState().setLocationContext({
          locationId: event.new_location,
          locationName,
          atmosphere,
          region,
          tags: [],
        });
        characterStore.getState().updateLocation(event.new_location, locationName);
        const connections = Array.isArray(event.connections) ? (event.connections as string[]) : [];
        panelStore.getState().addVisitedLocation(event.new_location, connections);
      }
      break;

    case "combat_started":
      sessionStore.getState().setCombat(true);
      playSfx("sword_clash");
      break;

    case "combat_ended":
      sessionStore.getState().setCombat(false);
      hudStore.getState().clearCombatState();
      break;

    case "combat_ui_update": {
      const combatants = Array.isArray(event.combatants) ? (event.combatants as Combatant[]) : [];
      const combatState: CombatTrackerState = {
        phase: typeof event.phase === "string" ? event.phase : "unknown",
        round: typeof event.round === "number" ? event.round : 1,
        combatants,
      };
      hudStore.getState().setCombatState(combatState);
      sessionStore.getState().setCombat(true);
      break;
    }

    case "xp_awarded":
      if (typeof event.new_xp === "number" && typeof event.new_level === "number") {
        characterStore.getState().updateXp(event.new_xp, event.new_level);
        if (event.level_up) {
          hudStore.getState().pushOverlay(
            "level_up",
            {
              newLevel: event.new_level,
              xpGained: event.xp_gained,
              className: characterStore.getState().character?.className,
            },
            5000,
          );
          playSfx("level_up_sting");
          hapticLevelUp();
        } else {
          hudStore.getState().pushOverlay(
            "xp_toast",
            {
              xpGained: typeof event.xp_gained === "number" ? event.xp_gained : 0,
            },
            2500,
          );
        }
      }
      break;

    case "hp_changed":
      if (typeof event.current === "number") {
        characterStore
          .getState()
          .updateHp(event.current, typeof event.max === "number" ? event.max : undefined);
      }
      break;

    case "session_end": {
      const store = sessionStore.getState();
      if (typeof event.summary === "string") {
        store.setSessionSummary({
          summary: event.summary,
          xpEarned: typeof event.xp_earned === "number" ? event.xp_earned : 0,
          itemsFound: Array.isArray(event.items_found) ? (event.items_found as string[]) : [],
          questProgress: Array.isArray(event.quest_progress)
            ? (event.quest_progress as string[])
            : [],
          duration: typeof event.duration === "number" ? event.duration : 0,
          nextHooks: Array.isArray(event.next_hooks) ? (event.next_hooks as string[]) : [],
        });
        store.setPhase("summary");
      } else {
        store.setPhase("ended");
      }
      break;
    }

    case "transcript_entry":
      transcriptStore.getState().addEntry({
        speaker: (event.speaker as "player" | "dm" | "npc" | "tool" | undefined) ?? "dm",
        character: (event.character as string | undefined) ?? null,
        emotion: (event.emotion as string | undefined) ?? null,
        text: typeof event.text === "string" ? event.text : "",
        timestamp: typeof event.timestamp === "number" ? event.timestamp : Date.now() / 1000,
      });
      break;

    case "item_acquired":
      hudStore.getState().pushOverlay("item_acquired", {
        name: event.name,
        description: event.description,
        rarity: event.rarity,
        stats: event.stats,
      });
      playSfx("item_pickup");
      hapticItemAcquired();
      break;

    case "quest_update":
    case "quest_updated": {
      const questHud = hudStore.getState();
      questHud.pushOverlay("quest_update", {
        questName: event.quest_name,
        objective: event.objective,
        status: event.status,
        stageName: event.stage_name,
      });
      if (typeof event.quest_name === "string" && typeof event.objective === "string") {
        questHud.setActiveObjective({
          questName: event.quest_name,
          objective: event.objective,
          updatedAt: Date.now(),
        });
      }
      playSfx("quest_sting");
      break;
    }

    case "status_effect": {
      const hud = hudStore.getState();
      if (event.action === "remove" && typeof event.effect_id === "string") {
        hud.removeStatusEffect(event.effect_id);
      } else if (typeof event.effect_id === "string" && typeof event.name === "string") {
        hud.addStatusEffect({
          id: event.effect_id,
          name: event.name,
          category: event.category === "debuff" ? "debuff" : "buff",
        });
      }
      break;
    }

    case "creation_cards": {
      const cards = Array.isArray(event.cards) ? (event.cards as CreationCard[]) : [];
      hudStore.getState().setCreationCards(cards);
      break;
    }

    case "creation_card_selected":
      if (typeof event.card_id === "string") {
        hudStore.getState().setSelectedCreationCard(event.card_id);
      }
      break;

    case "inventory_updated":
      if (Array.isArray(event.inventory)) {
        panelStore
          .getState()
          .setInventory(parseInventoryItems(event.inventory as Record<string, unknown>[]));
      }
      break;

    default:
      console.log("[game-events] Unhandled event type:", event.type);
  }
}
