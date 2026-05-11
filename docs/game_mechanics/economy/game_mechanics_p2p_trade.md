# Game Mechanics — Player-to-Player Trade

> **Phase scope:** This system is **Phase 2+ deferred**. Phase 1 is single-player, so player-to-player trade does not exist yet. This document captures design intent and constraints for when multiplayer launches in Phase 2 and scales to MMO in Phase 3.
>
> **Purpose:** Stake out the design space before Phase 2 development begins. Identify constraints inherited from existing systems. Flag open questions for resolution during multiplayer planning. Avoid making Phase 2 design decisions now — capture them as questions for the right moment.
>
> **Cross-references:** `game_mechanics_economy.md` (canonical pricing), `game_mechanics_faction_pricing.md` (faction systems), `game_mechanics_merchant_inventory.md` (consignment, gold pools), `game_mechanics_supply_demand.md` (price dynamics), `game_mechanics_inflation.md` (Phase 2+ economic controls), `world_data_simulation.md` (regional economy, faction territory), `technical_architecture.md` (LiveKit transport, agent hosting).

---

## Design Intent

Player-to-player trade should feel like an extension of the world's economy, not a parallel system bolted onto it. Players trading with each other should obey the same rules as players trading with merchants — faction territory matters, regional supply and demand matters, voice-first communication matters. The world doesn't care whether the other party is a merchant or another adventurer.

The goal is not just *enabling* trade, but *making trade narratively rich*. A trade between two players in a Thornwatch outpost should feel different from a trade in a Drathian marketplace which should feel different from a back-alley exchange in the Diaspora quarter. The setting matters. The witnesses matter. The faction reputation matters.

Critically, P2P trade must not become a parallel economy that bypasses the design controls in single-player. If players can trade freely without sinks, they can circumvent the carefully balanced faucet/sink economy. The design must include trade-specific sinks (fees, taxes, transport costs) that maintain economic balance at scale.

---

## Inherited Constraints

The existing economy systems impose constraints on how P2P trade can work. These are not negotiable — they're the foundation any P2P design must respect.

### Voice-First Communication

Trade is a *conversation*, not a menu. Two players negotiating prices, terms, and items must do so through the same voice infrastructure that handles all other interactions. The DM facilitates trade as a witness/notary role: validating that both parties understand and agree, executing the mechanical transfer, narrating the outcome.

This means: no pop-up trade windows, no drag-and-drop interfaces, no menu-driven price negotiation. The character sheet shows current inventory and gold; the actual trade happens through speech.

### Faction Territory Affects All Trade

Per `game_mechanics_faction_pricing.md`, faction reputation governs merchant interactions. P2P trade in faction territory must respect faction rules:

- A trade in Thornwatch territory is *witnessed* by Thornwatch authority. Trading restricted goods (stolen Thornwatch gear, forbidden Hollow materials) in their territory carries detection risk.
- Faction-restricted items can be traded between players, but the *receiving* player inherits the reputation consequences if caught carrying them.
- Some factions may impose trade taxes in their territory (transaction fee paid to the faction treasury).

### Supply/Demand Affects Item Value

The current price of an item is regional and time-dependent (per `game_mechanics_supply_demand.md`). Two players trading should be able to *see* market context — what a merchant in this region currently pays for the item being traded. This anchors negotiation in real economic state, not arbitrary feeling.

### Gold Sinks Must Be Preserved

Every gold-equivalent transaction in the economy passes through some sink (per `game_mechanics_gold_sinks.md`). P2P trade cannot bypass this — it must include trade-specific sinks (fees, taxes, transport costs for remote trade) that absorb wealth at appropriate rates.

### Settlement Size Affects Trade Capacity

A hamlet doesn't have a marketplace. A city has multiple. P2P trade availability and richness should scale with settlement size, similar to how merchant inventory does.

---

## Direct Trade (Same Location)

The simplest P2P trade form: two players in the same physical location exchange items and/or gold directly.

### Open Design Questions

- **Witness requirement:** Should direct trade require a witness (the DM, an NPC notary, a guard captain) to validate the transaction, or can two players trade entirely between themselves with the DM only logging the result?

- **Fee structure:** Direct in-person trade is the most "frictionless" form. Should it be free (rewarding physical proximity) or carry a small base fee (preventing parallel-economy bypass)? Possible answer: free in non-faction-controlled areas, small fee in faction territory.

- **Trust mechanics:** When player A offers a sword to player B for 50 sp, what prevents A from changing their mind after receiving the gold? Possible answer: atomic exchange via DM-facilitated transaction (both parties confirm; transfer happens simultaneously).

- **Forced vs. consensual:** Can a player be coerced into trade through intimidation/threat in roleplay? Or must all trades be explicitly consensual at the mechanical level? (Lean: explicit consent always, with roleplay coercion staying narrative.)

- **Combat restrictions:** Can trade happen during combat? (Lean: no — combat phases are too constrained for trade negotiation. Outside combat only.)

### Likely Direction

Direct same-location trade is probably the **simplest, lowest-friction trade form** — the social baseline that makes parties of friends adventuring together feel cooperative. Free or near-free, voice-driven, DM-facilitated, atomic exchange. The complexity of P2P design lives in the other categories.

---

## Remote Trade

Trades between players in different locations. This is where the design gets genuinely complex.

### Open Design Questions

- **Should remote trade exist at all?** Some MMOs deliberately restrict trade to physical proximity to make geography meaningful. Divine Ruin's voice-first design might benefit from this restriction — meeting up to trade is a gameplay event, not a logistics concern. But MMO scale may require remote trade to function.

- **Transport mechanics:** If a player in Tideholm wants to send an item to a player in Stormhaven, who carries it? Possible mechanisms:
  - **Faction couriers** — pay a faction-affiliated transport service. Costs scale with distance and item value. Risk of caravan ambush (creates trade-route protection quests).
  - **NPC merchant network** — the Merchant Guild offers cross-city item delivery for a fee. Trusted+ reputation reduces fees.
  - **Player-driven transport** — a third-party player physically carries the item. Creates emergent gameplay (trade caravans, courier work as a player profession).

- **Time delay:** Remote trade should not be instant. Items in transit are real. Possible answer: 1-3 in-game days delivery time, with longer routes taking longer. Players see "in transit" status and estimated arrival.

- **Loss/theft risk:** If a courier caravan is attacked, items can be lost. This adds drama and creates economic friction but may be too punishing. Possible compromise: insurance system (pay extra to guarantee delivery; uninsured trades carry small loss probability).

- **Anti-RMT (real-money trade) protection:** Remote trade is the primary vector for real-money trading exploits. Design must include detection mechanisms (transaction value caps, velocity limits, behavioral analysis) without burdening legitimate players.

### Likely Direction

Remote trade probably exists but is **deliberately gated behind faction services** (Merchant Guild couriers, Thornwatch dispatch, etc.). This integrates with the faction reputation system, creates faction relevance for non-combat players, and provides natural anti-RMT controls (faction services are auditable; player-to-player handoffs are not).

The "player as courier" emergent gameplay is appealing but may be Phase 3 (MMO) territory.

---

## Auction House / Marketplace

A persistent listing system where players post items for sale and other players buy them without direct interaction.

### Open Design Questions

- **Should this exist?** Auction houses are a common MMO feature but they fundamentally change the economy. They reduce social interaction (no negotiation), commoditize items (every Hollow-Ward Amulet becomes interchangeable), and create market manipulation opportunities. They also enable RMT at scale.

- **Voice-first compatibility:** An auction house is fundamentally menu-driven. How does it work in a voice-first game? Possible answer: it's a faction service that can be queried by voice ("How much are healing potions going for in Tideholm?") and listings are placed verbally with a faction agent.

- **Listing fees and commissions:** If auction houses exist, they must include sinks. Posting fees + commission on successful sales feed the gold sink ledger. Possible structure: 5% listing fee + 10% commission.

- **Geographic scope:** One global auction house? Per-city auction houses? Per-faction marketplaces? Each option has different implications for regional economic identity.

- **Rare item handling:** Should unique items be auctionable? Or restricted to direct trade only? Limiting rare items to direct trade preserves their narrative weight (you have to *meet* the person who has the artifact you want).

### Likely Direction

I lean toward **deliberately constrained auction systems**, possibly as faction-specific marketplaces (the Merchant Guild auction in Tideholm, the Diaspora consignment exchange) rather than a global universal market. This preserves regional economic identity, integrates with faction reputation, and limits RMT scaling.

A global auction house would significantly simplify trade UX but at considerable cost to the world's identity. Worth genuine debate at Phase 2 design time.

---

## Trade Fees and Taxes

The sink mechanism for P2P trade. Without these, P2P becomes a parallel economy that bypasses inflation control.

### Possible Fee Structures

- **Faction transaction tax:** Trades in faction territory pay a small tax (1-5%) to the controlling faction. Higher faction reputation reduces or waives the tax. Detected evasion damages reputation.

- **Transport fees:** Remote trade pays per-distance courier fees. Scales naturally with item value and distance.

- **Auction fees:** If auction houses exist, listing fees + commission feed the sink.

- **Witness fees:** High-value direct trades may require an authorized witness (notary, faction official) for legal validity, who charges a fee. Trades without witnesses are mechanically valid but may be legally challengeable in faction courts.

### Tax Avoidance

Players can attempt to avoid trade taxes by trading in non-faction territory (wilderness, frontier, lawless areas) or by structuring transactions to disguise their nature. This creates legitimate gameplay (smuggling, frontier markets) without breaking the system — non-tax trades are riskier (no witness, no faction protection, possible bandits).

---

## Anti-Fraud and Anti-Exploit Guardrails

P2P trade is a primary attack surface for griefing, exploits, and real-money trading. Phase 2+ design must include:

### Atomic Transactions

The mechanical exchange must be atomic: either both parties get what they agreed to, or neither does. No partial transfers. No "I gave you the gold but you didn't give me the item" scenarios. The DM-facilitated trade must execute as a single transaction.

### Transaction Logs

Every P2P trade is logged with full provenance: who, what, when, where, how much. This data feeds anti-fraud detection, supports dispute resolution, and enables economic analytics.

### Velocity Limits

A player who completes 100 trades in an hour is probably a bot or RMT operator. Velocity limits flag unusual patterns. Limits should not constrain legitimate play (a guild raid distributing loot is fine; a single account moving thousands of gp/hour is not).

### Value Asymmetry Detection

A trade where player A gives player B a 5,000 sp sword in exchange for 1 cp is suspicious. Asymmetric trades aren't always RMT (gifts to friends are legitimate) but they warrant flagging for review.

### New Account Restrictions

Brand-new accounts cannot trade until they pass certain progression thresholds (level 5? completed tutorial?). This prevents single-use disposable accounts being created for RMT delivery.

### Item Provenance

Items carry a provenance trail. A weapon's history (created by player X via crafting, sold to merchant Y, looted by player Z) is queryable. This supports audit, enables narrative interactions ("That blade has a Ashmark seal — where did you get it?"), and discourages stolen-goods laundering.

---

## What Phase 1 Needs

Even though P2P trade doesn't exist in Phase 1, a few foundations should be in place to avoid Phase 2 retrofitting:

1. **Item provenance tracking infrastructure.** Every item created or transferred logs its history. This costs little in Phase 1 but is enormously expensive to retrofit later.

2. **Atomic transaction primitives.** The mechanics tools (`add_to_inventory`, `remove_from_inventory`) should be designed to support atomic multi-item, multi-currency transfers. Not used in Phase 1, but the API shape should accommodate Phase 2 trade execution.

3. **Settlement-aware inventory APIs.** When P2P trade activates, the system must know "these two players are in the same settlement" or "these players are in different settlements." Settlement membership should be queryable infrastructure.

4. **Transaction logging schema.** The faucet/sink event logging from `game_mechanics_inflation.md` should include event types for player-to-player transfers (logged as 0 sp from sink perspective in Phase 1; activated for real values in Phase 2+).

What Phase 1 explicitly does **not** need:

- Trade UI or voice flows
- Anti-fraud detection systems
- Auction house infrastructure
- Courier/transport mechanics
- Trade tax/fee execution

---

## Phase 2 Design Process

When P2P trade is designed for real (likely as part of Phase 2 multiplayer planning), the process should:

1. **Start with the constraints** in this document — they're inherited from existing systems and not up for debate.
2. **Resolve the open questions** in priority order: direct trade first (simplest), remote trade second, auction houses last (and possibly never).
3. **Stress-test the design** against RMT scenarios, griefing scenarios, and edge cases (account banning, item duplication exploits, etc.) before any implementation.
4. **Validate the voice-first interface** — every trade interaction must be expressible through voice. If a flow requires menus, redesign it.
5. **Integrate with existing systems** — faction reputation must matter, supply/demand must matter, inflation control must apply. P2P is *not* a separate economy.

---

## Design Decisions

> Extracted to `game_mechanics_decisions.md` for canonical reference.

**Decision 122: Player-to-player trade is Phase 2+ deferred; Phase 1 implements supporting infrastructure only.** Reason: Phase 1 is single-player; P2P trade is meaningless without other players. But the architectural foundations (item provenance, atomic transaction primitives, settlement-aware APIs, transaction logging) must exist in Phase 1 to avoid expensive retrofitting at Phase 2 launch. Build the bones now, the muscle later.

**Decision 123: P2P trade must obey the same world rules as merchant trade.** Reason: a parallel P2P economy that bypasses faction reputation, supply/demand, and gold sinks would undermine the entire economic design. P2P trade in Thornwatch territory is witnessed by Thornwatch authority. P2P trade of faction-restricted items carries reputation risk. P2P trade includes its own sinks (fees, taxes, transport). The world's economic rules apply uniformly regardless of who the other party is.

**Decision 124: P2P trade is voice-first; no menu-driven trade interfaces.** Reason: this is the core design pillar of the game extended consistently to trade. Players negotiate verbally, the DM facilitates, the character sheet shows current state. Auction houses (if they exist at all) are queried verbally and listings are placed verbally with a faction agent — they're not menu interfaces.

**Decision 125: Item provenance must be tracked from Phase 1.** Reason: provenance enables audit, anti-fraud, narrative ("where did you get this?"), and stolen-goods enforcement. Adding provenance retroactively to a multiplayer service requires migrating every existing item — vastly more expensive than building it in from the start. Phase 1 logs the trail; Phase 2+ uses it.

**Decision 126: Atomic transaction primitives are required infrastructure.** Reason: in Phase 1 they prevent edge cases (inventory full mid-transaction, partial loot drops). In Phase 2+ they prevent fraud and griefing. The cost is small — design the API once with atomicity in mind. The retrofit cost is enormous.

**Decision 127: Auction house design is genuinely uncertain and worth real debate at Phase 2 planning.** Reason: auction houses are a common MMO feature but they fundamentally reshape economies in ways that may conflict with our design goals (regional economic identity, voice-first interaction, narrative-rich trade). The decision shouldn't be made now. The constraints document captures the tradeoffs; the actual choice happens at Phase 2 design time with full context.

**Decision 128: Direct trade in non-faction territory carries no fee.** Reason: face-to-face trade between players adventuring together (a party splitting loot, friends gifting items) should be the most frictionless interaction. Imposing fees on every social trade would discourage the cooperative gameplay we want to enable. Faction territory adds taxes; lawless territory has none. This also creates a smuggling/frontier-market vector for legitimate gameplay.
