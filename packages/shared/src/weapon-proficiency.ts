const CATEGORIES = ["simple", "martial"] as const;
const RANGES = ["melee", "ranged"] as const;
const KINDS = [
  "battleaxe",
  "club",
  "dagger",
  "garrote",
  "greataxe",
  "greatsword",
  "halberd",
  "handaxe",
  "hand_crossbow",
  "heavy_crossbow",
  "light_crossbow",
  "longbow",
  "longsword",
  "lute",
  "mace",
  "quarterstaff",
  "rapier",
  "scimitar",
  "shortbow",
  "shortsword",
  "sling",
  "spear",
  "tools",
  "warhammer",
] as const;

type WeaponCategory = (typeof CATEGORIES)[number];
type WeaponRange = (typeof RANGES)[number];
type WeaponKind = (typeof KINDS)[number];

const CATEGORY_RANGES = {
  simple_melee: ["simple", "melee"],
  simple_ranged: ["simple", "ranged"],
  martial_melee: ["martial", "melee"],
  martial_ranged: ["martial", "ranged"],
} as const satisfies Record<
  `${WeaponCategory}_${WeaponRange}`,
  readonly [WeaponCategory, WeaponRange]
>;
type CategoryRangeToken = keyof typeof CATEGORY_RANGES;

const GROUP_KINDS = { martial_polearms: "halberd", martial_hammers: "warhammer" } as const;
type GroupToken = keyof typeof GROUP_KINDS;

export type WeaponProficiency =
  WeaponCategory | WeaponKind | CategoryRangeToken | GroupToken | "light_weapons" | "staff";

const PROFICIENCIES: ReadonlySet<unknown> = new Set([
  ...CATEGORIES,
  ...KINDS,
  ...Object.keys(CATEGORY_RANGES),
  ...Object.keys(GROUP_KINDS),
  "light_weapons",
  "staff",
]);

export interface WeaponProfile {
  weapon_category: WeaponCategory;
  weapon_range: WeaponRange;
  weapon_kind: WeaponKind;
}

function readEnum<T extends string>(value: unknown, allowed: readonly T[], ctx: string): T {
  if (!(allowed as readonly unknown[]).includes(value)) {
    throw new Error(`${ctx} ${JSON.stringify(value)} is invalid`);
  }
  return value as T;
}

export function parseWeaponProfile(data: Record<string, unknown>, ctx: string): WeaponProfile {
  return {
    weapon_category: readEnum(data.weapon_category, CATEGORIES, `${ctx}.weapon_category`),
    weapon_range: readEnum(data.weapon_range, RANGES, `${ctx}.weapon_range`),
    weapon_kind: readEnum(data.weapon_kind, KINDS, `${ctx}.weapon_kind`),
  };
}

export function parseWeaponProficiencies(raw: unknown, ctx: string): WeaponProficiency[] {
  if (!Array.isArray(raw) || raw.length === 0) throw new Error(`${ctx} must be a nonempty array`);
  return raw.map((token: unknown) => {
    if (!PROFICIENCIES.has(token))
      throw new Error(`${ctx} contains invalid token ${JSON.stringify(token)}`);
    return token as WeaponProficiency;
  });
}

export function hasWeaponProficiency(
  proficiencies: readonly WeaponProficiency[],
  weapon: WeaponProfile & { properties?: readonly string[] },
): boolean {
  return proficiencies.some((token) => {
    if (token === "simple" || token === "martial") return weapon.weapon_category === token;
    if (token in CATEGORY_RANGES) {
      const [category, range] = CATEGORY_RANGES[token as CategoryRangeToken];
      return weapon.weapon_category === category && weapon.weapon_range === range;
    }
    if (token in GROUP_KINDS) {
      return (
        weapon.weapon_category === "martial" &&
        weapon.weapon_kind === GROUP_KINDS[token as GroupToken]
      );
    }
    if (token === "light_weapons") return weapon.properties?.includes("light") ?? false;
    return weapon.weapon_kind === (token === "staff" ? "quarterstaff" : token);
  });
}
