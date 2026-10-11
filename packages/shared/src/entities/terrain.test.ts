import { test, expect } from "bun:test";
import {
  TERRAIN_PROPERTIES,
  terrainProperties,
  resonanceBase,
  isNatural,
  isEarthOrStone,
  regionType,
} from "./terrain";

test("actual Python and TypeScript terrain exports agree", () => {
  const root = decodeURIComponent(new URL("../../../../", import.meta.url).pathname);
  const result = Bun.spawnSync([
    "uv",
    "run",
    "--project",
    `${root}scripts`,
    "--frozen",
    "python",
    "-c",
    `
import sys, json
sys.path.insert(0, ${JSON.stringify(root + "apps/agent")})
from terrain import TerrainType, properties, resonance_base, is_natural, is_earth_or_stone, region_type
from dataclasses import asdict
print(json.dumps({v.value: {"properties": asdict(properties(v)), "accessors": [f(v) for f in (resonance_base, is_natural, is_earth_or_stone, region_type)]} for v in TerrainType}))
`,
  ]);
  expect(result.exitCode).toBe(0);
  const python = JSON.parse(result.stdout.toString()) as Record<
    string,
    {
      properties: ReturnType<typeof terrainProperties>;
      accessors: ReturnType<
        typeof resonanceBase | typeof isNatural | typeof isEarthOrStone | typeof regionType
      >[];
    }
  >;
  expect(Object.keys(TERRAIN_PROPERTIES).sort()).toEqual(Object.keys(python).sort());
  for (const [value, row] of Object.entries(python)) {
    expect(terrainProperties(value)).toEqual(row.properties);
    expect([
      resonanceBase(value),
      isNatural(value),
      isEarthOrStone(value),
      regionType(value),
    ]).toEqual(row.accessors);
  }
});

for (const accessor of [resonanceBase, isNatural, isEarthOrStone]) {
  test(`${accessor.name} rejects unknown terrain`, () => {
    expect(() => accessor("normal")).toThrow("normal");
  });
}
