# Veil Ward — Scope, Duration & Multiplayer Model

> **Status:** Decided (M24, sprint-040 story-001). This is the model that milestone
> M24's implementation stories build. Source spec: `game_mechanics_magic.md`
> §Veil Ward (L189-217). Scope decision: SMM `veil-ward-scope-decision`.

The Veil Ward locally reinforces the Veil so casters can push harder with less
danger. While a ward is active it halves Resonance generation (round down), grants
+4 to Hollow Echo rolls, and dampens spells by -1 damage die and -1 DC.

Those four effect constants are **unchanged** by this model and stay in `veil_ward.py`.
What this document settles is *who owns a ward*, *when it ends*, and *who sees it*.

---

## 1. A ward is owned by a scope, never by a caster

The shipped ward is a per-player boolean at `players.data.veil_ward`. That is wrong
in three ways: it protects only the caster who raised it, it never expires, and in a
multiplayer party it cannot express "the area is warded."

**The rule:**

> A ward belongs to a **scope**. Its effects apply to **every caster in that scope**.

Resonance and Hollow Echo remain **per-caster**. Each client in the LiveKit room is a
distinct `player_id` with its own Resonance pool, its own Overreach threshold, and its
own echo rolls. The ward is one shared object that each caster resolves *against* when
computing their own generation.

Put plainly: the ward is a property of the *place or fight*, not of the *person*.
Two casters under one ward each halve their own generation, independently.

---

## 2. Two scope kinds, two homes

Each ward lives in exactly **one** home. This is a scope split, not dual state.

| Scope kind | Key | Home | Expiry mechanism |
|---|---|---|---|
| `encounter` | `combat_id` | `CombatState.veil_ward` → `combat_instances.data` JSONB | `rounds_remaining: int \| None`, ticked at the WRAP beat; dies with the combat row |
| `location` | `location_id` | `veil_wards` table | `expires_at TIMESTAMPTZ`, `NULL` = permanent; compared to `NOW()` at read |

### Why two homes and not one table

`combat_phase.py` is a **pure engine over `CombatState`**. A round-based duration can
only tick purely if the thing being ticked lives on that state — which is exactly how
`conditions` (an integer phase-count with `None` meaning permanent) and `ac_modifiers`
already work. Holding encounter wards in a side table would force one of two bad
options: a `CombatState` projection of the ward (reintroducing the dual state this
milestone eliminates), or a signal-and-apply dance through `WrapOutcome`.

On `CombatState`, the ward also dies for free: `_end_combat_db` deletes the combat row,
and that deletion **is** the "encounter" duration. No teardown code to forget.
This honors the settled constraint `combat-persistence-jsonb-ssot`.

Location wards outlive and precede combat, so `combat_instances` cannot hold them.
An absolute `expires_at` compared to `NOW()` at read time is the established house
pattern (`workspace_rentals`, `training_activities`), with `NULL` meaning permanent.

### Durations need no world clock

Location-ward expiry is **lazy**: nothing sweeps expired wards; a read compares
`expires_at` to `NOW()`. That is real-elapsed time, consistent with the settled 1:1
world-clock model (1 game-minute = 1 real-minute).

What does *not* exist yet is a **tick loop**. `compute_node_respawn` is a pure resolver
with an injected elapsed value and no live caller; the simulation tick that would call
it belongs to Phase 11. A tick loop is only needed to fire *proactive* events ("the
ward drops, narrate it"). M24 needs no such loop, because a ward that has expired is
simply not returned by the next read.

---

## 3. Ward resolution: any covering scope

```
is_warded(caster) := encounter_ward_active(session.combat_state)
                     or location_ward_active(session.location_id)
```

Ward effects are uniform across sources and **do not stack**, so resolution is a
boolean OR. There is no stacking math and no "strongest ward wins" rule.

### Coexistence and single-scope expiry

Scopes overlap. A party fighting at a Sacred site has a permanent `location` ward;
if their Cleric also raises one mid-fight, an `encounter` ward covers them too.

When **one** covering scope's ward ends, the party may still be warded by another.
Therefore:

> The wire signal and the HUD reflect the **resolved** warded state across all covering
> scopes — never a single scope's own toggle.

Concretely: on combat end the encounter ward dies, but if a location ward still covers
the party, `VEIL_WARD_CHANGED` carries `active: true`. A consumer that keyed its
indicator to the expiring scope would turn the ward light **off while the party's casts
are still being halved** — the same class of silent lie this milestone exists to remove,
rebuilt one layer up. Producers must compute `active` from `is_warded`, not from the
scope they just mutated.

---

## 4. Sources and durations

`WARD_SOURCES` gains a duration per source. The three shipped sources keep their
level and cost fields exactly as they are.

| Source | Level | Cost | Scope raised | Duration |
|---|---|---|---|---|
| `cleric` | 7 | 4 Focus | `encounter` in combat, else `location` | encounter, or until dismissed |
| `druid` | 9 | 5 Focus | `encounter` in combat, else `location` | encounter, or until dismissed |
| `paladin` | 10 | 3 Focus + 3 Stamina | `encounter` **only** | 3 rounds |
| `artificer` | — | crafted item | `location` | small anchor 1 hour; large anchor permanent |
| `sacred_site` | — | passive | `location` | permanent |

**Paladin out of combat is refused** with a `ToolError`. "3 rounds" has no meaning
where no rounds elapse, and the spec frames Sanctified Ground as the expensive, short
emergency option. Refusing keeps the round clock honest: a round counter never exists
outside combat, so it can never silently fail to tick.

**Cleric and Druid out of combat** raise a `location` ward with `expires_at = NULL` —
the spec's "Encounter *or dismissed*", where no encounter exists to bound it.

**The Druid source is not terrain-gated here.** The spec's "natural terrain only"
restriction is Phase 10 (see §7).

### The Artificer's two anchors

`content/items.json` authors two anchors, and they are deliberately different:

- `veil_ward_anchor_small` — tier 3, "Creates a 15 ft Veil Ward for 1 hour; consumed on
  use." Deploys a `location` ward with `expires_at = NOW() + 1 hour`, consuming the item.
  This is the spec's Artificer row: the tactical, plannable option.
- `veil_ward_anchor_large` — tier 4 legendary, "Permanent 30 ft Veil Ward at a location;
  not consumed." Deploys a `location` ward with `expires_at = NULL`. It is, in effect, a
  **player-craftable Sacred site**, and it shares the permanent representation.

Both are raised without Focus or Stamina cost — the crafting *is* the cost.
Permanent wards (large anchor, `sacred_site`) are **not** dismissible via
`activate_veil_ward`; their lifecycle belongs to crafting and to Phase 11.

---

## 5. Dismissal

Any in-scope member may dismiss a dismissible ward, for free. The ward is scope-owned,
so it is not the raiser's to hold exclusively. A `ToolError` is raised when no
dismissible ward covers the caster.

---

## 6. Wire contract

`VEIL_WARD_CHANGED` carries:

```
{active, scope_kind, scope_id, source}
```

`active` is the party's **resolved** warded state (§3), not the mutated scope's flag.
There is **no raiser id**, and no `caster_id` filter. Every client whose party is in
scope lights its indicator.

> **Asymmetry, on purpose.** `RESONANCE_CHANGED` keeps its `isEventForLocalPlayer(caster_id)`
> filter, because Resonance is per-caster. `VEIL_WARD_CHANGED` must not copy that pattern.
> Filtering the ward to its raiser lights only the raiser's HUD while every other in-scope
> caster is silently halved. State this in the code, or a later reader will "restore
> consistency" and reintroduce the bug.

---

## 7. Phase boundaries

M24 owns the scope model and the pieces orphaned by Delivered phases 3 and 5. Two
ward-touching bodies of work stay in their own not-yet-started phases and build on
this model.

**Phase 10 — Druid terrain gate** (`10_terrain.md` §M10.2). Gates the `druid` source on
`is_natural(terrain)` and grants an `ancient_forest` bonus, against *this* reworked
activation path. `content/locations.json` carries `terrain` and `region_type` but no
`is_natural`; Phase 10 adds it. M24 leaves the `druid` source ungated.

**Phase 11 — world-sim wards** (`11_world_loop.md` §Layer 3). Ambient territory
Resonance, corruption-driven ward strength, seasonal escalation, and Sacred-site
permanent world wards. These populate the `sacred_site` source defined here.

### The Sacred-site hook

`sacred_site` exists as a `WARD_SOURCES` entry and as a permitted `source` value on a
permanent `location` ward. **M24 constructs none.** The hook is the source entry plus
the table's willingness to hold a permanent row — Phase 11 supplies the world entities.
The large Veil Anchor exercises the same representation from the crafting side, which
means the permanent-ward path is live and tested before Phase 11 depends on it.

---

## 8. Migration off the per-player boolean

Migration `057_veil_ward_scope.sql` creates `veil_wards` and removes the legacy key:

```sql
UPDATE players SET data = data - 'veil_ward' WHERE data ? 'veil_ward';
```

Idempotent via the `WHERE data ? 'key'` guard — the house backfill idiom, inverted.

This is the **first migration in this codebase to remove a key from `players.data`**;
every prior migration only added them. Say so in the migration comment.

**No ward state is carried forward.** A boolean with no scope and no duration cannot be
mapped onto a scoped, duration-bound ward, and wards are ephemeral by design. There is
no dual-state window: after `057`, `players.data.veil_ward` does not exist and nothing
reads it.
