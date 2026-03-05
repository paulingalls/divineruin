import { playSfx } from "./sfx-player";
import { sessionStore } from "@/stores/session-store";
import { characterStore } from "@/stores/character-store";
import { transcriptStore } from "@/stores/transcript-store";

export interface DataChannelEvent {
  type: string;
  [key: string]: unknown;
}

const decoder = new TextDecoder();

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
      playSfx("dice_roll");
      break;

    case "session_init": {
      const character = event.character as Record<string, unknown> | null | undefined;
      if (character && typeof character === "object") {
        characterStore.getState().setCharacter({
          playerId: typeof character.player_id === "string" ? character.player_id : "",
          name: typeof character.name === "string" ? character.name : "",
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
      break;

    case "xp_awarded":
      if (typeof event.new_xp === "number" && typeof event.new_level === "number") {
        characterStore.getState().updateXp(event.new_xp, event.new_level);
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
        speaker: (event.speaker as "player" | "dm" | "npc" | "tool") ?? "dm",
        character: (event.character as string) ?? null,
        emotion: (event.emotion as string) ?? null,
        text: typeof event.text === "string" ? event.text : "",
        timestamp: typeof event.timestamp === "number" ? event.timestamp : Date.now() / 1000,
      });
      break;

    case "quest_updated":
    case "inventory_updated":
      console.log("[game-events] Logged for future:", event.type);
      break;

    default:
      console.log("[game-events] Unhandled event type:", event.type);
  }
}
