import { test, expect } from "bun:test";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

// Bun resolves `--env-file` against the working directory the command ends up in,
// not the directory the script was launched from, and a path that resolves to
// nothing is silently ignored (exit 0, variables unset). So asserting that a
// command *carries* the flag proves nothing; every check below resolves the path.
const REPO_ROOT = resolve(import.meta.dir, "..");
const ROOT_ENV = resolve(REPO_ROOT, ".env");
const MARKER = "SERVICE_ENV_MARKER";

async function probe(
  args: string[],
  ambient: Record<string, string> = {},
): Promise<{ marker: string; exitCode: number }> {
  const root = await mkdtemp(join(tmpdir(), "service-env-"));
  try {
    const nested = join(root, "apps", "server");
    await mkdir(nested, { recursive: true });
    await writeFile(join(root, ".env"), `${MARKER}=from-env-file\n`);
    await writeFile(
      join(nested, "package.json"),
      JSON.stringify({ name: "probe", scripts: { probe: "bun probe.ts" } }),
    );
    await writeFile(join(nested, "probe.ts"), `console.log(process.env.${MARKER} ?? "");\n`);
    const child = Bun.spawn(["bun", ...args], {
      cwd: root,
      env: { ...Bun.env, [MARKER]: undefined, ...ambient },
      stdout: "pipe",
      stderr: "pipe",
    });
    const [stdout, exitCode] = await Promise.all([new Response(child.stdout).text(), child.exited]);
    return { marker: stdout.trim().split("\n").pop() ?? "", exitCode };
  } finally {
    await rm(root, { recursive: true, force: true });
  }
}

test("an env-file path reaches the subprocess only when it resolves under --cwd", async () => {
  const fromNested = await probe(["--env-file=../../.env", "run", "--cwd", "apps/server", "probe"]);
  expect(fromNested).toEqual({ marker: "from-env-file", exitCode: 0 });

  // The same file, named as the launcher sees it: silently loads nothing.
  const fromLauncher = await probe(["--env-file=.env", "run", "--cwd", "apps/server", "probe"]);
  expect(fromLauncher).toEqual({ marker: "", exitCode: 0 });
});

test("ambient variables win over the env file, and a missing file is not fatal", async () => {
  const shadowed = await probe(["--env-file=../../.env", "run", "--cwd", "apps/server", "probe"], {
    [MARKER]: "from-ambient",
  });
  expect(shadowed).toEqual({ marker: "from-ambient", exitCode: 0 });

  const absent = await probe(["--env-file=../../absent.env", "run", "--cwd", "apps/server", "probe"], {
    [MARKER]: "from-ambient",
  });
  expect(absent).toEqual({ marker: "from-ambient", exitCode: 0 });
});

// A command that opens Postgres or Valkey. Anything matching this must name an
// env file that resolves to the repo-root .env, or it picks up whatever service
// the ambient environment happens to point at.
const SERVICE_ENTRYPOINTS = [
  /scripts\/migrate\.ts/,
  /scripts\/test-all\.ts/,
  /seed_content\.py/,
  /\bagent\.py\b/,
  /\basync_worker\.py\b/,
  /\bpytest\b/,
  /src\/index\.ts/,
];
// Suites whose tests connect to the services (scripts/test_content.test.ts, the
// server db/invite lanes). The other workspaces' suites are pure.
const SERVICE_TEST_DIRS = ["scripts", "apps/server"];
// Floors: an empty manifest walk or an empty match set reads as green otherwise.
const MIN_MANIFESTS = 5;
const MIN_SERVICE_COMMANDS = 12;

type Manifest = { workspaces?: string[]; scripts?: Record<string, string> };

async function readManifest(relative: string): Promise<Manifest> {
  return (await Bun.file(join(REPO_ROOT, relative)).json()) as Manifest;
}

async function manifestPaths(): Promise<string[]> {
  const root = await readManifest("package.json");
  const paths = ["package.json"];
  for (const pattern of root.workspaces ?? []) {
    for await (const found of new Bun.Glob(`${pattern}/package.json`).scan({ cwd: REPO_ROOT })) {
      paths.push(found);
    }
  }
  return paths.sort();
}

function flagValue(segment: string, flag: string): string | null {
  return new RegExp(`${flag}(?:=|\\s+)(\\S+)`).exec(segment)?.[1] ?? null;
}

function testSuiteDir(segment: string, manifestDir: string): string | null {
  const tokens = segment.trim().split(/\s+/);
  const bun = tokens.indexOf("bun");
  const test = tokens.indexOf("test");
  if (bun === -1 || test < bun || tokens.includes("run")) return null;
  const cwd = flagValue(segment, "--cwd");
  if (cwd) return join(manifestDir, cwd);
  for (let i = test + 1; i < tokens.length; i++) {
    const token = tokens[i] ?? "";
    if (token === "--cwd") i++;
    else if (!token.startsWith("-")) return join(manifestDir, token);
  }
  return manifestDir;
}

function isServiceCommand(segment: string, manifestDir: string): boolean {
  if (SERVICE_ENTRYPOINTS.some((pattern) => pattern.test(segment))) return true;
  const suite = testSuiteDir(segment, manifestDir);
  return suite !== null && SERVICE_TEST_DIRS.some((dir) => suite === dir || suite.startsWith(`${dir}/`));
}

test("every service command loads the repo-root .env explicitly", async () => {
  const manifests = await manifestPaths();
  expect(manifests.length).toBeGreaterThanOrEqual(MIN_MANIFESTS);

  const checked: string[] = [];
  for (const manifest of manifests) {
    const manifestDir = join(manifest, "..");
    const scripts = (await readManifest(manifest)).scripts ?? {};
    for (const [name, command] of Object.entries(scripts)) {
      for (const segment of command.split("&&")) {
        if (!isServiceCommand(segment, manifestDir)) continue;
        const label = `${manifest} → ${name}: ${segment.trim()}`;
        const envFile = flagValue(segment, "--env-file");
        if (envFile === null) throw new Error(`no --env-file on a service command — ${label}`);
        const launchedIn = resolve(REPO_ROOT, manifestDir, flagValue(segment, "--cwd") ?? ".");
        if (resolve(launchedIn, envFile) !== ROOT_ENV) {
          throw new Error(`--env-file resolves to ${resolve(launchedIn, envFile)} — ${label}`);
        }
        checked.push(label);
      }
    }
  }
  expect(checked.length).toBeGreaterThanOrEqual(MIN_SERVICE_COMMANDS);
});
