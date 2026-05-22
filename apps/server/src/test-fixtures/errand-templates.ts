/**
 * Shared test fixture for errand templates.
 *
 * Loads content/errand_templates.json directly at test setup time, then
 * populates the runtime map. File-driven to avoid drift between the content
 * JSON (the single shared source) and test data.
 */

import { setErrandTemplates, type ErrandTemplate } from "../activity_templates.ts";

const TEMPLATES_PATH = new URL("../../../../content/errand_templates.json", import.meta.url);

interface RawErrandTemplate {
  id: string;
  name: string;
  duration_min_seconds: number;
  duration_max_seconds: number;
  valid_destinations: string[];
  blocked_companions: string[];
}

let cachedTemplates: Map<string, ErrandTemplate> | null = null;

async function loadFixtureData(): Promise<void> {
  if (cachedTemplates) return;
  const raw = (await Bun.file(TEMPLATES_PATH).json()) as RawErrandTemplate[];
  cachedTemplates = new Map(
    raw.map((t) => [
      t.id,
      {
        id: t.id,
        name: t.name,
        activity_type: "companion_errand" as const,
        duration_min_seconds: t.duration_min_seconds,
        duration_max_seconds: t.duration_max_seconds,
        required_params: ["destination"],
        valid_destinations: t.valid_destinations,
        blocked_companions: t.blocked_companions,
      },
    ]),
  );
}

// Preload at module import so setupErrandTemplatesFixture can stay sync
await loadFixtureData();

export function setupErrandTemplatesFixture(): void {
  if (!cachedTemplates) {
    throw new Error("Errand templates fixture data not loaded");
  }
  setErrandTemplates(cachedTemplates);
}
