import { test, expect } from "bun:test";
import { resolvePrompt, PROMPT_TEMPLATES } from "./image-prompt-templates.ts";

test("resolvePrompt substitutes variables correctly", () => {
  const { prompt } = resolvePrompt("npc_portrait", {
    description: "an elderly female merchant",
    features: "a broad face, deep-set knowing eyes, and a hooded wool shawl",
  });
  expect(prompt).toContain("an elderly female merchant");
  expect(prompt).toContain("a broad face, deep-set knowing eyes, and a hooded wool shawl");
  expect(prompt).not.toContain("{{");
});

test("resolvePrompt works with no variables", () => {
  const { prompt } = resolvePrompt("companion_portrait_primary", {});
  expect(prompt).toContain("Ink wash portrait");
  expect(prompt).not.toContain("{{");
});

test("resolvePrompt throws on missing required variable", () => {
  expect(() => resolvePrompt("npc_portrait", { description: "a guard" })).toThrow(
    'Missing required variable "features"',
  );
});

test("resolvePrompt throws on unknown template ID", () => {
  expect(() => resolvePrompt("nonexistent_template", {})).toThrow("Unknown template");
});

test("all templates have consistent structure", () => {
  for (const [id, t] of Object.entries(PROMPT_TEMPLATES)) {
    expect(t.id).toBe(id);
    expect(t.promptText.length).toBeGreaterThan(50);
    expect(["3:4", "16:9", "1:1", "2:3", "9:16"]).toContain(t.aspectRatio);
    // Every variable slot must appear in the prompt text
    for (const slot of t.variableSlots) {
      expect(t.promptText).toContain(`{{${slot}}}`);
    }
  }
});

test("PROMPT_TEMPLATES has all 18 templates", () => {
  expect(Object.keys(PROMPT_TEMPLATES).length).toBe(18);
});
