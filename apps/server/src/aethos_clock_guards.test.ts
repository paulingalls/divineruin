import { expect, test } from "bun:test";

import { aethos_day } from "./aethos_clock";

test("Aethos day rejects an invalid Date", () => {
  expect(() => aethos_day(new Date(NaN))).toThrow("valid Date");
});
