import { sql } from "./db.ts";
import { logError } from "./env.ts";

interface DecisionOption {
  id: string;
  label: string;
}

interface FeedItemProgress {
  startTime: string;
  resolveAtEstimate: string;
  progressText: string | null;
  percentEstimate: number;
}

export interface FeedItem {
  id: string;
  type:
    | "resolved"
    | "pending_decision"
    | "in_progress"
    | "world_news"
    | "companion_idle"
    | "god_whisper";
  title: string;
  summary: string;
  timestamp: string;
  relativeTime: string;
  hasAudio: boolean;
  audioUrl: string | null;
  decisionOptions: DecisionOption[] | null;
  activityType: string | null;
  progress: FeedItemProgress | null;
}

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

function getRelativeTime(timestamp: string): string {
  const now = Date.now();
  const then = new Date(timestamp).getTime();
  const diffMs = now - then;
  const diffMinutes = Math.floor(diffMs / 60_000);

  if (diffMinutes < 1) return "just now";
  if (diffMinutes < 60) return `${diffMinutes}m ago`;

  const diffHours = Math.floor(diffMinutes / 60);
  if (diffHours < 24) return `${diffHours}h ago`;

  const diffDays = Math.floor(diffHours / 24);
  return `${diffDays}d ago`;
}

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

function str(val: unknown, fallback: string): string {
  return typeof val === "string" ? val : fallback;
}

function activityTitle(data: Record<string, unknown>): string {
  const type = data.activity_type;
  const params = (data.parameters ?? {}) as Record<string, unknown>;

  if (type === "crafting") {
    return str(params.result_item_name, "Crafting");
  }
  if (type === "training") {
    const stat = typeof params.stat === "string" ? params.stat : "";
    return stat ? `${stat.charAt(0).toUpperCase() + stat.slice(1)} Training` : "Training";
  }
  if (type === "companion_errand") {
    const errandType = typeof params.errand_type === "string" ? params.errand_type : "";
    return errandType
      ? `${errandType.charAt(0).toUpperCase() + errandType.slice(1)} Errand`
      : "Companion Errand";
  }
  return "Activity";
}

function pickProgressText(data: Record<string, unknown>): string | null {
  const stages = data.progress_stages as string[] | undefined;
  if (!stages || stages.length === 0) return null;

  const startTime = data.start_time as string;
  const resolveAt = data.resolve_at as string;
  const now = Date.now();
  const start = new Date(startTime).getTime();
  const end = new Date(resolveAt).getTime();

  if (end <= start) return stages[0] ?? null;

  const elapsed = now - start;
  const total = end - start;
  const pct = Math.min(1, Math.max(0, elapsed / total));

  const index = Math.min(Math.floor(pct * stages.length), stages.length - 1);
  return stages[index] ?? null;
}

function computeProgress(data: Record<string, unknown>): FeedItemProgress | null {
  const startTime = data.start_time as string | undefined;
  const resolveAt = data.resolve_at as string | undefined;
  if (!startTime || !resolveAt) return null;

  const now = Date.now();
  const start = new Date(startTime).getTime();
  const end = new Date(resolveAt).getTime();
  const total = end - start;
  const elapsed = now - start;

  return {
    startTime,
    resolveAtEstimate: resolveAt,
    progressText: pickProgressText(data),
    percentEstimate:
      total > 0 ? Math.min(100, Math.max(0, Math.round((elapsed / total) * 100))) : 0,
  };
}

function activityToFeedItem(id: string, data: Record<string, unknown>): FeedItem {
  const status = data.status as string;
  const hasDecisions =
    status === "resolved" &&
    Array.isArray(data.decision_options) &&
    (data.decision_options as unknown[]).length > 0;

  const timestamp = str(data.resolve_at, str(data.start_time, new Date().toISOString()));

  let type: FeedItem["type"];
  if (status === "in_progress") {
    type = "in_progress";
  } else if (hasDecisions) {
    type = "pending_decision";
  } else {
    type = "resolved";
  }

  const narrationText = data.narration_text as string | undefined;

  return {
    id,
    type,
    title: activityTitle(data),
    summary: narrationText
      ? narrationText.replace(/\[(?:NPC:[^\]]*|NARRATOR)\]\s*/g, "").slice(0, 200)
      : activityTitle(data),
    timestamp,
    relativeTime: getRelativeTime(timestamp),
    hasAudio: typeof data.narration_audio_url === "string",
    audioUrl: typeof data.narration_audio_url === "string" ? data.narration_audio_url : null,
    decisionOptions: hasDecisions ? (data.decision_options as DecisionOption[]) : null,
    activityType: typeof data.activity_type === "string" ? data.activity_type : null,
    progress: status === "in_progress" ? computeProgress(data) : null,
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
        AND data->>'status' IN ('resolved', 'in_progress')
      ORDER BY created_at DESC
    ` as Promise<{ id: string; data: unknown }[]>;

    const newsPromise = sql`
      SELECT id, data FROM world_news_items
      WHERE player_id = ${playerId}
        AND created_at > NOW() - INTERVAL '24 hours'
      ORDER BY created_at DESC
      LIMIT 5
    `.catch(() => [] as { id: string; data: unknown }[]) as Promise<
      { id: string; data: unknown }[]
    >;

    const whispersPromise = sql`
      SELECT id, data FROM god_whispers
      WHERE player_id = ${playerId}
        AND data->>'status' = 'pending'
      ORDER BY created_at DESC
    `.catch(() => [] as { id: string; data: unknown }[]) as Promise<
      { id: string; data: unknown }[]
    >;

    const [rows, newsRows, whisperRows] = await Promise.all([
      activitiesPromise,
      newsPromise,
      whispersPromise,
    ]);

    const items: FeedItem[] = [];

    for (const row of rows) {
      const data = (typeof row.data === "string" ? JSON.parse(row.data) : row.data) as Record<
        string,
        unknown
      >;
      items.push(activityToFeedItem(row.id, data));
    }

    for (const row of newsRows) {
      const data = (typeof row.data === "string" ? JSON.parse(row.data) : row.data) as Record<
        string,
        unknown
      >;
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
      const data = (typeof row.data === "string" ? JSON.parse(row.data) : row.data) as Record<
        string,
        unknown
      >;
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

    return Response.json({ items });
  } catch (err) {
    logError("[catchup] feed failed:", err);
    return Response.json({ error: "Internal server error" }, { status: 500 });
  }
}

// Re-export helpers for testing
export { getRelativeTime, getCompanionIdleChatter, activityToFeedItem };
