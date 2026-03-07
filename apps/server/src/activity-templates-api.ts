import { CRAFTING_RECIPES, TRAINING_PROGRAMS, ERRAND_TEMPLATES } from "./activity_templates.ts";

function formatDuration(minSec: number, maxSec: number): string {
  const minH = Math.round(minSec / 3600);
  const maxH = Math.round(maxSec / 3600);
  if (minH === maxH) return `${minH}h`;
  return `${minH}-${maxH}h`;
}

interface TemplateItem {
  id: string;
  name: string;
  duration: string;
  params: Record<string, unknown>;
}

interface TemplateGroup {
  type: string;
  label: string;
  items: TemplateItem[];
}

export function handleGetActivityTemplates(): Response {
  const groups: TemplateGroup[] = [
    {
      type: "crafting",
      label: "Crafting",
      items: Object.values(CRAFTING_RECIPES).map((r) => ({
        id: r.id,
        name: r.name,
        duration: formatDuration(r.duration_min_seconds, r.duration_max_seconds),
        params: {
          recipe_id: r.id,
          required_materials: r.required_materials,
          skill: r.skill,
          dc: r.dc,
        },
      })),
    },
    {
      type: "training",
      label: "Training",
      items: Object.values(TRAINING_PROGRAMS).map((p) => ({
        id: p.id,
        name: p.name,
        duration: formatDuration(p.duration_min_seconds, p.duration_max_seconds),
        params: {
          program_id: p.id,
          stat: p.stat,
          skill: p.skill,
        },
      })),
    },
    {
      type: "companion_errand",
      label: "Companion Errands",
      items: Object.values(ERRAND_TEMPLATES).map((e) => ({
        id: e.id,
        name: e.name,
        duration: formatDuration(e.duration_min_seconds, e.duration_max_seconds),
        params: {
          errand_type: e.id,
          valid_destinations: e.valid_destinations,
        },
      })),
    },
  ];

  return Response.json({ groups });
}
