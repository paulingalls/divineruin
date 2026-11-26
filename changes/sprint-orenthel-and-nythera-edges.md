Bump: minor

Three patron synergies now work in combat. Sheltering Light gives a standing Orenthel guardian +1 AC against attacks while a standing ally below half HP is within 5 feet. Dawnward Strike gives an Orenthel warrior's hits 1 extra damage against Hollow and undead foes while another standing ally in the fight is below half HP. Saltwind Casting gives a Nythera mage +1 on spell attack rolls during their first stay at any Sunward Coast location. Attack receipts name each bonus when it applies.

Release steps:

- After deploy, run `SEED_PRODUCTION=1 bun run seed` from the deployed checkout with its production environment configured. This writes production content and uses no paid providers.
