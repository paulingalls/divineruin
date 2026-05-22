// Runs the unit/integration test suites concurrently and aggregates their exit
// codes. Exits non-zero if any lane fails (safe for pre-commit / CI). Full output
// is captured per lane and printed on completion to keep the streams from
// interleaving; a periodic one-line heartbeat per lane shows live progress so a
// slow lane (python is the longer one) isn't a silent wait.
//
// The real-LLM acceptance lane is intentionally NOT here — it runs only at
// pre-push / sprint close (see ADR 0003) to control API cost. Run it explicitly
// with `bun run test:acceptance`.

type Lane = { name: string; cmd: string[] };
type Result = { name: string; stdout: string; stderr: string; exitCode: number };

const HEARTBEAT_MS = 15_000;

const lanes: Lane[] = [
  { name: "bun (server + mobile)", cmd: ["bun", "run", "test"] },
  { name: "python", cmd: ["bun", "run", "test:python"] },
];

async function runLane(lane: Lane): Promise<Result> {
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
  const status = r.exitCode === 0 ? "PASS" : "FAIL";
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
