import { authStore } from "@/stores/auth-store";
import { characterStore } from "@/stores/character-store";
import { panelStore } from "@/stores/panel-store";

export interface PatronAbility {
  id: string;
  name: string;
  tier: "Acknowledged" | "Devoted" | "Exalted";
  recharge: "always" | "short_rest" | "long_rest" | "per_session";
  status: "active" | "pending";
  eligible: boolean;
  available: boolean;
  spent: boolean;
  reason: string | null;
  state: "ready" | "spent" | "locked";
}
export interface PatronSnapshot {
  patron_revision: number;
  player_id: string;
  divine_favor: { patron: string; level: number; max: number } | null;
  abilities: PatronAbility[];
}
const text = (v: unknown): v is string => typeof v === "string" && v.trim().length > 0;

export function parsePatronSnapshot(value: unknown): PatronSnapshot {
  const p = value as PatronSnapshot | null;
  const f = p?.divine_favor;
  if (
    !p ||
    !text(p.player_id) ||
    !Number.isSafeInteger(p.patron_revision) ||
    p.patron_revision < 0 ||
    (f !== null &&
      (!f ||
        !text(f.patron) ||
        !Number.isInteger(f.level) ||
        !Number.isInteger(f.max) ||
        f.max <= 0 ||
        f.level < 0 ||
        f.level > f.max)) ||
    !Array.isArray(p.abilities)
  )
    throw new Error("Invalid patron snapshot");
  if (f === null && p.abilities.length) throw new Error("Abilities require a patron");
  for (const row of p.abilities as (PatronAbility | null)[]) {
    if (
      !row ||
      !text(row.id) ||
      !text(row.name) ||
      !["Acknowledged", "Devoted", "Exalted"].includes(row.tier) ||
      !["always", "short_rest", "long_rest", "per_session"].includes(row.recharge) ||
      !["active", "pending"].includes(row.status) ||
      !["ready", "spent", "locked"].includes(row.state) ||
      [row.eligible, row.available, row.spent].some((v) => typeof v !== "boolean") ||
      (row.reason !== null && typeof row.reason !== "string")
    )
      throw new Error("Invalid patron ability");
  }
  return p;
}

export function acceptPatronSnapshot(value: unknown): PatronSnapshot | null {
  try {
    return parsePatronSnapshot(value);
  } catch (error) {
    console.warn("[game-events] Invalid patron snapshot:", error);
    return null;
  }
}

export function rememberPatronSnapshot(snapshot: PatronSnapshot): PatronSnapshot {
  const previous = panelStore.getState().patronSnapshot;
  if (
    previous?.player_id === snapshot.player_id &&
    previous.patron_revision >= snapshot.patron_revision
  )
    return previous;
  panelStore.setState({ patronSnapshot: snapshot });
  return snapshot;
}

export function handlePatronAbilitiesUpdated(value: unknown): void {
  const snapshot = acceptPatronSnapshot(value);
  const local = authStore.getState().playerId ?? characterStore.getState().character?.playerId;
  if (!snapshot || !local || snapshot.player_id !== local) return;
  const latest = rememberPatronSnapshot(snapshot);
  const detail = panelStore.getState().characterDetail;
  if (detail)
    panelStore.getState().setCharacterDetail({
      ...detail,
      divineFavor: latest.divine_favor,
      abilities: latest.abilities,
    });
}
