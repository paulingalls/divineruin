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

test("PROMPT_TEMPLATES has all 21 templates", () => {
  expect(Object.keys(PROMPT_TEMPLATES).length).toBe(21);
});

test("race_portrait resolves correctly", () => {
  const { prompt } = resolvePrompt("race_portrait", {
    race_name: "Draethar",
    physical_features: "Large and powerful",
  });
  expect(prompt).toContain("Draethar");
  expect(prompt).toContain("Large and powerful");
  expect(prompt).not.toContain("{{");
});

test("class_illustration resolves correctly", () => {
  const { prompt } = resolvePrompt("class_illustration", {
    class_name: "Warrior",
    class_fantasy: "Front-line combatant",
  });
  expect(prompt).toContain("Warrior");
  expect(prompt).toContain("Front-line combatant");
  expect(prompt).not.toContain("{{");
});

test("patron_deity_card resolves correctly", () => {
  const { prompt, template } = resolvePrompt("patron_deity_card", {
    deity_name: "Veythar",
    deity_domain: "Knowledge",
  });
  expect(prompt).toContain("Veythar");
  expect(prompt).toContain("Knowledge");
  expect(template.accentColor).toBe("divine_gold");
  expect(prompt).not.toContain("{{");
});
