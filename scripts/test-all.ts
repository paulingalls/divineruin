// Runs the bun and python test suites concurrently and aggregates their
// exit codes. Exits non-zero if either lane fails (safe for pre-commit / CI).
// Output is captured per lane and printed on completion to keep the two
// streams from interleaving.

type Lane = { name: string; cmd: string[] };

const lanes: Lane[] = [
  { name: "bun (server + mobile)", cmd: ["bun", "run", "test"] },
  { name: "python", cmd: ["bun", "run", "test:python"] },
];

const results = await Promise.all(
  lanes.map(async (lane) => {
    const proc = Bun.spawn(lane.cmd, { stdout: "pipe", stderr: "pipe" });
    const [stdout, stderr, exitCode] = await Promise.all([
      new Response(proc.stdout).text(),
      new Response(proc.stderr).text(),
      proc.exited,
    ]);
    return { name: lane.name, stdout, stderr, exitCode };
  }),
);

for (const r of results) {
  console.log(`\n===== ${r.name} [${r.exitCode === 0 ? "PASS" : "FAIL"}] =====`);
  if (r.stdout.trim()) console.log(r.stdout.trimEnd());
  if (r.stderr.trim()) console.error(r.stderr.trimEnd());
}

const failed = results.filter((r) => r.exitCode !== 0);
if (failed.length > 0) {
  console.error(`\nTest suites failed: ${failed.map((r) => r.name).join(", ")}`);
  process.exit(1);
}
console.log("\nAll test suites passed.");
