/**
 * Cross-language enumeration bridge for the M22 audio-completeness capstone.
 *
 * Prints every key across the four mobile audio registries as one JSON object
 * to stdout, so the Python acceptance capstone
 * (apps/agent/tests/acceptance/test_m22_audio_completeness_capstone.py) can
 * assert registry <-> bundled-asset key-set equality per family.
 *
 * Run: `cd apps/mobile && bun scripts/emit-audio-registry-keys.ts`
 * The bunfig `[loader] ".mp3" = "file"` resolves the registries' require()
 * calls to path strings, so no test-preload / RN mocks are needed.
 */
import { knownSoundNames } from "@/audio/sound-registry";
import { knownSoundscapeNames, knownTextureNames } from "@/audio/soundscape-registry";
import { knownMusicStates } from "@/audio/music-registry";

const keys = {
  sound: knownSoundNames(),
  soundscape: knownSoundscapeNames(),
  texture: knownTextureNames(),
  music: knownMusicStates(),
};

console.log(JSON.stringify(keys));
