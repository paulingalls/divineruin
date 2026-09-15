export interface BatchEntry {
  templateId: string;
  vars: Record<string, string>;
  label: string;
  /** When set, use this slug as the asset ID instead of computing a hash. */
  assetId?: string;
  /** When set, the generated image is also copied to the mobile assets dir with this filename. */
  locationId?: string;
  /** When set, the generated image is also copied to the mobile marketing assets dir with this filename. */
  marketingId?: string;
}

export interface CompanionArtRow {
  name: string;
  appearance: string;
  species: string;
  gender: string;
  age: string;
  portrait: {
    primary: string;
    alert: string;
  };
}

export function buildCompanionBatch(companions: CompanionArtRow[]): BatchEntry[] {
  return companions.flatMap((companion) => {
    const vars = {
      appearance: companion.appearance,
      species: companion.species,
      gender: companion.gender,
      age: companion.age,
    };
    return [
      {
        templateId: "companion_portrait_primary",
        vars,
        label: `${companion.name} primary`,
        assetId: companion.portrait.primary,
      },
      {
        templateId: "companion_portrait_alert",
        vars,
        label: `${companion.name} alert`,
        assetId: companion.portrait.alert,
      },
    ];
  });
}
