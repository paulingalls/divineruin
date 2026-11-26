type BunTask = {
  args: string[];
  owned: string[];
};

function directoryRun(name: string, args: string[], tests: Bun.Glob) {
  const unsupported = () => new Error(`${name}: unsupported Bun test command`);
  const test = args.indexOf("test");
  if (test < 1) return;
  // Wrapped tasks supply a second "bun" to the database clone runner.
  const bun = args.lastIndexOf("bun", test - 1);
  if (bun < 0 || (bun + 1 < test && !args[bun + 1]?.startsWith("-"))) return;
  if (
    args
      .slice(bun + 1, test)
      .some((arg) => arg !== "--no-env-file" && !arg.startsWith("--env-file="))
  ) {
    throw unsupported();
  }

  let cwd = ".";
  const ignores: Bun.Glob[] = [];
  const paths: string[] = [];
  const options = args.slice(test + 1).values();
  for (const arg of options) {
    if (arg === "--cwd" || arg.startsWith("--cwd=")) {
      cwd = arg === "--cwd" ? (options.next().value ?? "") : arg.slice("--cwd=".length);
    } else if (arg === "--path-ignore-patterns") {
      const pattern = options.next().value;
      if (!pattern || pattern.startsWith("-")) throw unsupported();
      ignores.push(new Bun.Glob(pattern));
    } else if (arg.startsWith("--path-ignore-patterns=")) {
      ignores.push(new Bun.Glob(arg.slice("--path-ignore-patterns=".length)));
    } else if (/^(?:\.\/)?[\w./-]+$/.test(arg) && !arg.startsWith("-")) {
      paths.push(arg);
    } else {
      throw unsupported();
    }
  }
  if (
    !/^(?:\.\/)?[\w.-]+(?:\/[\w.-]+)*$/.test(cwd) ||
    cwd.split("/").includes("..") ||
    paths.some((path) => path.split("/").includes(".."))
  ) {
    throw unsupported();
  }
  if (paths.length && paths.every((path) => tests.match(path))) return;
  const [directory] = paths;
  if (directory && (paths.length !== 1 || !directory.startsWith("./"))) throw unsupported();
  const cwdPrefix = pathPrefix(cwd);
  return { prefix: cwdPrefix + pathPrefix(directory ?? ""), cwdPrefix, ignores };
}

function pathPrefix(path: string) {
  const parts = path.split("/").filter((part) => part && part !== ".");
  return parts.length ? `${parts.join("/")}/` : "";
}

const config = (await Bun.file("proof.yaml").json()) as {
  inputs?: Record<string, unknown[]>;
  generate?: { inputs?: unknown[] };
};
const testFiles = config.inputs?.["bun-test-files"];
const pattern = testFiles?.[0];
if (
  typeof pattern !== "string" ||
  testFiles?.length !== 1 ||
  !config.generate?.inputs?.includes("$bun-test-files")
) {
  throw new Error("proof.yaml generate.inputs must include the bun-test-files glob");
}

const tasks = (await Bun.stdin.json()) as Record<string, BunTask>;
const tests = new Bun.Glob(pattern);
const candidates = [...tests.scanSync({ dot: false })]
  .filter((path) => !path.split("/").includes("node_modules"))
  .sort();
const missing: string[] = [];
for (const [name, { args, owned }] of Object.entries(tasks)) {
  const run = directoryRun(name, args, tests);
  if (!run) continue;
  const declared = new Set(owned);
  for (const path of candidates) {
    if (!path.startsWith(run.prefix) || declared.has(path)) continue;
    if (run.ignores.some((ignore) => ignore.match(path.slice(run.cwdPrefix.length)))) continue;
    missing.push(`${name}: unowned Bun test ${path}`);
  }
}
if (missing.length) throw new Error(missing.sort().join("\n"));
