const NAMED_INTEGRATIONS = new Set(["hollow_choir", "hollow_still", "hollow_architect"]);

export function validateEncounterReferences(
  encounter: unknown,
  creatureIds?: ReadonlySet<string>,
  npcIds?: ReadonlySet<string>,
): void {
  if (!encounter || typeof encounter !== "object") throw new Error("encounter must be an object");
  const row = encounter as Record<string, unknown>;
  const label = `encounter '${String(row.id)}'`;
  const level = row.recommended_party_level;
  if (typeof level !== "number" || !Number.isInteger(level) || level < 1 || level > 20)
    throw new Error(`${label}: recommended_party_level must be an integer 1-20`);
  if (Object.hasOwn(row, "recommended_party_size")) {
    const size = row.recommended_party_size;
    if (typeof size !== "number" || !Number.isInteger(size) || size < 1)
      throw new Error(`${label}: recommended_party_size must be a positive integer`);
  }
  if (!Array.isArray(row.enemies) || !row.enemies.length)
    throw new Error(`${label}: enemies must be a nonempty list`);
  const seen = new Set<string>();
  for (const [index, value] of row.enemies.entries()) {
    if (!value || typeof value !== "object" || Array.isArray(value))
      throw new Error(`${label} enemy ${index}: expected reference object`);
    const enemy = value as Record<string, unknown>;
    const context = `${label} enemy '${typeof enemy.id === "string" ? enemy.id : index}'`;
    for (const field of ["id", "creature_id", "role"]) {
      if (typeof enemy[field] !== "string" || !enemy[field].trim())
        throw new Error(`${context}: ${field} must be a nonempty string`);
    }
    const extra = Object.keys(enemy).filter((key) => !["id", "creature_id", "role"].includes(key));
    if (extra.length) throw new Error(`${context}: forbidden reference fields ${extra.join(", ")}`);
    const id = enemy.id as string;
    if (seen.has(id)) throw new Error(`${context}: duplicate id`);
    seen.add(id);
    if (
      !["minion", "standard", "elite", "boss"].includes(enemy.role as string) &&
      !(enemy.role === "named" && NAMED_INTEGRATIONS.has(enemy.creature_id as string))
    )
      throw new Error(`${context}: unsupported role '${String(enemy.role)}'`);
    if (creatureIds && !creatureIds.has(enemy.creature_id as string))
      throw new Error(`${context}: unknown creature_id '${String(enemy.creature_id)}'`);
  }
  if (Object.hasOwn(row, "witness") || Object.hasOwn(row, "accused")) {
    const { witness, accused } = row;
    if (typeof witness !== "string" || !witness.trim())
      throw new Error(`${label}: witness must be a nonempty NPC id`);
    if (!npcIds?.has(witness)) throw new Error(`${label}: unknown witness '${witness}'`);
    if (!Array.isArray(accused) || !accused.length)
      throw new Error(`${label}: accused must be a nonempty list of enemy ids`);
    for (const id of accused) {
      if (typeof id !== "string" || !id.trim())
        throw new Error(`${label}: accused must be a nonempty list of enemy ids`);
      if (!seen.has(id)) throw new Error(`${label}: unknown accused enemy id '${id}'`);
    }
  }
  if (
    row.enemies.some((enemy: unknown) =>
      NAMED_INTEGRATIONS.has((enemy as { creature_id: string }).creature_id),
    ) &&
    row.enemies.length !== 1
  )
    throw new Error(
      `${label}: a Named integration is solitary and must have one damage/reward owner`,
    );
}
