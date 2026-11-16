// Inventory: db_content_queries, recipes, materials, pricing_queries,
// quality_outcomes and recipe_slots own the content keys; player/session keys stay live.
const patterns = [
  "location:*",
  "locations:all",
  "faction:*",
  "npc:*",
  "item:*",
  "material_definition:*",
  "quest:*",
  "scene:*",
  "encounter:*",
  "loot_table:*",
  "training_program:*",
  "training_programs:all",
  "errand_template:*",
  "errand_templates:all",
  "recipe:*",
  "recipes:all",
  "material:*",
  "materials:all",
  "pricing:*",
  "quality_outcome:*",
  "recipe_slots:all",
];
const prefix = process.env.CONTENT_CACHE_PREFIX ?? "";
if (!/^[a-zA-Z0-9:_-]*$/.test(prefix)) throw new Error("Invalid CONTENT_CACHE_PREFIX");
const url = process.env.REDIS_URL;
if (!url) throw new Error("REDIS_URL is required for production content-cache invalidation");
const redis = new Bun.RedisClient(url, { connectionTimeout: 1000, autoReconnect: false });
try {
  for (const pattern of patterns) {
    let cursor = "0";
    do {
      const [next, keys] = await redis.scan(cursor, "MATCH", prefix + pattern, "COUNT", 500);
      if (keys.length) await redis.del(...keys);
      cursor = next;
    } while (cursor !== "0");
  }
  console.log("Valkey content caches invalidated");
} catch {
  console.error("Valkey content-cache invalidation failed");
  process.exitCode = 1;
} finally {
  redis.close();
}
