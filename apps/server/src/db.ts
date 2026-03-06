import { SQL } from "bun";
import { requireEnv } from "./env.ts";

export const sql = new SQL({
  url: requireEnv("DATABASE_URL"),
});
