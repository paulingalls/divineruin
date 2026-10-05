"""Guard for the companion-relationship stub scope (story-007 / concern 11908b7f8b29).

Adopted decision 5a29b2786537: the rank/affinity DB stubs must NOT be globally autouse.
A test module that does not opt into `stub_companion_errand_affinity_io` must see the REAL
`cached_effective_rank` / `apply_errand_affinity` — otherwise every errand/worker integration
test silently runs against a forced rank of 1, masking tier>1 behavior. The harmless
session-hydrate stub (`hydrate_companion_state`) stays global autouse so DB-free startup tests
keep passing.

This module intentionally requests NEITHER stub, so it observes the default global scope.
"""

from unittest.mock import Mock

import companion_relationship_queries as crq


def test_rank_and_affinity_are_not_globally_stubbed():
    """Use AsyncMock only for the asynchronous seam."""
    assert not isinstance(crq.cached_effective_rank, Mock)
    assert not isinstance(crq.apply_errand_affinity, Mock)


def test_session_hydrate_stays_globally_stubbed():
    """Hydration must replace global companion defaults with the assigned companion."""
    assert isinstance(crq.hydrate_companion_state, Mock)
