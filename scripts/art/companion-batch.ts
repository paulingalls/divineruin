export interface BatchEntry {
  templateId: string;
  vars: Record<string, string>;
  label: string;
  assetId?: string;
  locationId?: string;
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
