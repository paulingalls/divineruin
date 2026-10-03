import { describe, expect, test } from "bun:test";
import { assertMicrophoneTurns } from "../../scripts/verify-choir-encounter";

describe("Choir native microphone prerequisite", () => {
  const evidence = () => ({
    microphone_frames: 200,
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
    expect(() => assertMicrophoneTurns(evidence(), "mobile-current")).not.toThrow();
    for (const field of ["authenticated_turns", "commands", "receipts"] as const) {
      const faulty = evidence();
      faulty[field].pop();
      expect(() => assertMicrophoneTurns(faulty, "mobile-current")).toThrow();
    }
    const faulty = evidence();
    faulty.authenticated_turns[1].text = "capstone turn 1";
    expect(() => assertMicrophoneTurns(faulty, "mobile-current")).toThrow("distinct");
    faulty.authenticated_turns[1].text = "capstone turn 2";
    faulty.authenticated_turns[1].identity = "other";
    expect(() => assertMicrophoneTurns(faulty, "mobile-current")).toThrow("authenticated");
  });
  test("frame totals and an empty or unrelated error cannot certify commands", () => {
    expect(() => assertMicrophoneTurns({}, "mobile-current")).toThrow();
    for (const field of ["microphone_frames", "peak_amplitude"] as const) {
      const faulty = evidence();
      faulty[field] = 0;
      expect(() => assertMicrophoneTurns(faulty, "mobile-current")).toThrow();
    }
    for (const output of ["", "service failed"]) {
      const faulty = evidence();
      faulty.receipts[0].output = output;
      expect(() => assertMicrophoneTurns(faulty, "mobile-current")).toThrow("silenced");
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
      expect(() => assertMicrophoneTurns(faulty, "mobile-current")).toThrow();
    }
    const faulty = evidence();
    faulty.receipts[1].is_error = true;
    expect(() => assertMicrophoneTurns(faulty, "mobile-current")).toThrow("legal");
  });
});
