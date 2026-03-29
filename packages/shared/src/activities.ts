/** Activity types that can be started by a player. */
export type ActivityType = "crafting" | "training" | "companion_errand";

/** Percentage complete between two timestamps. */
export function computePercentComplete(startTime: string, resolveAt: string): number {
  const now = Date.now();
  const start = new Date(startTime).getTime();
  const end = new Date(resolveAt).getTime();
  const total = end - start;
  if (total <= 0) return 100;
  return Math.min(100, Math.max(0, Math.round(((now - start) / total) * 100)));
}

/** Convert a snake_case identifier to Title Case display name. */
export function displayName(id: string): string {
  return id
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

// --- API response types shared between server and client ---

export interface MaterialRequirement {
  itemId: string;
  name: string;
  required: number;
  owned: number;
}

export interface ActiveStatus {
  startTime: string;
  resolveAtEstimate: string;
  percentEstimate: number;
}

export interface TemplateItem {
  id: string;
  name: string;
  duration: string;
  params: Record<string, unknown>;
  materials: MaterialRequirement[] | null;
  active: ActiveStatus | null;
}

export interface TemplateGroup {
  type: string;
  label: string;
  items: TemplateItem[];
}

export interface DecisionOption {
  id: string;
  label: string;
}

export interface FeedItemProgress {
  startTime: string;
  resolveAtEstimate: string;
  progressText: string | null;
  percentEstimate: number;
}
