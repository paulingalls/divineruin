import { test, expect } from "bun:test";
import { errandBusyLabel, errandDestinationPrompt } from "@/components/activity-launcher-strings";

// These two strings live in a .ts, not in activity-launcher.tsx, because this lane's RN mock
// omits View/Text — a .tsx is unimportable here, so a test against the component would close
// the site on nothing (reference_mobile_bun_tsx_imports).

test("errand strings name the assigned companion", () => {
  expect(errandBusyLabel("Sable", "Scouting Run")).toBe("Sable is on a Scouting Run");
  expect(errandDestinationPrompt("Sable")).toBe("Where should Sable go?");
});

test("every companion gets their own name, not Kael's", () => {
  for (const name of ["Kael", "Lira", "Tam", "Sable"]) {
    expect(errandBusyLabel(name, "Errand")).toBe(`${name} is on a Errand`);
    expect(errandDestinationPrompt(name)).toBe(`Where should ${name} go?`);
  }
});

test("a missing companion name degrades to a neutral noun, never to Kael", () => {
  expect(errandDestinationPrompt(null)).toBe("Where should your companion go?");
  expect(errandBusyLabel(null, "Scouting Run")).toBe("Your companion is on a Scouting Run");
});
