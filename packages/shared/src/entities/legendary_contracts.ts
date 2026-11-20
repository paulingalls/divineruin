export type Shape = Record<string, unknown>;
export const isObject = (value: unknown): value is Shape =>
  typeof value === "object" && value !== null && !Array.isArray(value);

export interface Legendary {
  points: number;
  actions: { id: string; kind: "attack" | "shift_wall" | "reshape"; cost: number }[];
}

function hasFields(value: unknown, fields: string[]): value is Shape {
  return (
    isObject(value) &&
    Object.keys(value).length === fields.length &&
    fields.every((key) => Object.hasOwn(value, key))
  );
}

function binds(creature: Shape, id: string, kind: unknown): boolean {
  if (kind === "attack") {
    return (
      Array.isArray(creature.attacks) &&
      creature.attacks.filter(
        (attack) =>
          isObject(attack) &&
          attack.name === id &&
          typeof attack.damage === "string" &&
          !["", "0", "0d0"].includes(attack.damage),
      ).length === 1
    );
  }
  return (
    ((kind === "shift_wall" && id === "Shift Wall") || (kind === "reshape" && id === "Reshape")) &&
    creature.id === "hollow_architect" &&
    Array.isArray(creature.actives) &&
    creature.actives.filter((active) => isObject(active) && active.name === id).length === 1
  );
}

export function validateLegendary(creature: Shape): string[] {
  if (!Object.hasOwn(creature, "legendary")) return [];
  const legendary = creature.legendary;
  if (!hasFields(legendary, ["points", "actions"]))
    return ["legendary: expected points and actions"];
  const { points, actions } = legendary;
  if (typeof points !== "number" || !Number.isInteger(points) || points <= 0)
    return ["legendary.points: expected positive integer"];
  if (!Array.isArray(actions) || actions.length === 0)
    return ["legendary.actions: expected nonempty array"];
  const problems: string[] = [];
  const seen = new Set<string>();
  actions.forEach((action, index) => {
    const path = `legendary.actions[${index}]`;
    if (!hasFields(action, ["id", "kind", "cost"])) {
      problems.push(`${path}: expected id, kind and cost`);
      return;
    }
    const { id, kind, cost } = action;
    if (typeof id !== "string" || !id.trim() || seen.has(id)) {
      problems.push(`${path}.id: expected unique nonempty action id`);
    } else {
      seen.add(id);
      if (!binds(creature, id, kind))
        problems.push(`${path}.id: no matching legendary action binding`);
    }
    if (typeof cost !== "number" || !Number.isInteger(cost) || cost <= 0 || cost > points)
      problems.push(`${path}.cost: expected positive integer within budget`);
  });
  return problems;
}
