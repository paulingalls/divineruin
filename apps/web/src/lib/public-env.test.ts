import { expect, test } from "bun:test";
import { join } from "node:path";

// The deploy env reaches the browser only through Bun.build's inlining (prerender.ts, env
// "PUBLIC_*"). Unit tests run under Bun, where `process` exists, so they cannot see a read that
// only works when `process` does. Each case builds the real module the way prerender does, in a
// child process started with the deploy env (Bun.build reads the env as of process start), and
// runs the bundle where `process` is undefined, as it is in a browser.

const CHILD = `
const [entrySource, scopeNames] = JSON.parse(process.env.DR_PUBLIC_ENV_CASE);
const { mkdtemp, writeFile } = await import("node:fs/promises");
const { tmpdir } = await import("node:os");
const { join } = await import("node:path");
const dir = await mkdtemp(join(tmpdir(), "dr-public-env-"));
await writeFile(join(dir, "entry.ts"), entrySource);
const result = await Bun.build({
  entrypoints: [join(dir, "entry.ts")], target: "browser", format: "iife", env: "PUBLIC_*",
});
if (!result.success) throw new AggregateError(result.logs, "bundle failed");
const code = await result.outputs[0].text();
const out = { beacons: [] };
const scope = {
  sink: out,
  window: { dispatchEvent: () => true },
  CustomEvent: class {},
  navigator: { sendBeacon: (url) => out.beacons.push(url) > 0 },
};
new Function("process", ...scopeNames, code)(undefined, ...scopeNames.map((n) => scope[n]));
await (await import("node:fs/promises")).rm(dir, { recursive: true, force: true });
console.log(JSON.stringify(out));
`;

async function inBrowser(
  entrySource: string,
  scopeNames: string[],
  env: Record<string, string>,
): Promise<{ base?: string; beacons: string[] }> {
  const base = { ...process.env };
  delete base.PUBLIC_API_URL;
  delete base.PUBLIC_ANALYTICS_URL;
  const child = Bun.spawn(["bun", "-e", CHILD], {
    env: { ...base, ...env, DR_PUBLIC_ENV_CASE: JSON.stringify([entrySource, scopeNames]) },
    stdout: "pipe",
    stderr: "pipe",
  });
  const [stdout, stderr, code] = await Promise.all([
    new Response(child.stdout).text(),
    new Response(child.stderr).text(),
    child.exited,
  ]);
  if (code !== 0) throw new Error(`browser bundle run failed: ${stderr}`);
  return JSON.parse(stdout.trim().split("\n").at(-1) as string) as {
    base?: string;
    beacons: string[];
  };
}

const api = JSON.stringify(join(import.meta.dir, "api.ts"));
const analytics = JSON.stringify(join(import.meta.dir, "analytics.ts"));
const apiEntry = `import { waitlistApiBase } from ${api}; sink.base = waitlistApiBase();`;
const beaconEntry = `import { trackEvent } from ${analytics}; trackEvent("probe");`;
const BEACON_SCOPE = ["sink", "window", "CustomEvent", "navigator"];

test("a deployed PUBLIC_API_URL reaches the browser bundle", async () => {
  const out = await inBrowser(apiEntry, ["sink"], { PUBLIC_API_URL: "https://api.example.test" });
  expect(out.base).toBe("https://api.example.test");
});

test("an unset PUBLIC_API_URL falls back without throwing in the browser", async () => {
  expect((await inBrowser(apiEntry, ["sink"], {})).base).toBe("http://localhost:3001");
});

test("a deployed PUBLIC_ANALYTICS_URL sends beacons from the browser bundle", async () => {
  const env = { PUBLIC_ANALYTICS_URL: "https://beacon.example.test/e" };
  expect((await inBrowser(beaconEntry, BEACON_SCOPE, env)).beacons).toEqual([
    "https://beacon.example.test/e",
  ]);
});

test("an unset PUBLIC_ANALYTICS_URL sends no beacon and does not throw", async () => {
  expect((await inBrowser(beaconEntry, BEACON_SCOPE, {})).beacons).toEqual([]);
});
