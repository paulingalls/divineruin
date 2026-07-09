import { playSfx } from "./sfx-player";
import { hapticDiceRoll, hapticItemAcquired, hapticLevelUp } from "./haptics";
import { overrideMusicState } from "./music-player";
import type { MusicState } from "./music-registry";
import * as E from "./event-types";
import Constants from "expo-constants";
import { getApiBase, resolveApiUrl } from "@/utils/base-url";
import type { ReceivedDataMessage } from "@/livekit";
import { sessionStore, type CombatDifficulty, type StoryMoment } from "@/stores/session-store";
import { characterStore } from "@/stores/character-store";
import { transcriptStore } from "@/stores/transcript-store";
import { hudStore } from "@/stores/hud-store";
import { panelStore } from "@/stores/panel-store";
import { portraitStore } from "@/stores/portrait-store";
import type {
  Combatant,
  CombatTrackerState,
  CreationCard,
  HollowEchoBand,
  ResonanceState,
} from "@/stores/hud-store";
import {
  parseInventoryItems,
  parseCombatant,
  parseGameEvent,
  VALID_MUSIC_STATES,
  VALID_DIFFICULTIES,
  VALID_RESONANCE_STATES,
  VALID_HOLLOW_ECHO_BANDS,
} from "./game-event-parsing";
import type { DataChannelEvent } from "./game-event-parsing";
import { handleSessionInit } from "./game-event-session-init";

export type { DataChannelEvent } from "./game-event-parsing";
export {
  parseCombatant,
  parseGameEvent,
  VALID_RESONANCE_STATES,
  VALID_HOLLOW_ECHO_BANDS,
  MAX_EVENT_PAYLOAD_BYTES,
} from "./game-event-parsing";

/** Allowlist for safe API sub-paths (alphanumeric, hyphens, underscores, dots, slashes). */
const SAFE_API_PATH_RE = /^\/api\/[a-zA-Z0-9/_.-]+$/;

/** Delay before playing dice result stinger (matches tumble animation duration). */
export const DICE_STINGER_DELAY_MS = 600;
/** TTL for dice roll overlay — longer than default to account for tumble animation. */
export const DICE_ROLL_TTL_MS = 5000;
/** TTL for the dramatic Hollow Echo band overlay — lingers so the band is glanceable. */
export const HOLLOW_ECHO_TTL_MS = 5000;
/** Name of the companion character for portrait visibility. */
const COMPANION_NAME = "Kael";
let _diceStingerTimer: ReturnType<typeof setTimeout> | null = null;
let _companionHideTimer: ReturnType<typeof setTimeout> | null = null;

// Trust only the DM/agent participant. A player co-participant is Standard-kind;
// isAgent gates out forged game_events (fake HP/XP) from other players.
export function isDmSender(from: { isAgent?: boolean } | undefined): boolean {
  return from?.isAgent === true;
}

export function handleGameEventMessage(msg: ReceivedDataMessage): void {
  if (!isDmSender(msg.from)) return;
  const event = parseGameEvent(msg.payload);
  if (event) {
    console.log("[game-events] received:", event.type);
    handleGameEvent(event);
  }
}

/**
 * True when a caster-scoped HUD event targets the local player (M14 story-004 / story-006). The
 * agent pushes each party member's own state under a caster_id; the HUD keeps ONE global indicator,
 * so it updates only for the local id. A push with no caster_id, or before the local id is known
 * (pre-SESSION_INIT), is treated as the local player's (single-player back-compat).
 */
function isEventForLocalPlayer(casterId: unknown): boolean {
  const localPlayerId = characterStore.getState().character?.playerId;
  return typeof casterId !== "string" || !localPlayerId || casterId === localPlayerId;
}

export function handleGameEvent(event: DataChannelEvent): void {
  switch (event.type) {
    case E.PLAY_SOUND:
      if (typeof event.sound_name === "string") {
        playSfx(event.sound_name);
      }
      break;

    case E.DICE_ROLL:
    case E.DICE_RESULT:
      playSfx("dice_roll");
      hapticDiceRoll();
      hudStore.getState().pushOverlay(
        "dice_result",
        {
          roll: event.roll,
          modifier: event.modifier,
          total: event.total,
          success: event.success,
          rollType: event.roll_type,
          narrative: event.narrative,
          // Forward the agent's dramatic flag (boolean | undefined) so the overlay can
          // gate its tumble-and-reveal on it (story-006). Absent until stories 004/005
          // emit it, so the overlay stays suppressed in the interim — accepted scarcity.
          dramatic: event.dramatic,
        },
        DICE_ROLL_TTL_MS,
      );
      if (_diceStingerTimer) clearTimeout(_diceStingerTimer);
      _diceStingerTimer = setTimeout(() => {
        _diceStingerTimer = null;
        playSfx(event.success ? "success_sting" : "fail_sting");
      }, DICE_STINGER_DELAY_MS);
      break;

    case E.SESSION_INIT:
      handleSessionInit(event);
      break;

    case E.LOCATION_CHANGED:
      if (typeof event.new_location === "string") {
        const locationName =
          typeof event.location_name === "string" ? event.location_name : event.new_location;
        const atmosphere = typeof event.atmosphere === "string" ? event.atmosphere : "";
        const region = typeof event.region === "string" ? event.region : "";
        const ambientSounds = typeof event.ambient_sounds === "string" ? event.ambient_sounds : "";
        const timeOfDay = typeof event.time_of_day === "string" ? event.time_of_day : "";
        sessionStore.getState().setLocationContext({
          locationId: event.new_location,
          locationName,
          atmosphere,
          region,
          tags: [],
          ambientSounds,
          timeOfDay,
        });
        characterStore.getState().updateLocation(event.new_location, locationName);
        const connections = Array.isArray(event.connections) ? (event.connections as string[]) : [];
        panelStore.getState().addVisitedLocation(event.new_location, connections);
      }
      break;

    case E.COMBAT_STARTED: {
      const ss = sessionStore.getState();
      if (
        typeof event.difficulty === "string" &&
        VALID_DIFFICULTIES.has(event.difficulty as CombatDifficulty)
      ) {
        ss.setCombatDifficulty(event.difficulty as CombatDifficulty);
      }
      ss.setCombat(true);
      playSfx("sword_clash");
      break;
    }

    case E.HOLLOW_CORRUPTION_CHANGED:
      if (typeof event.level === "number") {
        sessionStore
          .getState()
          .setCorruptionLevel(Math.max(0, Math.min(3, Math.floor(event.level))));
      }
      break;

    case E.SET_MUSIC_STATE:
      if (typeof event.music_state === "string") {
        if (VALID_MUSIC_STATES.has(event.music_state as MusicState)) {
          overrideMusicState(event.music_state as MusicState);
        } else {
          console.warn("[game-events] Invalid music_state:", event.music_state);
        }
      }
      break;

    case E.COMBAT_ENDED:
      sessionStore.getState().setCombat(false);
      hudStore.getState().clearCombatState();
      break;

    case E.COMBAT_UI_UPDATE: {
      const rawCombatants = Array.isArray(event.combatants) ? (event.combatants as unknown[]) : [];
      const combatants = rawCombatants
        .map(parseCombatant)
        .filter((c): c is Combatant => c !== null);
      const combatState: CombatTrackerState = {
        round: typeof event.round === "number" ? event.round : 1,
        combatants,
      };
      hudStore.getState().setCombatState(combatState);
      sessionStore.getState().setCombat(true);
      break;
    }

    case E.XP_AWARDED:
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

    case E.HP_CHANGED:
      if (typeof event.current === "number") {
        characterStore
          .getState()
          .updateHp(event.current, typeof event.max === "number" ? event.max : undefined);
      }
      break;

    case E.RESONANCE_CHANGED: {
      // HUD shows the qualitative state only; current/max are ignored. Unknown
      // states are dropped (fail-safe) rather than corrupting the tracker.
      // Multi-player (M14 story-004): the agent pushes each party member's own state under a
      // caster_id. The HUD keeps ONE global resonance tracker, so filter to the local player.
      if (
        isEventForLocalPlayer(event.caster_id) &&
        VALID_RESONANCE_STATES.has(event.state as ResonanceState)
      ) {
        hudStore.getState().setResonanceState(event.state as ResonanceState);
      }
      break;
    }

    case E.HOLLOW_ECHO_RESULT:
      // An Overreach cast tore the Veil. Flash the dramatic band overlay; only the
      // qualitative band crosses the wire (raw d20 stays server-side). An unknown
      // band is dropped (fail-safe) rather than rendering a blank overlay.
      if (VALID_HOLLOW_ECHO_BANDS.has(event.band as HollowEchoBand)) {
        hudStore.getState().pushOverlay("hollow_echo", { band: event.band }, HOLLOW_ECHO_TTL_MS);
      }
      break;

    case E.VEIL_WARD_CHANGED: {
      // Persistent glanceable zone affordance. Only a boolean toggles it; a
      // malformed payload leaves the ward state untouched (fail-safe).
      //
      // NO isEventForLocalPlayer filter, deliberately (story-008, scope_model.md §6). A Veil Ward
      // belongs to a SCOPE — a fight or a place — and halves every caster in it. Filtering to the
      // raiser would light one client while the other player's casts are silently halved. The
      // payload carries {scope_kind, scope_id, source} and no caster_id; there is nothing to filter
      // on. RESONANCE_CHANGED above keeps its filter because Resonance is per-caster. Do not
      // "restore consistency" here — that asymmetry is the fix.
      if (typeof event.active === "boolean") {
        hudStore.getState().setVeilWardActive(event.active);
      }
      break;
    }

    case E.SESSION_END: {
      const store = sessionStore.getState();
      if (typeof event.summary === "string") {
        const rawMoments = Array.isArray(event.story_moments)
          ? (event.story_moments as Record<string, unknown>[])
          : [];
        const storyMoments: StoryMoment[] = rawMoments.map((m) => ({
          momentKey: typeof m.moment_key === "string" ? m.moment_key : "",
          description: typeof m.description === "string" ? m.description : "",
          imageUrl: typeof m.image_url === "string" ? m.image_url : null,
        }));
        store.setSessionSummary({
          summary: event.summary,
          xpEarned: typeof event.xp_earned === "number" ? event.xp_earned : 0,
          itemsFound: Array.isArray(event.items_found) ? (event.items_found as string[]) : [],
          questProgress: Array.isArray(event.quest_progress)
            ? (event.quest_progress as string[])
            : [],
          duration: typeof event.duration === "number" ? event.duration : 0,
          nextHooks: Array.isArray(event.next_hooks) ? (event.next_hooks as string[]) : [],
          lastLocationId: store.locationContext?.locationId ?? "",
          storyMoments,
        });
        store.setPhase("summary");
      } else {
        store.setPhase("ended");
      }
      break;
    }

    case E.TRANSCRIPT_ENTRY: {
      const speaker = (event.speaker as "player" | "dm" | "npc" | "tool" | undefined) ?? "dm";
      const characterName = (event.character as string | undefined) ?? null;

      transcriptStore.getState().addEntry({
        speaker,
        character: characterName,
        emotion: (event.emotion as string | undefined) ?? null,
        text: typeof event.text === "string" ? event.text : "",
        timestamp: typeof event.timestamp === "number" ? event.timestamp : Date.now() / 1000,
      });

      // Show NPC portrait when an NPC speaks
      const ps = portraitStore.getState();
      if (speaker === "npc" && characterName) {
        const npcUrl = ps.npcPortraitMap[characterName];
        if (npcUrl) {
          ps.setActiveNpc(characterName, npcUrl);
        }
        // Show companion avatar for companion speech
        if (characterName === COMPANION_NAME && ps.companionPrimaryUrl) {
          ps.setCompanionVisible(true);
          if (_companionHideTimer) clearTimeout(_companionHideTimer);
          _companionHideTimer = setTimeout(() => {
            _companionHideTimer = null;
            portraitStore.getState().setCompanionVisible(false);
          }, 5000);
        }
      } else {
        // Different speaker — clear NPC portrait
        ps.clearActiveNpc();
      }
      break;
    }

    case E.ITEM_ACQUIRED:
      if (isEventForLocalPlayer(event.player_id)) {
        hudStore.getState().pushOverlay("item_acquired", {
          name: event.name,
          description: event.description,
          rarity: event.rarity,
          stats: event.stats,
          image_url: typeof event.image_url === "string" ? event.image_url : undefined,
        });
        playSfx("item_pickup");
        hapticItemAcquired();
      }
      break;

    case E.QUEST_UPDATE:
    case E.QUEST_UPDATED: {
      const questHud = hudStore.getState();
      // Completion transition: the server sends completed:true (not a `status` field) with an
      // empty objective. Show a "completed" overlay, drop the tracked HUD objective (never blank
      // it via setActiveObjective("")), and mark the quest done in the panel so it moves to the
      // COMPLETED section instead of lingering as an active quest with no objective.
      const isCompleted = event.completed === true;
      questHud.pushOverlay("quest_update", {
        questName: event.quest_name,
        objective: event.objective,
        status: isCompleted ? "completed" : event.status,
        stageName: event.stage_name,
      });
      if (isCompleted) {
        questHud.clearActiveObjective();
        if (typeof event.quest_id === "string") {
          panelStore.getState().completeQuest(event.quest_id);
        }
      } else {
        if (typeof event.quest_name === "string" && typeof event.objective === "string") {
          questHud.setActiveObjective({
            questName: event.quest_name,
            objective: event.objective,
            updatedAt: Date.now(),
          });
        }
        // Advance the quest in the panel store so the map target updates
        if (typeof event.quest_id === "string" && typeof event.new_stage === "number") {
          panelStore.getState().advanceQuest(event.quest_id, event.new_stage);
        }
      }
      playSfx("quest_sting");
      break;
    }

    case E.STATUS_EFFECT: {
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

    case E.CREATION_CARDS: {
      const rawCards = Array.isArray(event.cards) ? (event.cards as Record<string, unknown>[]) : [];
      const cards: CreationCard[] = rawCards.map((c) => ({
        id: typeof c.id === "string" ? c.id : "",
        title: typeof c.title === "string" ? c.title : "",
        description: typeof c.description === "string" ? c.description : "",
        category: typeof c.category === "string" ? c.category : "",
        imageUrl:
          typeof c.image_url === "string"
            ? resolveApiUrl(c.image_url, getApiBase(Constants))
            : undefined,
      }));
      hudStore.getState().setCreationCards(cards);
      break;
    }

    case E.CREATION_CARD_SELECTED:
      if (typeof event.value === "string") {
        hudStore.getState().setSelectedCreationCard(event.value);
      } else if (typeof event.card_id === "string") {
        hudStore.getState().setSelectedCreationCard(event.card_id);
      }
      break;

    case E.SPECIALIZATION_CHOICE: {
      // M2.3: the L5 fork. Set the dedicated specializationChoice state, which
      // OverlayManager renders as an interactive glanceable overlay (a supplement
      // to the DM voicing the fork). Each option must carry a non-empty string id
      // — it is the React key and the tap's published specialization_id. Options
      // without one are dropped; an event with no usable options is a no-op.
      // The milestoneId is the choice_id the tap echoes back to the agent's select
      // verb; without it every tap would be silently dropped agent-side, so a
      // choice missing it is a no-op (fail at the boundary, not on the tap).
      const milestoneId = typeof event.milestone_id === "string" ? event.milestone_id : "";
      const rawOptions = Array.isArray(event.options)
        ? (event.options as Record<string, unknown>[])
        : [];
      const options = rawOptions
        .filter((o) => typeof o.id === "string" && o.id.length > 0)
        .map((o) => ({
          id: o.id as string,
          name: typeof o.name === "string" ? o.name : "",
          description: typeof o.description === "string" ? o.description : "",
        }));
      if (!milestoneId || options.length === 0) break;
      hudStore.getState().setSpecializationChoice({ milestoneId, options });
      break;
    }

    case E.DIVINE_FAVOR_CHANGED:
      if (typeof event.new_level === "number") {
        const favorMax = typeof event.max === "number" ? event.max : 100;
        characterStore.getState().updateDivineFavor(event.new_level, favorMax);
        const favorAmount = typeof event.amount === "number" ? event.amount : 0;
        if (favorAmount > 0) {
          hudStore.getState().pushOverlay(
            "divine_favor",
            {
              amount: favorAmount,
              patronId: typeof event.patron_id === "string" ? event.patron_id : "",
              newLevel: event.new_level,
            },
            2000,
          );
        }
      }
      break;

    case E.PLAYER_PORTRAIT_READY:
      if (
        typeof event.url === "string" &&
        event.url.length <= 256 &&
        !event.url.includes("..") &&
        SAFE_API_PATH_RE.test(event.url) &&
        event.url.startsWith("/api/assets/")
      ) {
        characterStore.getState().updatePortraitUrl(event.url);
        portraitStore.getState().setPlayerPortraitUrl(event.url);
      }
      break;

    case E.INVENTORY_UPDATED:
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
