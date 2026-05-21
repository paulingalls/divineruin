// Runs the test suites concurrently and aggregates their exit codes. Exits
// non-zero if any lane fails (safe for pre-commit / CI). Full output is captured
// per lane and printed on completion to keep the streams from interleaving; a
// periodic one-line heartbeat per lane shows live progress in the meantime so a
// slow or hung lane (python is the longer one) isn't a silent wait.
//
// The acceptance lane needs Docker. REQUIRE_DOCKER=1 forces it to run (the
// lane's pytest fixture hard-fails if Docker is down); otherwise it is skipped
// cleanly when Docker isn't available, so `bun run test:all` stays usable
// without Docker.

type Lane = { name: string; cmd: string[]; optional?: boolean };
type Result = { name: string; stdout: string; stderr: string; exitCode: number; skipped?: boolean };

const requireDocker = process.env.REQUIRE_DOCKER === "1";
const HEARTBEAT_MS = 15_000;

const lanes: Lane[] = [
  { name: "bun (server + mobile)", cmd: ["bun", "run", "test"] },
  { name: "python", cmd: ["bun", "run", "test:python"] },
  { name: "acceptance (livekit)", cmd: ["bun", "run", "test:acceptance"], optional: true },
];

async function dockerAvailable(): Promise<boolean> {
  const proc = Bun.spawn(["docker", "info"], { stdout: "ignore", stderr: "ignore" });
  return (await proc.exited) === 0;
}

async function runLane(lane: Lane): Promise<Result> {
  if (lane.optional && !requireDocker && !(await dockerAvailable())) {
    return { name: lane.name, stdout: "", stderr: "", exitCode: 0, skipped: true };
  }
  const proc = Bun.spawn(lane.cmd, { stdout: "pipe", stderr: "pipe" });
  const startedAt = Date.now();
  const heartbeat = setInterval(() => {
    console.log(`... still running: ${lane.name} (${Math.round((Date.now() - startedAt) / 1000)}s)`);
  }, HEARTBEAT_MS);
  try {
    const [stdout, stderr, exitCode] = await Promise.all([
      new Response(proc.stdout).text(),
      new Response(proc.stderr).text(),
      proc.exited,
    ]);
    return { name: lane.name, stdout, stderr, exitCode };
  } finally {
    clearInterval(heartbeat);
  }
}

const results = await Promise.all(lanes.map(runLane));

for (const r of results) {
  const status = r.skipped ? "SKIPPED (no docker)" : r.exitCode === 0 ? "PASS" : "FAIL";
  console.log(`\n===== ${r.name} [${status}] =====`);
  if (r.stdout.trim()) console.log(r.stdout.trimEnd());
  if (r.stderr.trim()) console.error(r.stderr.trimEnd());
}

const failed = results.filter((r) => r.exitCode !== 0);
if (failed.length > 0) {
  console.error(`\nTest suites failed: ${failed.map((r) => r.name).join(", ")}`);
  process.exit(1);
}
console.log("\nAll test suites passed.");
