import { existsSync, writeSync } from "node:fs";
import { resolve } from "node:path";

const root = resolve(import.meta.dir, "../../..");
const reported = new WeakSet<object>();

function frames(stack: string | undefined): string[] {
  return (stack ?? "")
    .split("\n")
    .flatMap((line) => {
      const match = line.match(/^\s+at (?:[A-Za-z0-9_$.[\]<> ]+ \()?([^\s()?]+):(\d+):(\d+)\)?$/);
      if (!match) return [];
      const [, file, row, column] = match;
      if (!file?.startsWith(`${root}/`) || (file !== `${root}/[eval]` && !existsSync(file)))
        return [];
      return [`${file.slice(root.length + 1)}:${row}:${column}`];
    })
    .slice(-50);
}

export function errorLine(
  boundary: "Server request failed" | "Server fatal",
  error: unknown,
): void {
  if (typeof error === "object" && error !== null) {
    if (reported.has(error)) return;
    reported.add(error);
  }
  const name =
    error instanceof Error && /^[A-Za-z_$][A-Za-z0-9_$.]*$/.test(error.name)
      ? `: ${error.name}`
      : "";
  const origin = frames(error instanceof Error ? error.stack : undefined);
  writeSync(
    2,
    JSON.stringify({
      service: "server",
      time: new Date().toISOString(),
      message: boundary + name,
      stack: (origin.length ? origin : frames(new Error().stack)).join("\n"),
    }) + "\n",
  );
}

process.on("uncaughtExceptionMonitor", (error) => errorLine("Server fatal", error));
