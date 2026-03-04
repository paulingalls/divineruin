import { SQL } from "bun";

if (!Bun.env.DATABASE_URL) {
  throw new Error("DATABASE_URL is not set");
}

export const sql = new SQL({
  url: Bun.env.DATABASE_URL,
});
