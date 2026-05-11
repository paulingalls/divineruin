# Inflation Targets & Controls — Economy Section

> **Integration note:** This section replaces the "Inflation Controls" stub in `game_mechanics_economy.md` under "Systems Not Yet Specified." Cross-references: `gold_sink_ledger.md` (sink event logging), `supply_demand_engine.md` (event lifecycle), `world_data_simulation.md` (god-agent heartbeat, simulation tick), `game_mechanics_patrons.md` (god behaviors).
>
> **Phase scope:** This section defines targets and controls for both Phase 1 (single-player) and Phase 2+ (multiplayer/MMO). Phase 1 needs only the per-character balance framework and analytics infrastructure. Phase 2+ adds global economy controls, god-agent economic intervention, and seasonal event systems. Sections marked **[Phase 2+]** are stubs until multiplayer launch.

---

## Inflation Targets & Controls

### Design Philosophy

In a single-player game, "inflation" is really just *per-character economic balance*: does the player accumulate wealth at a satisfying rate? Too slow and the economy feels punitive; too fast and gold becomes meaningless and choices stop mattering.

In a multiplayer/MMO context, inflation becomes a true macroeconomic problem. Thousands of players generate currency through quests and loot, and spend it on NPC services. If faucets (sources) exceed sinks (drains) systematically, the global gold supply grows unsustainably — a classic MMO failure mode where prices float upward, new players can't afford anything, and high-level players hoard wealth that has nothing to absorb it.

The Divine Ruin economy is designed to handle both cases:

1. **Phase 1 single-player** — the framework is *per-character* economic curves with analytics infrastructure that scales naturally to multiplayer.
2. **Phase 2+ multiplayer** — the analytics feed into intervention systems (god-agent economic actions, seasonal events, parameter tuning) that respond to drift before it becomes a problem.

The goal is not zero inflation. The goal is *controlled, deliberate* economic progression where the player feels wealth accumulation early-to-mid game, hits a stable plateau in mid-to-late game, and finds endgame sinks that absorb their wealth meaningfully.

---

### Phase 1: Per-Character Economic Curves

For single-player, the economic balance question is: at any given level, is the player's wealth approximately where it should be? Too poor = frustrating. Too rich = trivializes the system.

#### Target Wealth Curve by Level

These targets represent the player's *liquid wealth* (gold on hand, not the value of equipped gear) at the start of each level band. They assume normal play — completing main quest content, reasonable loot recovery, and typical sink engagement.

| Level Range | Expected Liquid Wealth | Major Affordability Targets |
|---|---|---|
| 1 | 10 sp (starting) | Basic supplies, common room lodging |
| 2-3 | 30-80 sp | Common armor, basic weapon upgrade |
| 4-6 | 100-300 sp | Quality armor (chain shirt, scale mail), Tier 2 commissions |
| 7-9 | 300-700 sp | First rare item purchase, mentor training fees |
| 10-12 | 700-1,500 sp | Half plate armor, Tier 2 crafted gear, Tier 3 commissions |
| 13-15 | 1,500-3,000 sp | Plate armor (100 gc), Greater Restoration available |
| 16-18 | 3,000-6,000 sp | Resurrection diamond reachable (50 gc), legendary repair affordable |
| 19-20 | 6,000-15,000 sp | Resurrection ritual (500 gc) within reach, faction investments |

**The curve has three phases:**

- **Levels 1-9 (steep growth):** Players accumulate wealth fastest here. Each level should produce ~50-100 sp of net wealth growth. The curve feels generous — players enjoy seeing their resources grow.
- **Levels 10-15 (moderate growth):** Wealth growth slows as sinks scale up (legendary repair, Tier 3 commissions, mentor fees). Net growth ~150-300 sp/level.
- **Levels 16-20 (plateau and absorption):** Endgame sinks are designed to absorb whatever the player accumulates. Wealth growth tapers as resurrection services, faction investments, and lifestyle spending consume excess capital. Players who hoard reach 15,000+ sp; players who engage with endgame content stay closer to 6,000-10,000 sp.

**Why these specific numbers:** The targets are calibrated against:
- Quest reward tiers (25-50 sp Tier 1, 100-250 Tier 2, 300-700 Tier 3) producing typical session earnings of 100-400 sp
- Gold sink ledger drains of ~50-150 sp per typical session
- Major purchases (plate armor, resurrection components) timed to specific level bands as aspirational milestones

These numbers will need playtesting validation. They're starting targets, not final values.

#### Per-Session Balance Target

Each typical play session should produce **net positive ~50-150 sp** for the player. This means:

- The player feels wealth growing
- Decisions about spending matter (you can buy *something*, not *everything*)
- Major purchases require multiple sessions of accumulation

A session that produces net negative wealth is acceptable occasionally (after a death, after major crafting investment) but shouldn't be the norm. A session producing net positive 500+ sp is also acceptable occasionally (rare loot discovery, major quest completion) but shouldn't be the norm.

#### Player-Driven Variance

The curve targets assume *typical* play. Players who deliberately optimize will deviate:

- **Hoarders** (rarely spend): May reach 2-3× target wealth at any level. The economy doesn't punish this — it just means they have nothing meaningful to do with the gold until endgame sinks open up.
- **Spenders** (engage heavily with sinks): May sit at 0.5× target. They have better gear, more relationships, more cosmetic and lifestyle expression. This is also valid.
- **Crafters** (Crafting skill investment): Lower commission/repair costs over time, higher gear quality, more workspace rental sink. Net wealth varies but gear quality consistently exceeds non-crafter peers.

The curve is a *typical experience target*, not a constraint. Player choices produce real variance, which is healthy.

---

### Analytics Infrastructure (Phase 1)

To support inflation control in Phase 2+, Phase 1 must capture the data. Per `gold_sink_ledger.md` (Decision 113), every sink event is logged. The same applies to faucets — every gold source is logged.

#### Faucet Event Logging

```python
{
  "player_id": "player_xyz",
  "faucet_category": "quest_reward",
  "faucet_type": "main_quest_completion",
  "quest_id": "the_silent_patrol",
  "amount_sp": 150,
  "context": "completed_stage_3",
  "timestamp": 1736896000
}
```

Faucet categories:
- `quest_reward` — Main and side quest completions
- `loot_sale` — Items sold to merchants (subdivided by item category for tag tracking)
- `material_sale` — Harvested materials sold
- `crafted_sale` — Player-crafted items sold
- `faction_bounty` — Standing tasks
- `service_income` — Player class abilities used economically (Cleric heals, Bard performs, Artificer repairs)
- `currency_drop` — Currency dropped by humanoid creatures (per `game_mechanics_encounter_roles.md`)
- `consignment_payout` — Deferred consignment sales

#### Aggregate Metrics

The economy simulation aggregates faucet and sink events into rolling metrics:

| Metric | Window | Use |
|---|---|---|
| Player session net (faucet - sink) | Per session | Per-session balance check |
| Player wealth by level | Snapshot | Curve adherence check |
| Faucet category distribution | 30 days | Which sources dominate? |
| Sink category distribution | 30 days | Which sinks see usage? |
| Net wealth velocity by level | 30 days | Is the curve calibrated correctly? |

These metrics feed dashboards for live balance monitoring once playtesting begins. For Phase 1, they primarily inform iterative tuning during development.

---

### Phase 2+: Global Economy Controls

> **[Phase 2+]** The systems below are required for multiplayer/MMO scale. They're stubs in Phase 1 — Phase 1 logs the data and uses simple parameter tuning, but doesn't run automated intervention systems.

#### Global Faucet/Sink Ratio Targets

For Phase 2+, the key metric is the **global faucet/sink ratio** — total gold generated across all players vs. total gold removed across all players, measured over rolling windows.

**Target: long-term ratio approaches 1.0 (faucet ≈ sink), with allowed variance:**

| Window | Acceptable Range | Action if Exceeded |
|---|---|---|
| 24-hour | 0.7 - 1.4 | Monitor only — short-term variance is normal |
| 7-day | 0.85 - 1.2 | Investigate cause; consider light intervention |
| 30-day | 0.95 - 1.1 | Active intervention required — drift is real |
| 90-day | 0.98 - 1.05 | If exceeded: balance crisis; major rebalance triggered |

**Why not exactly 1.0:** Some inflation is expected and healthy. Players accumulate wealth; the economy grows with the playerbase. Slight net-positive (faucet > sink) over the long term reflects natural progression. Slight net-negative is also acceptable if it's intentional (post-event recovery, sink-heavy seasons). The target is *deliberate, controlled* economic state, not zero growth.

#### Intervention Mechanisms

When the ratio drifts outside acceptable ranges, three intervention mechanisms can apply:

##### 1. God-Agent Economic Intervention

Per `game_mechanics_patrons.md`, the ten gods are active simulation agents with heartbeats every 15-30 minutes. Several gods have economic domains and can take economic actions when the simulation detects drift.

**Aelindra (Preservation, Memory, Value):**
- Detects: low overall wealth (sink-heavy economy, players struggling)
- Action: grants visions of forgotten ruins, lost caches, hidden treasure
- Mechanic: spawns treasure-discovery events with quest hooks pointing to high-value loot
- Net effect: increases faucet rate via authored content, narratively justified

**Mortaen (Death, Endings):**
- Detects: high death-spell spending (Revivify/Resurrection abuse) or excessive wealth in death-defying players
- Action: demands greater tribute. NPC resurrection prices rise temporarily; diamond costs spike
- Mechanic: triggers economic event affecting `divine` and `healing` tagged death-related items
- Net effect: increases sink rate, narratively justified ("death is becoming too cheap")

**Veythar (Knowledge, Magic):**
- Detects: high arcane-spending economy (lots of magic item commissions)
- Action: creates research opportunities — patron commissions paying for esoteric work
- Mechanic: spawns high-value quests for scholar patrons, balanced by high-value sinks (rare reagents, scholar fees)
- Net effect: shifts wealth between high-arcane and low-arcane players, neutral overall

**A War God (TBD):**
- Detects: low weapon/armor circulation, peace dividend hoarding
- Action: triggers faction conflict events that mobilize armies
- Mechanic: War event activates (per `supply_demand_engine.md`), creating military demand spikes
- Net effect: increases sink rate via consumable/repair demand during conflicts

The god-agent intervention system is **narratively elegant** because it disguises macroeconomic balancing as worldbuilding events. The player never sees "inflation control event"; they see "Aelindra has granted you a vision of an old Aelindran cache near the ruins" or "Mortaen demands greater tribute this season — resurrection costs have risen."

##### 2. Seasonal Economic Events

> **[Phase 2+]** Seasonal events are authored content data, not procedurally generated. The simulation rotates them through a cultural calendar.

The world has cultural seasons that produce predictable economic cycles. Each season is an authored content package with associated events.

| Season | Duration | Economic Effect |
|---|---|---|
| **Lantern Festival** (Aelindran) | 1 in-game week, annual | Luxury surplus (-15% on luxury), divine demand (+15% divine), social events trigger |
| **Forge Day** (Keldaran) | 1 in-game week, annual | Weapons/armor surplus (-15%), commission discounts (-25% Tier 1-2), faction reputation events |
| **Veil Wane** (between Hollow incursion peaks) | 2 in-game weeks, semi-annual | Anti-Hollow gear surplus, healing price normalization, recovery events |
| **Veil Wax** (peak Hollow activity) | 2 in-game weeks, semi-annual | Hollow Incursion events more likely, anti-Hollow demand spikes, military mobilization |
| **Harvest Time** (autumn) | 1 in-game month, annual | Bumper Harvest events common, food prices low |
| **The Long Dark** (winter) | 1 in-game month, annual | Travel restricted, food prices rise, lodging premium, social/indoor activity bonuses |

Seasonal events are **authored as standard economic events** (per `supply_demand_engine.md`) but with calendar-based triggers. They give the world a predictable rhythm and serve as periodic economic reset mechanisms.

**Players learn the rhythm:** "If I want a discount on weapons, I save my purchases for Forge Day." This becomes part of the strategic landscape, deepening the world's reality.

##### 3. Parameter Tuning (Manual)

When automated intervention isn't sufficient, the live operations team can adjust parameters directly:

- Quest reward tier values
- Sink magnitudes (repair costs, service prices)
- Loot drop rates
- Currency drop formulas

These adjustments are content-side, not requiring code deployment. They should be rare — the goal is for automated systems (god-agent, seasonal) to handle most drift. Parameter tuning is the lever of last resort, used quarterly at most.

---

### Phase 2+ Inflation Control Loop

The complete loop in Phase 2+:

```
Continuous data ingestion (per session, per sink, per faucet)
  ↓
Aggregate metrics computed (24h, 7d, 30d, 90d windows)
  ↓
Drift detection (ratio outside acceptable range)
  ↓
[If 24h drift] Monitor only
[If 7d drift] God-agent intervention triggers (the affected god takes domain action)
[If 30d drift] Seasonal event scheduled (next available calendar slot)
[If 90d drift] Manual parameter rebalance
  ↓
Effects propagate through simulation (events, prices, NPC behavior)
  ↓
Effects narrated to players naturally (no economic UI dashboard)
  ↓
Loop continues
```

The player never sees the inflation control system directly. They see Mortaen demanding tribute. They see Aelindra's visions. They see Forge Day approaching. They see the world responding to economic pressures through gods and seasons. This is the heart of the design — macroeconomics expressed as worldbuilding.

---

### What Phase 1 Needs

To enable Phase 2+ when the time comes, Phase 1 must implement:

1. **Per-event logging infrastructure** — Every sink and faucet event logs to a structured table. This is the foundation everything else depends on.
2. **Aggregate metrics computation** — Even if no automated intervention happens in Phase 1, the metrics should be computed for development-time tuning.
3. **God-agent economic action stubs** — The patron heartbeat system already exists. Adding "evaluate economic state" as a heartbeat consideration means the framework is ready for Phase 2+ activation.
4. **Seasonal event content data structure** — Define how seasons are authored (calendar-based event triggers). For Phase 1, populate one or two seasonal events as proof-of-concept; defer comprehensive seasonal content to Phase 2+.
5. **Parameter tuning capability** — Server-side configuration changes for quest rewards, sink magnitudes, etc. Should be content-side, not requiring code changes.

What Phase 1 explicitly does **not** need:

- Real-time inflation monitoring dashboards (build during Phase 2+ operations)
- Automated god-agent economic intervention triggering (heartbeat framework is ready, but actual triggering can be deferred)
- Comprehensive seasonal calendar content (one or two seasonal events are enough to validate the system)
- Multi-region economic modeling (single-player has one effective region — the player's local context)

The Phase 1/Phase 2+ split keeps initial development scoped while ensuring no major architectural surgery is needed for multiplayer launch.

---

### Design Decisions

> Extracted to `game_mechanics_decisions.md` for canonical reference.

**Decision 114: Inflation control is a Phase 2+ primary concern; Phase 1 implements the data infrastructure only.** Reason: in a single-player game, "inflation" is just per-character economic balance, which is handled by the wealth-by-level curves and per-session targets. Building a full automated inflation control system for single-player is over-engineering. But the *data infrastructure* (per-event logging, aggregate metrics) must exist in Phase 1 because retrofitting it into a live multiplayer service is enormously expensive. Build the foundation now, activate the controls later.

**Decision 115: The wealth-by-level curve has three phases — steep growth (1-9), moderate growth (10-15), plateau (16-20).** Reason: players need to feel wealth accumulation early to be invested in the economy. Mid-game requires harder choices as sinks scale up. Endgame requires sinks that absorb excess wealth so gold remains meaningful. The three-phase curve captures all three needs. Specific numbers will need playtesting validation, but the curve shape is the design intent.

**Decision 116: Target per-session balance is net positive 50-150 sp.** Reason: this produces a satisfying wealth growth experience without trivializing the economy. Net negative sessions feel punitive; net positive 500+ sessions feel like the system is breaking. The 50-150 sp range gives the player visible progression while preserving meaningful spending decisions. Outliers in either direction are acceptable but shouldn't be the norm.

**Decision 117: Long-term faucet/sink ratio target is 1.0 with controlled variance.** Reason: zero growth (perfect 1.0) would mean players never feel they're getting richer over time, which kills the sense of progression. Runaway growth (significantly above 1.0) creates classic MMO inflation. The target ratio of 1.0 with widening acceptable variance over shorter windows (1.4 at 24h, 1.05 at 90d) acknowledges that short-term swings are normal while long-term drift is the real problem.

**Decision 118: God-agent economic intervention is the primary Phase 2+ control mechanism.** Reason: macroeconomic adjustments expressed as authored content (god actions, seasonal events) are narratively elegant and player-visible. Players experience the world responding to their collective behavior, not "the developers nerfed quest rewards." This converts a backend balance problem into a worldbuilding feature. Manual parameter tuning remains as a fallback for cases the narrative systems can't handle, but it's the lever of last resort.

**Decision 119: Seasonal economic events are authored content with calendar triggers, not procedural.** Reason: seasonal events should feel cultural and intentional — Lantern Festival is a real festival that real NPCs celebrate, not a random discount event. Procedural generation would make seasons feel artificial. Authored content gives each season a distinct character that players can learn, anticipate, and engage with. The cost is that seasonal content must be authored and rotated, but this is a content-team responsibility, not engineering complexity.

**Decision 120: The player must never see the inflation control system directly.** Reason: economic dashboards, "inflation indicators," or any UI that exposes the macro-economic state would break the worldbuilding. The player should experience economic shifts as Mortaen's tribute demands, Aelindra's blessings, the approach of Forge Day, the deepening of the Long Dark — narrative phenomena, not statistical readouts. This is voice-first design extended to the economy: the world responds, the DM narrates, the player feels.

**Decision 121: Wealth variance from player choice is not a bug.** Reason: hoarders, spenders, and crafters will naturally land at different wealth levels. The curve targets are *typical experience targets*, not constraints. The economy should produce different experiences for different play styles — that's a feature. Inflation controls target *aggregate* drift, not individual deviation. A player choosing to hoard wealth shouldn't be penalized; they just have nothing exciting to spend it on until endgame sinks unlock.
