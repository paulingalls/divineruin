import { describe, expect, test } from "bun:test";
import {
  assertChoirEncounter,
  assertChoirFault,
  CHOIR_FAULTS,
  CHOIR_STEPS,
  assertMicrophoneTurns,
} from "../../scripts/verify-choir-encounter";

describe("Choir native microphone prerequisite", () => {
  const evidence = () => ({
    microphone_frames: 200,
    acoustic_sources: [
      { run_id: "current", turn: 1, source: "owned-acoustic-marker" },
      { run_id: "current", turn: 2, source: "owned-acoustic-marker" },
    ],
    peak_amplitude: 12000,
    authenticated_turns: [
      { identity: "mobile-current", text: "capstone turn 1", generation: 1 },
      { identity: "mobile-current", text: "capstone turn 2", generation: 1 },
    ],
    commands: ["declare_phase", "check"],
    receipts: [
      { name: "declare_phase", is_error: true, output: "silenced" },
      { name: "check", is_error: false, output: "save receipt" },
    ],
  });
  test("requires two independent authenticated turns and actual command receipts", () => {
    expect(() => assertMicrophoneTurns(evidence(), "mobile-current", "current")).not.toThrow();
    for (const field of ["authenticated_turns", "commands", "receipts"] as const) {
      const faulty = evidence();
      faulty[field].pop();
      expect(() => assertMicrophoneTurns(faulty, "mobile-current", "current")).toThrow();
    }
    const faulty = evidence();
    faulty.authenticated_turns[1].text = "capstone turn 1";
    expect(() => assertMicrophoneTurns(faulty, "mobile-current", "current")).toThrow("distinct");
    faulty.authenticated_turns[1].text = "capstone turn 2";
    faulty.authenticated_turns[1].identity = "other";
    expect(() => assertMicrophoneTurns(faulty, "mobile-current", "current")).toThrow(
      "authenticated",
    );
  });
  test("frame totals and an empty or unrelated error cannot certify commands", () => {
    expect(() => assertMicrophoneTurns({}, "mobile-current", "current")).toThrow();
    for (const field of ["microphone_frames", "peak_amplitude"] as const) {
      const faulty = evidence();
      faulty[field] = 0;
      expect(() => assertMicrophoneTurns(faulty, "mobile-current", "current")).toThrow();
    }
    for (const output of ["", "service failed"]) {
      const faulty = evidence();
      faulty.receipts[0].output = output;
      expect(() => assertMicrophoneTurns(faulty, "mobile-current", "current")).toThrow("silenced");
    }
    for (const defect of [
      "generation",
      "commands",
      "refusal-name",
      "refusal-error",
      "legal-name",
      "legal-output",
    ]) {
      const faulty = evidence();
      if (defect === "generation") faulty.authenticated_turns[1].generation = 0;
      if (defect === "commands") faulty.commands.reverse();
      if (defect === "refusal-name") faulty.receipts[0].name = "check";
      if (defect === "refusal-error") faulty.receipts[0].is_error = false;
      if (defect === "legal-name") faulty.receipts[1].name = "declare_phase";
      if (defect === "legal-output") faulty.receipts[1].output = " ";
      expect(() => assertMicrophoneTurns(faulty, "mobile-current", "current")).toThrow();
    }
    const faulty = evidence();
    faulty.receipts[1].is_error = true;
    expect(() => assertMicrophoneTurns(faulty, "mobile-current", "current")).toThrow("legal");
  });
  test("DM tones, unrelated bursts, stale and replayed acoustic input cannot certify commands", () => {
    for (const defect of ["missing", "dm-tone", "unrelated-burst", "stale", "replay"]) {
      const faulty = evidence();
      if (defect === "missing") faulty.acoustic_sources.pop();
      if (defect === "dm-tone" || defect === "unrelated-burst")
        faulty.acoustic_sources[0].source = defect;
      if (defect === "stale") faulty.acoustic_sources[0].run_id = "stale";
      if (defect === "replay") faulty.acoustic_sources[1].turn = 1;
      expect(() => assertMicrophoneTurns(faulty, "mobile-current", "current")).toThrow(
        "owned acoustic source",
      );
    }
  });
});

test("owned acoustic playback propagates process failure and cancellation", async () => {
  const { stimulateMicrophone } = await import("../../scripts/native-microphone-stimulus");
  const { OwnedProcesses } = await import("../../scripts/native-transport-processes");
  const { spyOn } = await import("bun:test");
  const scope = new OwnedProcesses();
  const spawned: string[][] = [];
  const spawn = spyOn(scope, "spawn").mockImplementation((command) => {
    spawned.push(command);
    return { exited: Promise.resolve(7) } as ReturnType<typeof scope.spawn>;
  });
  async function rejected(action: Promise<void>, message: string) {
    let failure: unknown;
    try {
      await action;
    } catch (error) {
      failure = error;
    }
    expect(failure).toBeInstanceOf(Error);
    expect((failure as Error).message).toContain(message);
  }
  try {
    await rejected(
      stimulateMicrophone(scope, "/owned", {
        controlPath: "/run/control.json",
        runId: "current",
        artifactDir: "/run",
      }),
      "status 7",
    );
    expect(spawned[0]).toEqual([
      "python3",
      "/owned/scripts/native-microphone-stimulus.py",
      "--control",
      "/run/control.json",
      "--run-id",
      "current",
      "--artifacts",
      "/run",
    ]);
    scope.controller.abort(new Error("cancelled"));
    spawn.mockRestore();
    await rejected(
      stimulateMicrophone(scope, "/owned", {
        controlPath: "/run/control.json",
        runId: "current",
        artifactDir: "/run",
      }),
      "cancelled",
    );
  } finally {
    spawn.mockRestore();
    await scope.close();
  }
});

test("prerequisite-only, omitted steps and unapplied native receipts cannot certify the encounter", () => {
  const evidence = () => ({
    acoustic_sources: Array.from({ length: 3 }, (_, i) => ({
      run_id: "current",
      turn: i + 1,
      source: "owned-acoustic-marker",
    })),
    authenticated_turns: Array.from({ length: 3 }, (_, i) => ({
      identity: "mobile-current",
      generation: 1,
      text: `capstone turn ${i + 1}`,
    })),
    commands: ["enter_mode", "declare_phase", "check"],
    receipts: [
      { name: "enter_mode", is_error: false, output: "entry" },
      { name: "declare_phase", is_error: true, output: "silenced" },
      { name: "check", is_error: false, output: "legal save" },
    ],
    checkpoints: Object.fromEntries(
      CHOIR_STEPS.map((step) => [
        step,
        step === "replay"
          ? { refused: true }
          : step === "destruction"
            ? { phase: "destroyed", owner: "choir_zone", xp: 100 }
            : {
                phase: ["entry", "cast-aura", "aura-break"].includes(step) ? "search" : "exposed",
                owner: "choir_zone",
                core_hp: 200,
                player_hp: 150,
              },
      ]),
    ),
    native_checkpoints: Object.fromEntries(
      CHOIR_STEPS.map((step) => [
        step,
        {
          player: "mobile-current",
          events: [{ type: "combat_started" }, { type: "combat_ended" }],
          combat_active: !["destruction", "replay"].includes(step),
          combat: ["destruction", "replay"].includes(step)
            ? null
            : {
                combatants: [
                  { id: "mobile-current", hpCurrent: 150, conditions: [{ type: "deafened" }] },
                  { id: "choir_zone", hpCurrent: 200, conditions: [] },
                ],
              },
          xp: 100,
          resonance: "stable",
        },
      ]),
    ),
  });
  expect(() => assertChoirEncounter(evidence(), "mobile-current", "current")).not.toThrow();
  expect(() => assertChoirEncounter({}, "mobile-current", "current")).toThrow(
    "complete authenticated",
  );
  for (const field of ["checkpoints", "native_checkpoints"] as const) {
    for (const step of CHOIR_STEPS) {
      const faulty = evidence();
      delete faulty[field][step];
      expect(() => assertChoirEncounter(faulty, "mobile-current", "current")).toThrow(
        "named Choir",
      );
    }
  }
  for (const defect of [
    "source",
    "identity",
    "generation",
    "text",
    "receipt",
    "events",
    "player",
    "combat",
    "hp",
    "deafened",
    "resonance",
    "award",
  ]) {
    const faulty = evidence();
    if (defect === "source") faulty.acoustic_sources[0].run_id = "stale";
    if (defect === "identity") faulty.authenticated_turns[0].identity = "other";
    if (defect === "generation") faulty.authenticated_turns[0].generation = 0;
    if (defect === "text") faulty.authenticated_turns[0].text = "capstone turn 2";
    if (defect === "receipt") faulty.receipts[0].output = "";
    if (defect === "events") faulty.native_checkpoints.entry.events = [];
    if (defect === "combat") faulty.native_checkpoints.entry.combat_active = false;
    if (defect === "hp") faulty.native_checkpoints.entry.combat!.combatants[0].hpCurrent = 140;
    if (defect === "deafened")
      faulty.native_checkpoints.deafened.combat!.combatants[0].conditions = [];
    if (defect === "resonance") faulty.native_checkpoints["cast-aura"].resonance = "";
    if (defect === "award") faulty.native_checkpoints.destruction.xp = 0;
    if (defect === "player") faulty.native_checkpoints.entry.player = "other";
    expect(() => assertChoirEncounter(faulty, "mobile-current", "current")).toThrow();
  }
});

test("native faults require their intended diagnostic and preserve entry or no-input evidence", () => {
  for (const fault of CHOIR_FAULTS) {
    const count = ["withhold-microphone", "dm-tone-only", "unrelated-burst"].includes(fault)
      ? 0
      : 1;
    const expected =
      {
        "deactivate-session": "missing separate authenticated turn 2 and gameplay receipt",
        "drop-gameplay": "missing Choir gameplay delivery: combat_started",
        "bypass-receiver": "native receiver did not apply combat",
        "skip-encounter": "missing named Choir encounter checkpoint",
      }[fault] ?? "missing separate authenticated turn 1 and gameplay receipt";
    const healthy = {
      fault,
      fault_failure: expected,
      microphone_frames: 100,
      acoustic_sources: count
        ? [{ run_id: "current", turn: 1, source: "owned-acoustic-marker" }]
        : [],
      authenticated_turns: count
        ? [{ identity: "mobile-current", generation: 1, text: "capstone turn 1" }]
        : [],
      receipts: count ? [{ name: "enter_mode", is_error: false, output: "actual entry" }] : [],
      commands: count ? ["enter_mode"] : [],
    };
    expect(() => assertChoirFault(healthy, "mobile-current", "current", fault)).not.toThrow();
    for (const wrong of ["service unavailable", "native build failed", ""])
      expect(() =>
        assertChoirFault({ ...healthy, fault_failure: wrong }, "mobile-current", "current", fault),
      ).toThrow("diagnostic");
    expect(() =>
      assertChoirFault({ ...healthy, microphone_frames: 0 }, "mobile-current", "current", fault),
    ).toThrow();
    expect(() =>
      assertChoirFault(
        {
          ...healthy,
          receipts: count ? [] : [{ name: "check", is_error: false, output: "unrelated" }],
        },
        "mobile-current",
        "current",
        fault,
      ),
    ).toThrow();
  }
});

test("SFX fault mutates the actual binding and restores other source edits", async () => {
  const { prepareChoirFault } = await import("../../scripts/choir-native-faults");
  const { mkdtemp, mkdir, readFile, writeFile, rm } = await import("node:fs/promises");
  const { tmpdir } = await import("node:os");
  const { join } = await import("node:path");
  const scratch = await mkdtemp(join(tmpdir(), "choir-sfx-fault-"));
  const path = join(scratch, "apps/mobile/src/audio/sfx-player.ts");
  try {
    await mkdir(join(scratch, "apps/mobile/src/audio"), { recursive: true });
    const original = await readFile(new URL("../audio/sfx-player.ts", import.meta.url), "utf8");
    await writeFile(path, original);
    const restore = await prepareChoirFault(scratch, "deactivate-session");
    expect(await readFile(path, "utf8")).toBe(
      original.replace("keepAudioSessionActive: true", "keepAudioSessionActive: false"),
    );
    await writeFile(path, (await readFile(path, "utf8")) + "\nother edit");
    await restore();
    expect(await readFile(path, "utf8")).toBe(original + "\nother edit");
    for (const malformed of ["", "keepAudioSessionActive: true keepAudioSessionActive: true"]) {
      await writeFile(path, malformed);
      let failure: unknown;
      try {
        await prepareChoirFault(scratch, "deactivate-session");
      } catch (error) {
        failure = error;
      }
      expect(failure).toBeInstanceOf(Error);
    }
  } finally {
    await rm(scratch, { recursive: true, force: true });
  }
});
