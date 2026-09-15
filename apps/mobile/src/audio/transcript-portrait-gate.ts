import { portraitStore } from "@/stores/portrait-store";

let companionHideTimer: ReturnType<typeof setTimeout> | null = null;

export function handleTranscriptPortraits(
  speaker: "player" | "dm" | "npc" | "tool",
  characterName: string | null,
): void {
  const portraits = portraitStore.getState();
  if (speaker === "npc" && characterName) {
    const npcPortrait = portraits.npcPortraitMap[characterName];
    if (npcPortrait) {
      portraits.setActiveNpc(npcPortrait.name, npcPortrait.url);
    } else {
      portraits.clearActiveNpc();
    }
    if (
      portraits.companionVoiceId &&
      characterName === portraits.companionVoiceId &&
      portraits.companionPrimaryUrl
    ) {
      portraits.setCompanionVisible(true);
      if (companionHideTimer) clearTimeout(companionHideTimer);
      companionHideTimer = setTimeout(() => {
        companionHideTimer = null;
        portraitStore.getState().setCompanionVisible(false);
      }, 5000);
    }
  } else {
    portraits.clearActiveNpc();
  }
}
