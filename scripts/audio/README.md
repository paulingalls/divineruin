# Audio generation scripts

Build-time tooling for (re)generating the bundled audio in
`apps/mobile/assets/sounds/` from committed prompts ("Audio Must Be
Generatable" — regeneration is generative, not byte-for-byte). None of this is
a repo dependency; the heavy ML stack lives in a gitignored venv.

## Files

| File | Role |
|---|---|
| `generate_spell_sfx.py` | ElevenLabs generator. Owns `PROMPTS`, the single prompt SSOT for every bundled stem, and the shared `out_path` naming helper. Stdlib-only. |
| `generate_spell_sfx_stableaudio.py` | Stable Audio 3 (SA3) Small SFX generator — the engine that won the story-002 bake-off and produced the committed spell palette. Imports `PROMPTS` from the script above. |
| `setup_sfx_env.sh` | One-command bootstrap of the SA3 venv at `scripts/audio/.venv-sa3` (gitignored), with the `stable-audio-3` commit pinned. |

## One-time setup (SA3)

```sh
scripts/audio/setup_sfx_env.sh
```

Then, once per machine/account:

1. Accept the gated model terms: https://huggingface.co/stabilityai/stable-audio-3-small-sfx
2. Have a HuggingFace token available (`~/.cache/huggingface/token` or `$HF_TOKEN`).

First generation run downloads ~3.2 GB of weights into the HF cache.

## Generating

```sh
# All 57 stems (skips files that already exist in --out-dir)
scripts/audio/.venv-sa3/bin/python scripts/audio/generate_spell_sfx_stableaudio.py \
  --out-dir /tmp/takes

# A subset, with 3 takes per key to audition
scripts/audio/.venv-sa3/bin/python scripts/audio/generate_spell_sfx_stableaudio.py \
  --out-dir /tmp/takes --keys spell_fire dice_roll --variants 3
```

Output is `.mp3` by default (`--format wav` keeps the raw render). Naming:
`<key>.mp3` for a single take, `<key>_v<N>.mp3` with `--variants`.

### The recipe

`--steps 8 --cfg-scale 1.0` (the defaults) are the recipe behind the
customer-approved M17 palette; a fast-lane test pins them. Don't raise
`--cfg-scale` casually — cfg 7 overdrives the output into clipping and buzz.

Every take passes a noise guard: renders matching the clamped-Gaussian noise
signature (std > 0.7) abort loudly instead of writing a garbage file.

### ElevenLabs (A/B alternative)

```sh
export ELEVEN_LABS_API_KEY=...
python scripts/audio/generate_spell_sfx.py --out-dir /tmp/bakeoff --variants 2
```

Both engines share the frozen `PROMPTS`, so their takes stay comparable.

## Troubleshooting

- **Every render is pure noise:** known transient machine-state failure, not a
  code/params/weights problem — see `docs/audio_sa3_noise_investigation.md`
  (§12 has the forensics). The noise guard catches it; retry later rather than
  tuning parameters.
- **403 / gated errors from HF:** license not accepted, or the token env value
  is quote-wrapped — strip the quotes.
- Pipeline design and prompt keying: `docs/audio_sfx_pipeline.md`.
