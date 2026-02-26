# Divine Ruin — Cost Model

## Purpose

Can the unit economics of a voice-first AI RPG support a $15–20/month subscription? This document models the per-session and per-subscriber costs using current (February 2026) pricing for each component of the voice pipeline.

**Bottom line: Yes, with healthy margin. Switching from Cartesia to Inworld TTS-1.5 cuts TTS cost by 67%, making the economics comfortable for all player profiles including solo heavy users.**

---

## Pricing Inputs (February 2026)

| Component | Provider | Price | Unit | Source |
|---|---|---|---|---|
| **STT** | Deepgram Nova-3 | $0.0065 | per minute (streaming, Growth plan) | deepgram.com/pricing |
| **TTS (primary)** | Inworld TTS-1.5 Max | $0.000010 | per character ($10/1M chars) | inworld.ai/tts |
| **TTS (alternative)** | Inworld TTS-1.5 Mini | $0.000005 | per character ($5/1M chars) | inworld.ai/tts |
| **TTS (evaluated)** | Cartesia Sonic-3 | $0.0000299 | per character (Scale plan) | cartesia.ai/pricing |
| **LLM** | Claude Haiku 4.5 | $1 / $5 | per MTok input / output | anthropic.com |
| **LLM** | Claude Sonnet 4.5 | $3 / $15 | per MTok input / output | anthropic.com |
| **LLM cache** | Claude (all models) | 0.1× input price | per MTok cache read | anthropic.com |
| **Transport** | LiveKit Cloud | $0.0005 | per participant-minute (connection) | livekit.io/pricing |
| **Transport** | LiveKit Cloud | $0.01 | per agent-session-minute | livekit.io/pricing |
| **Transport** | LiveKit Cloud | $0.004 | per minute (audio bandwidth) | livekit.io/pricing |
| **Transport** | LiveKit self-hosted | ~$0.002 | per participant-minute (estimated server cost) | estimated |

### Notes on Pricing

- **Inworld TTS-1.5** is ranked #1 on Artificial Analysis blind tests (ELO 1,160). Max model at $10/1M characters is 3× cheaper than Cartesia and higher quality. Mini at $5/1M chars is 6× cheaper. Both support WebSocket streaming, instant voice cloning from 5-15s audio, temperature-based expressiveness control, and 15 languages. Originally built for game NPCs — strong fit for our use case.
- **Cartesia Sonic-3** remains evaluated as an alternative. It has the lowest latency in the market (40-90ms TTFA) and more granular emotion controls (specific emotion tags vs. Inworld's temperature dial). Scale plan = $239/mo (annual) for 8M credits, effective rate ~$30/1M characters.
- **Deepgram** PAYG is $0.0077/min; Growth plan is $0.0065/min. We use Growth.
- **Claude** prompt caching: system prompt cached at 0.1× input price after first call. Cache write = 1.25× input price (one-time). This is a massive cost lever — the DM's system prompt (world state, character sheets, rules) stays cached across an entire session.
- **LiveKit** is open source. Cloud pricing shown; self-hosting eliminates connection fees and agent-session charges, leaving only server compute. At scale, self-hosting is substantially cheaper.
- **Self-hosted TTS option:** Chatterbox-Turbo (MIT, 350M params, emotion exaggeration control, paralinguistic tags) eliminates per-character costs entirely. GPU cost only (~$0.75/hr per A10G). Viable at scale as a cost-elimination path.

---

## Session Model Assumptions

### What Happens in a 30-Minute Session

A typical session includes narration, player interaction, NPC dialogue, combat, and exploration. We model the time split and interaction count.

| Metric | Solo Session | Party Session (4 players) |
|---|---|---|
| Session duration | 30 min | 30 min |
| Player speaking time (total) | 10 min | 15 min |
| DM audio output time | 15 min | 18 min |
| Silence / ambient / processing | 5 min | ~2 min (less idle in groups) |
| Player–DM exchanges | 35 | 50 |
| Average DM response length | ~120 words (~600 chars) | ~100 words (~500 chars) |
| Total DM output characters | ~21,000 | ~25,000 |

### LLM Token Estimates Per Session

The DM's system prompt (world state, scene, character sheets, rules, voice tags) is assembled once and cached for the session.

| Token Category | Solo Session | Party Session |
|---|---|---|
| System prompt (cached after call 1) | 4,000 tokens | 6,000 tokens |
| Average conversation context per call | ~500 tokens | ~700 tokens |
| Average new player input per call | ~40 tokens | ~60 tokens |
| Average DM output per call | ~150 tokens | ~130 tokens |
| Total cache reads | 140K tokens | 300K tokens |
| Total fresh input | 19K tokens | 38K tokens |
| Total output | 5.3K tokens | 6.5K tokens |
| Cache write (one-time) | 4K tokens | 6K tokens |

---

## Per-Session Cost Breakdown

### Solo Session (1 player + DM agent, 30 minutes)

| Component | Haiku 4.5 | Sonnet 4.5 | Calculation |
|---|---|---|---|
| **STT** (Deepgram) | $0.065 | $0.065 | 10 min × $0.0065 |
| **TTS** (Inworld Max) | $0.21 | $0.21 | 21,000 chars × $0.00001 |
| **LLM** — cache write | $0.005 | $0.015 | 4K tokens × 1.25× input |
| **LLM** — cache reads | $0.014 | $0.042 | 140K tokens × 0.1× input |
| **LLM** — fresh input | $0.019 | $0.057 | 19K tokens × input rate |
| **LLM** — output | $0.027 | $0.079 | 5.3K tokens × output rate |
| **LLM subtotal** | **$0.065** | **$0.193** | |
| **LiveKit Cloud** | $0.44 | $0.44 | connection + agent + bandwidth |
| **LiveKit self-hosted** | $0.06 | $0.06 | estimated server cost |
| | | | |
| **Total (LK Cloud)** | **$0.78** | **$0.91** | |
| **Total (LK self-host)** | **$0.40** | **$0.53** | |

*For comparison, using Cartesia instead of Inworld adds ~$0.42 to TTS per session.*

### Party Session (4 players + DM agent, 30 minutes)

| Component | Haiku 4.5 | Sonnet 4.5 | Calculation |
|---|---|---|---|
| **STT** (Deepgram) | $0.098 | $0.098 | 15 min × $0.0065 |
| **TTS** (Inworld Max) | $0.25 | $0.25 | 25,000 chars × $0.00001 |
| **LLM subtotal** | $0.10 | $0.29 | (see token estimates above) |
| **LiveKit Cloud** | $0.60 | $0.60 | 5 participants × 30 min |
| **LiveKit self-hosted** | $0.10 | $0.10 | estimated |
| | | | |
| **Total session (LK Cloud)** | **$1.05** | **$1.24** | |
| **Total session (LK self-host)** | **$0.55** | **$0.74** | |
| **Per player (LK Cloud)** | **$0.26** | **$0.31** | ÷ 4 players |
| **Per player (LK self-host)** | **$0.14** | **$0.19** | ÷ 4 players |

---

## Monthly Subscriber Economics

### Usage Assumptions

| Player Profile | Sessions/month | Avg. duration | Async check-ins/month |
|---|---|---|---|
| **Heavy** | 12 (3/week) | 45 min | 30 |
| **Moderate** | 6 (1.5/week) | 40 min | 15 |
| **Light** | 3 (0.75/week) | 35 min | 8 |

Async check-in cost: ~$0.04 each. Breakdown: world news narration is pre-rendered during simulation ticks (amortized, ~$0.005/player/tick). Resolved activity narrations are batch-generated when activities complete (one LLM call for outcome text + one TTS synthesis per activity, ~$0.002 each). God whispers are pre-rendered (~$0.003 each). Decision inputs are REST calls (negligible). Total per check-in with 2-3 resolved activities + world news: ~$0.01-0.02 in pre-rendered content + ~$0.02 in serving/infrastructure = ~$0.04. Mini-quests (optional, 5-10 min live voice) cost ~$0.10-0.15 each — these are rare and optional, excluded from base async costing.

### Monthly Cost Per Subscriber

Using **Haiku 4.5 + self-hosted LiveKit + Inworld TTS-1.5 Max** (the likely production configuration):

| Profile | Play Style | Session Cost | Async Cost | Total/month | At $17.50 sub | Gross Margin |
|---|---|---|---|---|---|---|
| Heavy | Solo | $7.20 | $1.20 | **$8.40** | $17.50 | **52%** |
| Heavy | Party | $2.52 | $1.20 | **$3.72** | $17.50 | **79%** |
| Moderate | Solo | $3.20 | $0.60 | **$3.80** | $17.50 | **78%** |
| Moderate | Party | $1.12 | $0.60 | **$1.72** | $17.50 | **90%** |
| Light | Solo | $1.40 | $0.32 | **$1.72** | $17.50 | **90%** |
| Light | Party | $0.49 | $0.32 | **$0.81** | $17.50 | **95%** |

### Key Insight: Even Solo Heavy Players Have Comfortable Margin

With Inworld TTS, the solo heavy player (12 sessions/month at 45 min each, all solo) runs at 52% gross margin — a dramatic improvement over the ~9% margin with Cartesia. This eliminates the previous concern about solo play being marginally profitable. Party play remains dramatically cheaper per player, but solo is no longer a risk case.

Using **Sonnet 4.5** instead of Haiku adds ~$1.50/month for a heavy player. The LLM is still not the cost problem — and with Inworld's pricing, no single component dominates enough to be an existential concern.

---

## Cost Distribution

For a solo 30-minute session (Haiku + self-hosted + Inworld Max):

| Component | Cost | % of Total |
|---|---|---|
| TTS (Inworld Max) | $0.21 | **53%** |
| STT (Deepgram) | $0.065 | 16% |
| LLM (Haiku 4.5) | $0.065 | 16% |
| Transport (self-hosted) | $0.06 | 15% |
| **Total** | **$0.40** | 100% |

**TTS is still the largest component at 53%, but no longer an overwhelming 77%.** Costs are more evenly distributed. This means no single vendor has existential pricing power over the business.

*With Inworld Mini ($5/1M chars), TTS drops to $0.105 (36% of session cost), making transport the second-largest component.*

*With Cartesia ($30/1M chars), TTS would be $0.63 (77% of session cost) — the previous model.*

---

## Optimization Paths

### TTS — Still the Biggest Lever, Now Well-Managed

1. **Inworld TTS-1.5 as primary.** At $10/1M characters (Max) or $5/1M (Mini), Inworld is already 3-6× cheaper than Cartesia while ranking #1 on quality. Built for game NPCs, supports voice cloning and expressiveness controls. WebSocket streaming at <250ms latency. This single switch cut TTS cost by 67% from our initial Cartesia model.

2. **Inworld Mini for routine interactions.** Use Max ($10/1M) for high-impact moments (boss fights, god whispers, dramatic reveals) and Mini ($5/1M) for routine narration (navigation confirmations, merchant interactions, ambient NPC chatter). The orchestrator already classifies intent — it can route to different quality tiers.

3. **Self-hosted TTS at scale (Chatterbox-Turbo).** MIT licensed, 350M parameters, emotion exaggeration control, paralinguistic tags ([laugh], [cough], [chuckle]), zero-shot voice cloning. Self-hosting eliminates per-character costs entirely — you pay GPU compute only. A single A10G (~$0.75/hr on AWS) can serve multiple concurrent sessions. At 100K+ subscribers, self-hosting TTS could cut the TTS line item by another 50-80%.

4. **Dia2 as long-term multi-speaker option.** Nari Labs' Dia2 is architecturally ideal for our ventriloquism pattern — it generates multi-speaker dialogue natively with [S1]/[S2] tags. Currently English-only and research-stage, but worth tracking. If it matures, it could handle the DM-speaking-as-multiple-characters use case more naturally than switching between single-speaker voice IDs.

5. **Response compression.** Still valuable regardless of TTS provider. Shorter DM output = fewer TTS characters = lower cost. This is a prompt engineering problem with direct financial impact.

6. **Pre-generated audio.** Common NPC greetings, merchant interactions, ambient narration snippets can be pre-generated and cached. The DM selects from pre-generated audio for routine exchanges and only generates fresh TTS for novel content.

### LLM — Already Cheap, Can Be Cheaper

1. **Prompt caching is critical.** The system prompt (world state, rules, character sheets) should be stable within a session. With 1-hour caching, reads cost 10% of input price. This already saves ~80% on input costs.

2. **Model tiering.** Use Haiku for routine interactions (navigation, simple NPC exchanges) and Sonnet for complex scenes (combat narration, mystery reveals, multi-character dialogue). The orchestrator can route based on complexity. 80% of interactions can use Haiku.

3. **Fine-tuned small models.** For high-volume, predictable interactions (merchant transactions, skill checks), a fine-tuned small model could replace API calls entirely.

### Transport — Self-Host at Scale

LiveKit is open source. At any meaningful scale, self-hosting on dedicated servers with LiveKit's SFU eliminates per-minute cloud charges. The infrastructure cost is a flat rate based on server count, not per-session.

### STT — Already Efficient

Deepgram at $0.0065/min is already the cheapest high-quality streaming STT. VAD ensures we only transcribe actual speech, not silence. Little optimization needed here.

---

## Projections at Scale

### 10,000 Subscribers (Early Scale)

Assuming a mix of 20% heavy, 50% moderate, 30% light, and 60% party play:

| | Monthly |
|---|---|
| Subscribers | 10,000 |
| Weighted avg cost/subscriber | ~$2.80 |
| Total AI/infra cost | ~$28,000 |
| Subscription revenue ($17.50) | $175,000 |
| **Gross margin on AI costs** | **84%** |

Remaining margin covers: servers (PostgreSQL, Redis, app tier), CDN, payment processing (~3%), customer support, content creation, team salaries.

### 100,000 Subscribers (Scale)

At this scale, enterprise pricing kicks in, self-hosted TTS becomes viable, and per-unit costs drop significantly.

| | Monthly |
|---|---|
| Subscribers | 100,000 |
| Weighted avg cost/subscriber | ~$2.00 (with optimizations) |
| Total AI/infra cost | ~$200,000 |
| Subscription revenue ($17.50) | $1,750,000 |
| **Gross margin on AI costs** | **89%** |

---

## Comparison: What Traditional MMOs Spend

For context, a traditional MMO's server infrastructure costs roughly $1–3 per subscriber per month at scale. Our AI costs are higher ($3–5 range), but our content creation costs are radically lower — the AI generates every interaction instead of requiring hand-authored quest scripts, voice actor recordings, and 3D assets.

The fundamental trade-off: **higher per-session compute cost, dramatically lower content production cost.** At scale, this trade-off strongly favors the AI approach because content scales with compute (which gets cheaper every year) rather than with headcount. The Inworld pricing shift demonstrates this trend — TTS cost dropped 67% in a single competitive move.

---

## Risks and Uncertainties

1. **TTS vendor concentration.** Inworld's pricing is exceptional but they're a startup. If they raise prices, pivot, or shut down, we need alternatives ready. Mitigation: maintain Cartesia as a tested fallback, invest in Chatterbox-Turbo evaluation for self-hosting.

2. **Session length creep.** Players who love the experience may push toward 60-90 minute sessions. The cost model now works comfortably at 30-45 min and remains healthy even at 60 min. At 90 min solo sessions (heavy user), costs approach ~$1.20/session — still profitable but worth monitoring. Mitigation: natural session pacing by the DM, session types with suggested durations.

3. **LLM pricing trends favor us.** Token costs have dropped ~50% year-over-year. Haiku 4.5 at $1/$5 would have been frontier pricing two years ago. This trend makes the LLM component cheaper over time.

4. **TTS pricing trends also favor us.** The Inworld launch at $5-10/1M chars (25× cheaper than ElevenLabs) signals a race to the bottom in TTS pricing. Cartesia, ElevenLabs, and open-source options will likely respond with price cuts, further improving our economics.

5. **God-agent background costs.** The heartbeat loops for 10 god-agents add a constant baseline cost even when no players are online. This is small (a few LLM calls per hour per god) but should be modeled once the god-agent architecture is specified.

6. **Async costs are modest.** Each check-in is a short interaction (~$0.04). Even heavy async users add <$1.50/month. This is not a concern.

7. **Inworld latency vs. Cartesia.** Inworld Max is ~200ms TTFA vs. Cartesia's 40-90ms. For our pipeline (where LLM generation is the bottleneck at 500-800ms to first token), this ~150ms difference is unlikely to be perceptible. But it should be validated in the prototype.

---

## Verdict

**The unit economics are strong.** A $17.50/month subscription supports the voice pipeline with healthy margins across all player profiles. Even the worst case — a solo-only heavy player doing 12 sessions/month at 45 minutes each — runs at 52% gross margin. The median player is closer to 80-90%.

The switch from Cartesia to Inworld TTS-1.5 was the single most impactful finding: **67% cost reduction on the dominant cost component, with higher quality.** This moved TTS from an existential concern (77% of session cost) to a manageable component (53%).

The path to even better economics is clear: self-host LiveKit, tier TTS between Inworld Max and Mini by interaction importance, evaluate self-hosted Chatterbox-Turbo at scale, and use prompt caching aggressively. Each optimization compounds.

**The LLM is not the expensive part** — and with Inworld's pricing, nothing is. The cost difference between Haiku and Sonnet is ~$1.50/month per heavy user. If Sonnet produces materially better DM narration, use it without hesitation.

### TTS Provider Evaluation Summary

| Provider | Price/1M chars | Quality | Latency | Multi-voice | Emotion | Self-host | Status |
|---|---|---|---|---|---|---|---|
| **Inworld 1.5 Max** | $10 | #1 (ELO 1,160) | <250ms | Yes (cloning) | Temperature | On-prem available | **Primary** |
| **Inworld 1.5 Mini** | $5 | High | <130ms | Yes (cloning) | Temperature | On-prem available | **Routine interactions** |
| Cartesia Sonic-3 | ~$30 | #20 (ELO 1,053) | 40-90ms | Yes (cloning) | Emotion tags | Enterprise only | Evaluated alternative |
| Chatterbox-Turbo | GPU only | Beats ElevenLabs | Sub-200ms | Voice cloning | Exaggeration param | MIT license | Scale path |
| Dia2 | GPU only | Research-stage | Real-time | Native [S1]/[S2] | Audio conditioning | Apache 2.0 | Watching |

---

*Pricing data verified February 2026. All costs are estimates based on published API rates and usage modeling. Actual costs will vary based on session behavior, optimization effectiveness, and negotiated enterprise rates.*
