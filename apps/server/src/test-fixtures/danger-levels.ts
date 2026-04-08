/**
 * Shared test fixture for destination danger levels.
 *
 * Mirrors the data backfilled in content/locations.json so unit tests can
 * exercise the validation/risk paths without going through the DB loader.
 */

import { setDestinationDangerLevels, type DangerLevel } from "../errand_risk.ts";

export function setupDangerLevelFixture(): void {
  setDestinationDangerLevels(
    new Map<string, DangerLevel>([
      ["millhaven", "safe"],
      ["millhaven_inn", "safe"],
      ["accord_guild_hall", "safe"],
      ["accord_market_square", "moderate"],
      ["accord_dockside", "moderate"],
      ["greyvale_ruins_entrance", "dangerous"],
    ]),
  );
}
