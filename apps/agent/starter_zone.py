"""Starter-zone SSOT (story-006). Pure — no IO, no async.

The starter zone is whichever location carries the ``"starting_area"`` tag. That tag is the single
source of truth; ``STARTER_ZONE_ID`` is the offline fallback used ONLY when no location is tagged
(e.g. a content catalog that predates the tag). Both resurrection.py's tier-4 anchor and
``creation_rules.DEFAULT_START_LOCATION`` derive from here, so a retag can never silently diverge
from a hardcoded literal copied into two modules.
"""

STARTER_ZONE_TAG = "starting_area"

# Offline fallback when no location carries STARTER_ZONE_TAG. The tag is the SSOT; this literal only
# protects resolution against an untagged location catalog — it is NOT a second source of truth.
STARTER_ZONE_ID = "accord_market_square"


def get_starter_zone_id(locations: dict[str, dict]) -> str:
    """Return the id of the location tagged STARTER_ZONE_TAG, or STARTER_ZONE_ID if none is tagged.

    Searches the supplied ``{id: data}`` location map. The tag — not the literal — is the source of
    truth: retagging a different location moves the starter zone everywhere this helper is called.
    """
    return (
        next((loc_id for loc_id, loc in locations.items() if STARTER_ZONE_TAG in loc.get("tags", [])), None)
        or STARTER_ZONE_ID
    )
