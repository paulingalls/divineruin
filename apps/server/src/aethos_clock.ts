import worldClock from "../../../content/world_clock.json";

export const AETHOS_EPOCH_MS = Date.parse(worldClock.epoch);
const HOUR_MS = 60 * 60 * 1_000;
const DAY_MS = 24 * HOUR_MS;
const FIRST_DAWN_MS = AETHOS_EPOCH_MS + worldClock.day_start_hour * HOUR_MS;

export function aethos_day(instant: Date): number {
  const instantMs = instant.getTime();
  if (!Number.isFinite(instantMs)) {
    throw new RangeError("Aethos day requires a valid Date");
  }
  return 1 + Math.floor((instantMs - FIRST_DAWN_MS) / DAY_MS);
}
