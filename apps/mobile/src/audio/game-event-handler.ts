import { playSfx } from "./sfx-player";

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
    default:
      console.log("[game-events] Unhandled event type:", event.type);
  }
}
