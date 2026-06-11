// Canonical 5-tier disposition ladder — the single server-side runtime SSOT,
// ordered low->high. Imported by repair.ts (pricing) and role_archetypes.ts
// (catalog validation) so a tier change touches one place, not several.
//
// The shared package's role_archetype.ts DISPOSITION_VALUES is the cross-package
// *type* source; the shared barrel is type-only, so the runtime array is
// re-stated here rather than imported across the boundary (parity with the Python
// role_archetypes.DISPOSITIONS SSOT — same values, mirrored maintenance).
export const DISPOSITION_ORDER = ["hostile", "unfriendly", "neutral", "friendly", "trusted"];
