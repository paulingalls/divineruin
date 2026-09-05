import { sql } from "./db.ts";
import { parseJsonb } from "./parse-jsonb.ts";
import { logError, logDiag } from "./env.ts";
import {
  computePercentComplete,
  type DecisionOption,
  type FeedItemProgress,
} from "@divineruin/shared";
import { getMidpointDecision } from "./training_state_machine.ts";
import { activityToFeedItem, getRelativeTime, str, type FeedItem } from "./catchup_items.ts";

const COMPANION_IDLE_CHATTER = [
  "Kael is sharpening his blade and humming something off-key.",
  "The guild hall is quiet. Kael leans against the wall, watching the door.",
  "A faint breeze stirs dust motes in the lamplight. Nothing stirs.",
  "Somewhere down the hall, someone drops a tankard. Then silence.",
  "Kael traces old scars on the table with one finger, lost in thought.",
  "The hearth crackles low. Kael glances at the embers, then at the door.",
  "A cat winds between chair legs. Kael watches it with quiet amusement.",
  "Rain taps the shutters. Kael pulls his cloak tighter and waits.",
  "The smell of stew drifts from the kitchen. Kael's stomach growls.",
  "Kael flips a coin, catches it, flips it again. The wait continues.",
  "Candlelight flickers across old maps pinned to the wall.",
  "Kael mutters something about 'needing better boots' under his breath.",
  "A distant bell marks the hour. The guild hall settles deeper into silence.",
  "Kael cleans his nails with a small knife, eyes half-closed.",
  "The floorboards creak as the building breathes in the wind.",
];

function getCompanionIdleChatter(playerId: string): string {
  const hour = new Date().getUTCHours();
  // Simple hash from playerId + hour to pick a chatter line
  let hash = hour;
  for (let i = 0; i < playerId.length; i++) {
    hash = (hash * 31 + playerId.charCodeAt(i)) | 0;
  }
  const index = Math.abs(hash) % COMPANION_IDLE_CHATTER.length;
  return COMPANION_IDLE_CHATTER[index]!;
}

interface TrainingRow {
  id: string;
  activity_type: string;
  state: string;
  data: Record<string, unknown>;
  transition_at: string | null;
  created_at: string;
  updated_at: string;
}

function trainingToFeedItem(row: TrainingRow): FeedItem {
  const data = parseJsonb(row.data);
  const programName = str(data.program_name, "Training");
  const transitionAt = row.transition_at ?? undefined;

  let type: FeedItem["type"];
  let decisionOptions: DecisionOption[] | null = null;
  let progress: FeedItemProgress | null = null;

  if (row.state === "running_first_half" || row.state === "running_second_half") {
    type = "in_progress";
    const startTime = row.state === "running_first_half" ? row.created_at : row.updated_at;
    if (startTime && transitionAt) {
      progress = {
        startTime,
        resolveAtEstimate: transitionAt,
        progressText: null,
        percentEstimate: computePercentComplete(startTime, transitionAt),
      };
    }
  } else if (row.state === "awaiting_decision") {
    type = "pending_decision";
    const decision = getMidpointDecision(row.activity_type);
    decisionOptions = decision.options;
  } else {
    type = "resolved";
  }

  const timestamp = transitionAt ?? row.updated_at;
  const audioUrl = typeof data.narration_audio_url === "string" ? data.narration_audio_url : null;

  return {
    id: row.id,
    type,
    title: programName,
    summary: (data.narration_text as string) || programName,
    timestamp,
    relativeTime: getRelativeTime(timestamp),
    hasAudio: audioUrl !== null,
    audioUrl,
    decisionOptions,
    activityType: "training",
    progress,
  };
}

const DEITY_DISPLAY_NAMES: Record<string, string> = {
  kaelen: "Kaelen, the Ironhand",
  syrath: "Syrath, the Veiled",
  veythar: "Veythar, the Unbound",
  mortaen: "Mortaen, the Still",
  thyra: "Thyra, the Thornmother",
  aelora: "Aelora, the Hearthkeeper",
  valdris: "Valdris, the Unyielding",
  nythera: "Nythera, the Drifting Star",
  orenthel: "Orenthel, the Dawnbearer",
  zhael: "Zhael, the Weaver",
};

// Sort priority: god_whisper/pending_decision (0), resolved (1), in_progress (2), world_news (3), companion_idle (4)
const TYPE_SORT_ORDER: Record<FeedItem["type"], number> = {
  god_whisper: 0,
  pending_decision: 0,
  resolved: 1,
  in_progress: 2,
  world_news: 3,
  companion_idle: 4,
};

export async function handleGetCatchUpFeed(_req: Request, playerId: string): Promise<Response> {
  try {
    // Run all queries in parallel
    const activitiesPromise = sql`
      SELECT id, data FROM async_activities
      WHERE player_id = ${playerId}
        AND data->>'status' IN ('resolved', 'in_progress', 'resolving')
      ORDER BY created_at DESC
      LIMIT 20
    ` as Promise<{ id: string; data: unknown }[]>;

    const newsPromise = sql`
      SELECT id, data FROM world_news_items
      WHERE player_id = ${playerId}
        AND created_at > NOW() - INTERVAL '24 hours'
      ORDER BY created_at DESC
      LIMIT 5
    `.catch((err) => {
      logError("[catchup] world_news query failed:", err);
      return [] as { id: string; data: unknown }[];
    }) as Promise<{ id: string; data: unknown }[]>;

    const whispersPromise = sql`
      SELECT id, data FROM god_whispers
      WHERE player_id = ${playerId}
        AND data->>'status' = 'pending'
      ORDER BY created_at DESC
    `.catch((err) => {
      logError("[catchup] god_whispers query failed:", err);
      return [] as { id: string; data: unknown }[];
    }) as Promise<{ id: string; data: unknown }[]>;

    const trainingPromise = sql`
      SELECT id, activity_type, state, data, transition_at, created_at, updated_at
      FROM training_activities
      WHERE player_id = ${playerId}
        AND state IN ('running_first_half', 'running_second_half', 'awaiting_decision', 'complete')
        AND (state != 'complete' OR updated_at > NOW() - INTERVAL '24 hours')
      ORDER BY created_at DESC
      LIMIT 20
    `.catch((err) => {
      logError("[catchup] training_activities query failed:", err);
      return [] as TrainingRow[];
    }) as Promise<TrainingRow[]>;

    const [rows, newsRows, whisperRows, trainingRows] = await Promise.all([
      activitiesPromise,
      newsPromise,
      whispersPromise,
      trainingPromise,
    ]);

    const items: FeedItem[] = [];

    for (const row of rows) {
      const data = parseJsonb(row.data);
      items.push(activityToFeedItem(row.id, data));
    }

    for (const row of trainingRows) {
      items.push(trainingToFeedItem(row));
    }

    for (const row of newsRows) {
      const data = parseJsonb(row.data);
      const ts = str(data.created_at, new Date().toISOString());
      items.push({
        id: row.id,
        type: "world_news",
        title: str(data.title, "World News"),
        summary: str(data.summary, ""),
        timestamp: ts,
        relativeTime: getRelativeTime(ts),
        hasAudio: typeof data.audio_url === "string",
        audioUrl: typeof data.audio_url === "string" ? data.audio_url : null,
        decisionOptions: null,
        activityType: null,
        progress: null,
      });
    }

    for (const row of whisperRows) {
      const data = parseJsonb(row.data);
      const deityId = str(data.deity_id, "unknown");
      const displayName = DEITY_DISPLAY_NAMES[deityId] ?? deityId;
      const narration = str(data.narration_text, "");
      const audioUrl = typeof data.audio_url === "string" ? data.audio_url : null;
      items.push({
        id: row.id,
        type: "god_whisper",
        title: displayName,
        summary: narration.slice(0, 200),
        timestamp: new Date().toISOString(),
        relativeTime: "now",
        hasAudio: audioUrl !== null,
        audioUrl,
        decisionOptions: null,
        activityType: null,
        progress: null,
      });
    }

    // Sort by type priority
    items.sort((a, b) => TYPE_SORT_ORDER[a.type] - TYPE_SORT_ORDER[b.type]);

    // If no resolved/pending items, add companion idle chatter
    const hasActionable = items.some(
      (i) => i.type === "pending_decision" || i.type === "resolved" || i.type === "god_whisper",
    );
    if (!hasActionable) {
      items.push({
        id: `idle_${Date.now()}`,
        type: "companion_idle",
        title: "Companion",
        summary: getCompanionIdleChatter(playerId),
        timestamp: new Date().toISOString(),
        relativeTime: "now",
        hasAudio: false,
        audioUrl: null,
        decisionOptions: null,
        activityType: null,
        progress: null,
      });
    }

    logDiag("catchup.feed", () => ({
      playerId,
      total: items.length,
      byType: items.reduce<Record<string, number>>((acc, i) => {
        acc[i.type] = (acc[i.type] ?? 0) + 1;
        return acc;
      }, {}),
      ids: items.map((i) => i.id),
      activityRows: rows.length,
      trainingRows: trainingRows.length,
    }));

    return Response.json({ items });
  } catch (err) {
    logError("[catchup] feed failed:", err);
    // Structured diag on the 500 path too (items is out of scope here): a flake
    // that surfaces as a hard failure — e.g. the un-.catch'd async_activities
    // query timing out — gets the same greppable [diag] line, tying the failure
    // to a playerId, not just logError's free-text message.
    logDiag("catchup.feed.error", () => ({
      playerId,
      error: err instanceof Error ? err.message : String(err),
    }));
    return Response.json({ error: "Internal server error" }, { status: 500 });
  }
}

// Re-export helpers for testing
export { getCompanionIdleChatter };
