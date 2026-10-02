import { useEffect, useState } from "react";
import { useStore } from "zustand";
import { Pressable, View } from "react-native";
import { Participant, ParticipantKind } from "livekit-client";
import { handleGameEventMessage } from "@/audio/game-event-handler";
import { CombatTracker } from "@/components/hud/combat-tracker";
import { ThemedText } from "@/components/themed-text";
import { hudStore } from "@/stores/hud-store";

function IronResolveReplay() {
  const state = useStore(hudStore, (s) => s.combatState);
  const [step, setStep] = useState(0);
  useEffect(() => {
    hudStore.getState().reset();
    return () => hudStore.getState().reset();
  }, []);
  function next() {
    const sender = new Participant(
      "PA_kaelen",
      "dm",
      undefined,
      undefined,
      undefined,
      undefined,
      ParticipantKind.AGENT,
    );
    const event = {
      type: "combat_ui_update",
      round: step + 1,
      combatants: [
        {
          id: "kaelen_player",
          name: "Kaelen Faithful",
          isAlly: true,
          hpCurrent: 4,
          hpMax: 20,
          isActive: true,
          conditions:
            step === 0
              ? [{ type: "iron_resolve", duration: 1, source: "kaelen_iron_resolve", stacks: 1 }]
              : [],
        },
      ],
    };
    handleGameEventMessage({
      payload: new TextEncoder().encode(JSON.stringify(event)),
      from: sender,
    });
    setStep(step + 1);
  }
  return (
    <View style={{ flex: 1, padding: 24, paddingTop: 80 }}>
      <ThemedText>{`Combat update ${step}`}</ThemedText>
      <Pressable onPress={next}>
        <ThemedText>Next combat update</ThemedText>
      </Pressable>
      {state && <CombatTracker state={state} />}
    </View>
  );
}

export default function IronResolveTest() {
  return __DEV__ ? <IronResolveReplay /> : null;
}
