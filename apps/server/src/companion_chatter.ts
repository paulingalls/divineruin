// The catch-up feed's idle line, per companion. Ten authored lines each plus five
// companion-free ambient lines, written for the ear (CLAUDE.md content rules): short
// sentences, sound and smell before sight.
//
// Sable is non-verbal, so her ten carry presence without speech — weight shifting, a cold
// nose, a shadow that moves a beat late. companion_chatter.test.ts holds that to the
// content row's `non_verbal` flag, and every pronoun here to its `gender`.

export const AMBIENT_IDLE_CHATTER = [
  "A faint breeze stirs dust motes in the lamplight. Nothing stirs.",
  "Somewhere down the hall, someone drops a tankard. Then silence.",
  "Candlelight flickers across old maps pinned to the wall.",
  "A distant bell marks the hour. The guild hall settles deeper into silence.",
  "The floorboards creak as the building breathes in the wind.",
] as const;

export const COMPANION_IDLE_CHATTER: Record<string, readonly string[]> = {
  companion_kael: [
    "Kael is sharpening his blade and humming something off-key.",
    "The guild hall is quiet. Kael leans against the wall, watching the door.",
    "Kael traces old scars on the table with one finger, lost in thought.",
    "The hearth crackles low. Kael glances at the embers, then at the door.",
    "A cat winds between chair legs. Kael watches it with quiet amusement.",
    "Rain taps the shutters. Kael pulls his cloak tighter and waits.",
    "The smell of stew drifts from the kitchen. Kael's stomach growls.",
    "Kael flips a coin, catches it, flips it again. The wait continues.",
    "Kael mutters something about 'needing better boots' under his breath.",
    "Kael cleans his nails with a small knife, eyes half-closed.",
  ],
  companion_lira: [
    "Lira has three books open at once and one finger holding a fourth.",
    "Ink and hot wax. Lira is copying something out in her small, fast hand.",
    "Lira taps two fingers on the table, working through a problem she has not said aloud.",
    "A page turns. Then another, faster. Lira has found something.",
    "Lira holds a reagent vial up to the lamp and frowns at what the light does.",
    "The scratch of a nib. Lira crosses out a whole paragraph and starts again.",
    "Lira is arguing with the margin of a book. The book is losing.",
    "Lira closes her satchel, opens it again, and checks the same ledger twice.",
    "Somewhere a door bangs. Lira does not look up.",
    "Lira sharpens a quill down to nothing, thinking about the Veil.",
  ],
  companion_tam: [
    "Tam is up on the windowsill again, watching the roofline for no reason.",
    "Tam bounces on the balls of their feet, waiting for something to happen.",
    "A coin, a knife, a bootlace — Tam has taken half their kit apart to put it back.",
    "Tam is telling the room a story. The room left an hour ago.",
    "Tam counts the exits out loud and gets a different number each time.",
    "Boots on the stair, fast. Tam, going somewhere. Tam, coming back.",
    "Tam whistles four notes, stops, and starts them over.",
    "Tam has found a loose floorboard and will not leave it alone.",
    "Tam sharpens nothing, fixes nothing, and cannot sit still.",
    "Tam pulls their collar up against a draft that is not there.",
  ],
  companion_sable: [
    "Sable is a darker patch of dark under the bench, and only her ears move.",
    "Something warm and heavy settles across Sable's paws. She has claimed the fire.",
    "Sable's ears swivel toward the door a full second before the footsteps arrive.",
    "A cold nose, once, against the back of a hand. Then Sable is gone again.",
    "Sable shifts her weight, and the shadow under her shifts a moment late.",
    "The room's one candle gutters. Sable watches it die without blinking.",
    "Sable turns three times, drops, and does not sleep.",
    "A low sound in Sable's throat, barely there. Then nothing.",
    "Sable has taken the high shelf. From up there she can see the whole room.",
    "Sable's tail moves once across the floorboards, slow, and stops.",
  ],
};

/** The lines a given companion's player can draw: their own ten plus the five ambient. */
export function chatterPool(companionId: string): readonly string[] {
  const lines = COMPANION_IDLE_CHATTER[companionId];
  if (!lines) {
    throw new Error(`No idle chatter authored for ${companionId}`);
  }
  return [...lines, ...AMBIENT_IDLE_CHATTER];
}

/** A stable idle line for this player and this UTC hour, drawn from their companion's pool. */
export function getCompanionIdleChatter(playerId: string, companionId: string): string {
  const pool = chatterPool(companionId);
  const hour = new Date().getUTCHours();
  // Simple hash from playerId + hour to pick a chatter line
  let hash = hour;
  for (let i = 0; i < playerId.length; i++) {
    hash = (hash * 31 + playerId.charCodeAt(i)) | 0;
  }
  return pool[Math.abs(hash) % pool.length]!;
}
