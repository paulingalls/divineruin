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

    case "session_end":
      sessionStore.getState().setPhase("ended");
      break;

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
