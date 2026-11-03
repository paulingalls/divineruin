import { pythonClosure } from "../node_modules/@pi-innovations/proof/src/python";

const paths = (await Bun.stdin.json()) as string[];
const roots = ["apps/agent", "apps/agent/tests", "scripts"];
const texts = new Map<string, string>();
for (const path of paths) texts.set(path, await Bun.file(path).text());
const source = {
  paths,
  read: (path: string) => texts.get(path),
  mode: (path: string) => (texts.has(path) ? "100644" : undefined),
};
const result = Object.fromEntries(
  paths
    .filter((path) => path.includes("/acceptance/") || path.endsWith("/conftest.py"))
    .map((entry) => {
      const closure = pythonClosure(entry, source, roots);
      // Stop traversal after one hop while retaining proof's import resolution.
      const direct = pythonClosure(
        entry,
        {
          ...source,
          read: (path: string) => (path === entry ? texts.get(path) : ""),
        },
        roots,
      );
      return [
        entry,
        {
          closure: [...closure.paths].sort(),
          direct: [...direct.paths].filter((path) => path !== entry).sort(),
          reason: closure.reason,
        },
      ];
    }),
);
await Bun.write(Bun.stdout, JSON.stringify(result));
