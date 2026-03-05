import { playSfx } from "./sfx-player";
import { hapticDiceRoll, hapticItemAcquired, hapticLevelUp } from "./haptics";
import { sessionStore } from "@/stores/session-store";
import { characterStore } from "@/stores/character-store";
import { transcriptStore } from "@/stores/transcript-store";
import { hudStore } from "@/stores/hud-store";
import type { Combatant, CombatTrackerState, CreationCard } from "@/stores/hud-store";

export interface DataChannelEvent {
  type: string;
  [key: string]: unknown;
}

const decoder = new TextDecoder();

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
      console.log("[game-events] Logged for future:", event.type);
      break;

    default:
      console.log("[game-events] Unhandled event type:", event.type);
  }
}
