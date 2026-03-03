# Player Resonance System — Specification & Implementation Plan

## About This Document

This document specifies the Player Resonance System: a real-time feedback loop that lets the DM agent perceive *how* the player is speaking, not just *what* they're saying. It bridges the gap between text-only LLM reasoning and the rich paralinguistic information available in voice — the thing that makes a real-time audio API feel more alive than a text pipeline, without requiring us to give up multi-voice TTS or tool calling.

This is a standalone feature that enhances every existing system without changing any of them. It sits between STT and the LLM as a lightweight analysis layer.

**Integration points:** Technical Architecture (DM Agent → per-turn hot layer injection), Game Design (session pacing, DM behavioral modes), Audio Design (Hollow intensity modulation), Cost Model (negligible incremental cost).

---

## The Problem

Claude generates text. Inworld converts that text to speech. But Claude is deaf to the player. It processes a transcript — bare words stripped of everything that makes spoken language expressive. A real DM reads the table: they hear excitement, notice hesitation, feel the energy drop when someone's losing interest. Our DM gets a string.

Real-time audio APIs (like OpenAI's) get affect perception for free because the model processes raw audio. We can't use those because we need multi-voice TTS output (the ventriloquism system) and structured tool calling. But we can build the affect perception ourselves from signals that are already flowing through our pipeline.

## The Solution

A **Player Affect Analyzer** that runs alongside the STT pipeline, computing a compact affect vector from three signal sources:

1. **Transcript metadata** — word timestamps, utterance length, response latency, question frequency (already available from Deepgram streaming)
2. **Raw audio features** — RMS energy (volume), speech rate from word timing density, silence patterns (available from LiveKit `AudioFrame` PCM data)
3. **Behavioral patterns** — NPC name usage, companion engagement, planning language, character voice adoption (derived from transcript text with lightweight pattern matching)

The affect vector is injected into the DM's per-turn hot layer context alongside existing game state. The DM doesn't receive instructions — it receives *awareness*. It's told what the player sounds like, not what to do about it.

---

## Signal Sources — What We Already Have

### From Deepgram Streaming (zero additional cost)

Every streaming transcription result already includes:

```json
{
  "words": [
    { "word": "hello", "start": 0.0, "end": 0.5, "confidence": 0.99 },
    { "word": "I", "start": 0.6, "end": 0.7, "confidence": 0.98 }
  ],
  "speech_final": true,
  "is_final": true
}
```

**Available signals:**
- **Word timestamps** (`start`, `end` per word) → speech rate (words per second), pause patterns (gaps between words), hesitation detection (long gaps mid-utterance)
- **Utterance boundaries** (`speech_final`, `is_final`) → utterance length in words and duration
- **Confidence scores** → low confidence can indicate mumbling, trailing off, or uncertain speech
- **Response latency** — time between DM TTS completion and player speech onset (derived from comparing DM output end timestamp to first word start timestamp)

**Important constraint:** Deepgram's sentiment analysis is **not available for streaming/live audio** — only pre-recorded. We cannot use it. Everything must come from the streaming response metadata and raw audio.

### From LiveKit AudioFrame (zero additional cost)

The player's audio arrives as `rtc.AudioFrame` objects — raw PCM int16 samples at 48kHz. Before reaching Deepgram, these frames pass through Silero VAD. We can tap into this same stream.

```python
# AudioFrame gives us raw samples
audio_data = np.frombuffer(frame.data, dtype=np.int16)
# RMS energy (volume proxy) is one line
rms = np.sqrt(np.mean(audio_data.astype(np.float32) ** 2))
```

**Available signals:**
- **RMS energy** → volume level per frame, volume trajectory over utterance
- **Energy variance** → monotone (low variance) vs. animated (high variance) speech
- **Silence ratio** — proportion of frames below energy threshold within speech-active regions (hesitation, thinking pauses)

### From Transcript Text (zero additional cost)

Simple pattern matching on the transcript string. No ML model needed.

**Available signals:**
- **Question detection** — ends with `?` or starts with interrogative words
- **NPC/companion name usage** — player says "Kael" or "the blacksmith" unprompted
- **Planning language** — "I want to", "let's", "we should", "what if"
- **Exclamations** — "whoa", "wait", "oh no", "yes!", laughter indicators
- **Command language** — "I attack", "I open", "I cast" (decisive engagement)
- **Minimal responses** — "ok", "sure", "yeah", "uh huh" (low engagement or processing)
- **Repetition/confusion** — restating what the DM just said, asking "wait, what?"

---

## The Affect Vector

The analyzer produces a compact JSON object on every player turn. This is the only output — a small structured payload injected into the hot layer.

```json
{
  "engagement": {
    "level": "high",
    "trend": "rising",
    "signals": ["utterance_length_increasing", "questions_asked", "npc_name_used"]
  },
  "energy": {
    "volume": "moderate",
    "volume_trend": "stable",
    "speech_rate_wps": 3.2,
    "rate_vs_baseline": "+15%",
    "variance": "animated"
  },
  "interaction_style": {
    "mode": "exploratory",
    "signals": ["planning_language", "question_frequency_high"]
  },
  "response_latency_ms": 1200,
  "latency_vs_baseline": "-20%",
  "turn_number": 14,
  "session_duration_min": 12.5
}
```

### Field Definitions

**engagement.level** — `high` | `moderate` | `low` | `minimal`
- Composite of utterance length trend, question frequency, name usage, planning language
- `high`: long utterances, asking questions, using names, making plans
- `moderate`: normal-length responses, some questions
- `low`: short responses, no questions, no names
- `minimal`: single-word responses, extended silence between turns

**engagement.trend** — `rising` | `stable` | `falling`
- Sliding window over last 5 turns comparing engagement level

**energy.volume** — `quiet` | `moderate` | `loud`
- Mean RMS of the utterance relative to session baseline

**energy.volume_trend** — `rising` | `stable` | `falling`
- Volume trajectory over last 5 turns

**energy.speech_rate_wps** — float
- Words per second derived from Deepgram word timestamps

**energy.rate_vs_baseline** — string percentage
- Current speech rate compared to the player's session average

**energy.variance** — `monotone` | `moderate` | `animated`
- Energy variance within the utterance. Animated speech = invested. Monotone = disengaged or tired.

**interaction_style.mode** — `exploratory` | `decisive` | `social` | `cautious` | `confused` | `passive`
- Derived from transcript patterns:
  - `exploratory`: questions, "what if", looking around, investigating
  - `decisive`: commands, action verbs, "I attack", "I open"
  - `social`: talking to NPCs, companion interaction, asking about people
  - `cautious`: hedging language, "is it safe", asking about risks
  - `confused`: repetition, "wait what", restating DM's words
  - `passive`: minimal responses, acknowledgments only

**response_latency_ms** — int
- Milliseconds between DM TTS output ending and player's first word

**latency_vs_baseline** — string percentage
- Faster responses = engaged/excited. Slower = thinking/disengaged/awed.

---

## Architecture — Where It Lives

```
Player Audio (LiveKit AudioFrame)
    │
    ├──► Silero VAD (existing) ──► Deepgram STT (existing)
    │                                      │
    │                                      ▼
    │                              Transcript + word timestamps
    │                                      │
    ▼                                      ▼
┌──────────────────────────────────────────────┐
│         Player Affect Analyzer               │
│                                              │
│  Audio Features    Transcript     Behavioral │
│  ─────────────     Metadata       Patterns   │
│  RMS energy        Speech rate    Questions   │
│  Energy variance   Latency        Names       │
│  Silence ratio     Utt. length    Commands    │
│                    Confidence     Planning    │
│                                              │
│  ──────────► Affect Vector ◄──────────       │
│              (JSON, ~200 bytes)               │
└──────────────────┬───────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────┐
│  DM Agent — on_user_turn_completed           │
│                                              │
│  Existing hot layer:                         │
│    - Location, NPCs, quests, HP, combat      │
│                                              │
│  + NEW: Player affect context                │
│    "Player affect: high engagement (rising),  │
│     speech rate +15% above baseline,          │
│     exploratory mode — asking questions,      │
│     used companion name unprompted.           │
│     Response latency 20% faster than usual." │
│                                              │
└──────────────────────────────────────────────┘
```

The analyzer is a Python class instantiated per session, running inside the DM agent process. It maintains a rolling window of per-turn metrics to compute baselines and trends. It receives audio frames from the same stream that feeds VAD/STT, and transcript results from the STT callback.

**Latency impact: near-zero.** Audio feature extraction (RMS, variance) runs on frames that have already been buffered for STT. Transcript analysis runs after STT completes. Neither is on the critical path — the affect vector is computed in parallel and ready by the time `on_user_turn_completed` fires.

**Token impact: ~50-80 tokens per turn** for the affect context injection. At Claude's prompt caching rates, this is negligible.

---

## What the DM Does With It

The affect vector is injected as natural language in the hot layer, not as structured data the LLM must parse. The DM's system prompt includes guidance on how to interpret affect context:

```
## Player Awareness

You receive a player affect reading each turn. This tells you HOW the player
is speaking, not just what they said. Use it the way a human DM reads the table:

- If engagement is falling, shift the energy. Introduce something unexpected.
  Have a companion speak up. Don't lecture — provoke.
- If the player is confused, slow down. Have an NPC rephrase. Offer a clear
  choice instead of an open field.
- If engagement is high and rising, ride it. Lean into whatever they're
  excited about. Give them more of what's working.
- If speech rate is fast and volume is up, they're excited or anxious. Match
  the energy in narration.
- If responses are getting shorter and latency is increasing, they may be
  fatigued. Steer toward a natural stopping point or a satisfying beat.
- If they're in exploratory mode, reward curiosity. Drop lore hints, add
  environmental details, let NPCs volunteer information.
- If they're in decisive mode, don't slow them down. Resolve actions quickly,
  keep momentum.

Never mention the affect system to the player. Never say "you seem excited"
or "I notice you're confused." Act on the awareness naturally, the way a
perceptive human would.
```

### Concrete DM Behavioral Shifts

| Affect Signal | DM Response |
|---|---|
| Engagement falling + short responses | Companion initiates conversation: "You've been quiet. Something on your mind?" Or: unexpected event breaks monotony. |
| High engagement + exploratory | More environmental detail, NPC lore volunteered, hidden details revealed on investigation |
| Fast speech + loud + decisive | Quick narration, actions resolve fast, momentum maintained |
| Slow responses + low energy + monotone | Gentle steering toward stopping point: "The fire burns low in the hearth..." |
| Confused + repetition + questions | NPC or companion rephrases. Offer clear A/B/C choices. Simplify scene. |
| Social mode + companion names | Companion responds with more personality. NPCs become chattier. Social encounters deepen. |
| Cautious + hedging | Validate caution with environmental cues. Reward careful play. Don't punish slowness. |
| Player laughs or exclaims | DM leans into humor or drama. The moment that got a reaction gets extended. |

### Hollow Intensity Modulation

The Hollow's audio and narrative intensity can modulate based on player affect:

- Player showing genuine unease (quieter, slower, longer pauses) → Hollow intensity holds steady or eases slightly. Ride the edge, don't break immersion by going too far.
- Player calm and clinical about Hollow → increase intensity. They haven't felt it yet.
- Player excited/engaged during Hollow encounter → this is working, maintain current level.

This is opt-in DM behavior guided by the system prompt, not a hard-coded system.

---

## Implementation Plan

### Phase A: Transcript-Only Baseline (Add to Milestone 2.3 — DM Conversation)

**Goal:** Get the simplest useful version working using only data we already have from Deepgram.

**What to build:**
- `PlayerAffectAnalyzer` class with session-scoped state
- Transcript metrics: utterance word count, question detection, response latency, speech rate from word timestamps
- Engagement level computation (composite heuristic)
- Affect vector generation (text-only fields)
- Injection into `on_user_turn_completed` hot layer
- System prompt additions for player awareness

**What we skip:** All audio-level features (RMS, energy variance). All behavioral pattern matching beyond questions.

**Acceptance criteria:**
- [ ] Analyzer produces engagement level (high/moderate/low/minimal) for each turn
- [ ] Speech rate (WPS) computed from Deepgram word timestamps
- [ ] Response latency measured (DM TTS end → player speech start)
- [ ] Engagement trend computed over sliding window
- [ ] Affect context injected into hot layer as natural language
- [ ] DM system prompt includes player awareness section
- [ ] DM demonstrably changes behavior when given high vs. low engagement affect (test with synthetic transcripts)

**Dependencies:** Milestone 2.3 (basic DM conversation working)

**Key references:**
- Technical Architecture → DM Agent → Per-Turn Hot Layer
- Technical Architecture → DM Agent → Layer 1 (on_user_turn_completed)

### Phase B: Audio Feature Extraction (Add to Milestone 5.3 — Audio Engine)

**Goal:** Add volume and energy analysis from raw audio frames.

**What to build:**
- Audio frame tap in the player audio pipeline (before or alongside VAD)
- Per-utterance RMS energy computation from `AudioFrame.data` PCM samples
- Energy variance computation
- Volume baseline tracking (per-session rolling average)
- Volume trend (sliding window over last 5 turns)
- Add energy fields to affect vector

**What we skip:** Spectral analysis, pitch tracking, formant extraction. Keep it to time-domain features that are trivially cheap.

```python
import numpy as np

class AudioFeatureExtractor:
    """Extracts simple audio features from PCM frames during an utterance."""
    
    def __init__(self):
        self._frames: list[np.ndarray] = []
        self._session_rms_history: list[float] = []
    
    def push_frame(self, frame: rtc.AudioFrame) -> None:
        """Called for each audio frame during active speech."""
        samples = np.frombuffer(frame.data, dtype=np.int16).astype(np.float32)
        self._frames.append(samples)
    
    def compute_utterance_features(self) -> dict:
        """Called at end of utterance. Returns audio features and resets."""
        if not self._frames:
            return {"volume": "unknown", "variance": "unknown"}
        
        all_samples = np.concatenate(self._frames)
        rms = np.sqrt(np.mean(all_samples ** 2))
        
        # Per-frame RMS for variance calculation
        frame_rms = [np.sqrt(np.mean(f ** 2)) for f in self._frames]
        rms_variance = np.std(frame_rms) / (np.mean(frame_rms) + 1e-8)
        
        self._session_rms_history.append(rms)
        baseline = np.mean(self._session_rms_history)
        
        self._frames = []
        
        return {
            "rms": float(rms),
            "rms_vs_baseline": float((rms - baseline) / (baseline + 1e-8)),
            "variance": "animated" if rms_variance > 0.3 else "moderate" if rms_variance > 0.15 else "monotone",
            "volume": "loud" if rms > baseline * 1.3 else "quiet" if rms < baseline * 0.7 else "moderate",
        }
```

**Acceptance criteria:**
- [ ] RMS energy computed per utterance from AudioFrame data
- [ ] Energy variance classified as monotone/moderate/animated
- [ ] Volume classified relative to session baseline
- [ ] Volume trend tracked over sliding window
- [ ] Audio features appear in affect vector
- [ ] No measurable latency impact on voice pipeline (< 1ms added)

**Dependencies:** Phase A complete, Milestone 5.3 (audio engine integration)

### Phase C: Behavioral Pattern Matching (Add to Milestone 6.2 — Companion System)

**Goal:** Detect richer interaction patterns from transcript content.

**What to build:**
- Pattern matcher for NPC/companion name usage (check against known entity names from session state)
- Planning language detection ("I want to", "let's", "we should", "what if")
- Command language detection ("I attack", "I open", "I cast", "I go")
- Minimal response detection ("ok", "sure", "yeah", "uh huh", single-word turns)
- Confusion signals ("wait", "what?", restating DM's last sentence)
- Interaction style mode classification (exploratory/decisive/social/cautious/confused/passive)
- Laughter/exclamation detection (transcript-level: "haha", exclamation marks, interjections)

**Acceptance criteria:**
- [ ] Interaction style mode correctly classified across test transcripts
- [ ] NPC name usage detected and included in affect signals
- [ ] Confusion detection triggers on restated/repeated content
- [ ] Companion responds to behavioral signals (Phase C enables companion "noticing" player mood)
- [ ] Full affect vector produced with all three signal sources

**Dependencies:** Phase B complete, Milestone 6.2 (companion system where behavioral signals become most valuable)

### Phase D: Tuning and Calibration (Part of Milestone 9.1 — Internal Playtest)

**Goal:** Calibrate thresholds and DM responses against real player behavior.

**What to do:**
- Record affect vectors during playtest sessions
- Correlate affect signals with actual player experience (post-session survey)
- Tune engagement thresholds (what speech rate / utterance length actually indicates "high" vs "low")
- Tune DM system prompt guidance based on observed behavior
- Add per-player baseline calibration (first 3-5 turns establish baseline for that player's speaking style)
- Identify false positives (player thinking deeply misread as disengaged)

**Acceptance criteria:**
- [ ] Engagement level correlates with post-session self-reported engagement (>0.6 correlation)
- [ ] DM behavioral shifts perceived as natural by playtesters (not jarring or patronizing)
- [ ] No player reports feeling "watched" or manipulated
- [ ] Per-player calibration prevents soft-spoken players from always reading as "low energy"

---

## Cost Impact

| Component | Additional Cost | Notes |
|---|---|---|
| Deepgram | $0.00 | Word timestamps already in streaming response |
| Audio features | $0.00 | Computed from frames already in memory |
| Pattern matching | $0.00 | String matching on transcript already available |
| LLM context | ~$0.0001/turn | ~60 extra tokens in hot layer, cached at 90% |
| **Per session (30 min, ~60 turns)** | **~$0.006** | Effectively free |

---

## Future Extensions (Post-MVP)

These are not in scope but worth noting as the system matures:

- **Pitch tracking** — Extract fundamental frequency (F0) from audio. Rising pitch at end of utterance = uncertainty/question even without question mark. Sustained high pitch = excitement. Dropping pitch = trailing off. Requires lightweight pitch detection (e.g., YIN algorithm) but adds genuine prosodic awareness.
- **Cross-session player profile** — Track per-player baselines across sessions. Some players are naturally quiet speakers. Some always speak fast. Baselines should personalize over time rather than resetting each session.
- **Multiplayer differential** — In multiplayer sessions, compute affect per player. The DM can notice that Player A is dominating the conversation while Player B has gone quiet, and explicitly redirect: "Kira, you've been studying the runes. What do you make of this?"
- **Companion emotional mirroring** — Companions react to player affect independently of DM direction. If the player sounds distressed, Kael's voice gets gentler. If excited, Lira matches the energy. Requires per-companion affect-response mapping.
- **Session pacing automation** — Instead of the DM interpreting affect through prompt guidance, a dedicated pacing system uses affect trends to adjust session structure weights (ambient → guided → structured transitions) algorithmically.

---

## Resolved Technical Questions

### 1. Word-level timestamps from Deepgram through the LiveKit plugin — CONFIRMED AVAILABLE

The `livekit-plugins-deepgram` plugin populates word-level timestamps on every streaming transcription result. The plugin's `_parse_transcription` function extracts each word with `start` and `end` times from Deepgram's response and wraps them as `TimedString` objects:

```python
# From livekit-plugins-deepgram/stt_v2.py — _parse_transcription()
words=[
    TimedString(
        text=word.get("word", ""),
        start_time=word.get("start", 0) + start_time_offset,
        end_time=word.get("end", 0) + start_time_offset,
        start_time_offset=start_time_offset,
    )
    for word in words
]
```

These appear on `SpeechData.words` (a `list[TimedString] | None`) on every `SpeechEvent` of type `FINAL_TRANSCRIPT`, `INTERIM_TRANSCRIPT`, and `PREFLIGHT_TRANSCRIPT`. Each `TimedString` has `.start_time`, `.end_time`, and `.confidence` attributes.

**How to access in the agent:** The `on_user_turn_completed` hook receives a `ChatMessage` (the `new_message` parameter). The transcript text is available via `new_message.text_content()`. To get word-level timing, we need to capture `SpeechEvent` data from the STT stream. Two approaches:

**Approach A — Override `stt_node` to tap events.** The `stt_node` yields `SpeechEvent` objects. We override it, pass events through to the default pipeline, and simultaneously extract word timing data into our `PlayerAffectAnalyzer`:

```python
async def stt_node(self, audio, model_settings):
    async for event in Agent.default.stt_node(self, audio, model_settings):
        # Tap word-level data for affect analysis
        if event.type in (SpeechEventType.FINAL_TRANSCRIPT, SpeechEventType.INTERIM_TRANSCRIPT):
            for alt in event.alternatives:
                if alt.words:
                    self._affect_analyzer.push_stt_event(alt)
        yield event
```

**Approach B — Override `stt_node` to tap audio AND events.** For Phase B (audio features), we extend the override to also capture raw audio frames:

```python
async def stt_node(self, audio, model_settings):
    async def tapped_audio():
        async for frame in audio:
            # Tap raw audio for energy analysis
            self._affect_analyzer.push_audio_frame(frame)
            yield frame
    
    async for event in Agent.default.stt_node(self, tapped_audio(), model_settings):
        if event.type in (SpeechEventType.FINAL_TRANSCRIPT, SpeechEventType.INTERIM_TRANSCRIPT):
            for alt in event.alternatives:
                if alt.words:
                    self._affect_analyzer.push_stt_event(alt)
        yield event
```

This is clean — both audio and transcript tapping happen in a single `stt_node` override, data flows to the analyzer in parallel, and the default pipeline is unmodified.

### 2. Audio frame access point — CONFIRMED VIA stt_node OVERRIDE

The `stt_node` receives `audio: AsyncIterable[rtc.AudioFrame]` as its first parameter — the raw audio stream from the player's track. This is the same stream that feeds into Deepgram. By wrapping this iterable (as shown above), we can extract audio features from every frame before it reaches STT, with zero latency impact on the pipeline.

The `AudioFrame` object provides:
- `frame.data` — raw PCM bytes (int16), readable as `np.frombuffer(frame.data, dtype=np.int16)`
- `frame.sample_rate` — sample rate in Hz (typically 48000)
- `frame.num_channels` — number of audio channels
- `frame.samples_per_channel` — samples per channel in this frame

This gives us everything needed for RMS energy, energy variance, and silence ratio computation.

### 3. Baseline calibration window — 5 TURNS, WITH PROGRESSIVE CONFIDENCE

Initial analysis uses hardcoded thresholds for the first 5 turns (conservative defaults — assume moderate engagement, moderate energy). After 5 turns, switch to per-player baselines.

The affect vector includes a `calibration_confidence` field during the first 5 turns:
- Turns 1-2: `"calibration_confidence": "low"` — barely useful, very conservative signals
- Turns 3-4: `"calibration_confidence": "medium"` — baselines forming, trends possible
- Turn 5+: `"calibration_confidence": "high"` — baselines established, full affect reporting

The DM system prompt is told to weight affect signals by calibration confidence — don't make dramatic behavioral shifts based on low-confidence reads.

### 4. DM prompt weight — LIGHT TOUCH, AWARENESS NOT INSTRUCTIONS

The system prompt should frame affect data as awareness, not directives. The DM should:
- **Always** adjust pacing when engagement is clearly falling (3+ consecutive declining turns)
- **Sometimes** adjust narration style based on energy/interaction mode
- **Never** explicitly mention the system or say "you seem [emotion]"

The prompt language should use "you notice" framing ("You notice the player is asking lots of questions and leaning into exploration") rather than imperative framing ("Slow down and add more detail"). This gives Claude the awareness while letting it decide how to respond naturally.

Calibration during Phase D: record DM behavioral shifts alongside affect vectors. If shifts feel jarring to playtesters, reduce prompt weight. If shifts feel invisible, increase it.

### 5. Privacy — SILENT FEATURE, DISCLOSED IN PRIVACY POLICY

The system should be experienced, not explained. Players should feel "this DM is unusually responsive" without being told why. The feature analyzes voice characteristics in real-time and retains only aggregate metrics (speech rate, engagement level) per session — no raw audio is stored, no emotional profiles are built across sessions (until the post-MVP cross-session extension).

**Disclosure approach:** Include in the app's privacy policy that voice characteristics are analyzed in real-time to improve the game experience. Don't surface it in onboarding or UI. If asked directly by a player, the DM should not acknowledge the system (it's a game-world character). The app's settings or FAQ can explain that "the DM adapts to your play style" without technical details.

This matches how human DMs work — they read the room without announcing "I'm now performing sentiment analysis on your facial expressions."
