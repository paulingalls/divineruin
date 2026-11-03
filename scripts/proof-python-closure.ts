import { readFileSync } from "node:fs";
import { pythonClosure } from "../node_modules/@pi-innovations/proof/src/python";

const paths = JSON.parse(readFileSync(0, "utf8")) as string[];
const roots = ["apps/agent", "apps/agent/tests", "scripts"];
const texts = new Map(paths.map((path) => [path, readFileSync(path, "utf8")]));
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
process.stdout.write(JSON.stringify(result));
