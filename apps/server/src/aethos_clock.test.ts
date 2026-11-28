import { expect, test } from "bun:test";

import cases from "../../../packages/shared/fixtures/aethos-day-cases.json";
import { aethos_day } from "./aethos_clock";

test("Aethos day cases have unique IDs and cover at least one instant", () => {
  expect(cases.length).toBeGreaterThan(0);
  expect(new Set(cases.map(({ id }) => id)).size).toBe(cases.length);
});

for (const { id, instant, expected } of cases) {
  test(id, () => expect(aethos_day(new Date(instant))).toBe(expected));
}
