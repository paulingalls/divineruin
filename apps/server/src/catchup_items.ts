import {
  computePercentComplete,
  type DecisionOption,
  type FeedItemProgress,
} from "@divineruin/shared";

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

export function getRelativeTime(timestamp: string): string {
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

export function str(val: unknown, fallback: string): string {
  return typeof val === "string" ? val : fallback;
}

function activityTitle(data: Record<string, unknown>): string {
  const type = data.activity_type;
  const params = (data.parameters ?? {}) as Record<string, unknown>;

  if (type === "crafting") {
    return str(params.result_item_name, "Crafting");
  }
  if (type === "training") {
    if (typeof params.name === "string") return params.name;
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

  return {
    startTime,
    resolveAtEstimate: resolveAt,
    progressText: pickProgressText(data),
    percentEstimate: computePercentComplete(startTime, resolveAt),
  };
}

export function activityToFeedItem(id: string, data: Record<string, unknown>): FeedItem {
  const status = data.status as string;
  const hasDecisions =
    status === "resolved" &&
    Array.isArray(data.decision_options) &&
    (data.decision_options as unknown[]).length > 0;

  const timestamp = str(data.resolve_at, str(data.start_time, new Date().toISOString()));
  const audioUrl = typeof data.narration_audio_url === "string" ? data.narration_audio_url : null;

  // 'resolving' is a transient worker-claim state — surface it as in_progress
  // so the HUD keeps showing the row while the LLM+TTS finish (10-30s window).
  const isInFlight = status === "in_progress" || status === "resolving";

  let type: FeedItem["type"];
  if (isInFlight) {
    type = "in_progress";
  } else if (hasDecisions) {
    type = "pending_decision";
  } else {
    type = "resolved";
  }

  return {
    id,
    type,
    title: activityTitle(data),
    summary: (data.narration_summary as string) || activityTitle(data),
    timestamp,
    relativeTime: getRelativeTime(timestamp),
    hasAudio: audioUrl !== null,
    audioUrl,
    decisionOptions: hasDecisions ? (data.decision_options as DecisionOption[]) : null,
    activityType: typeof data.activity_type === "string" ? data.activity_type : null,
    progress: isInFlight ? computeProgress(data) : null,
  };
}
