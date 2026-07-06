# SA3 SFX Generation — "Pure Noise" Investigation (handoff brain-dump)

**Status:** RESOLVED (2026-07-05 ~22:50) — generation works again; the failure
was transient machine state, not code, params, weights, or dependencies. See
§12 for the follow-up forensics that closed every lead in this doc. Historical
content below kept for the record.

Written: 2026-07-05, end of the sprint-038 (M22) session, on branch
`paulingalls/story-003-regen-legacy-sfx`.

---

## 1. Objective when this started

Sprint-038 / M22 "Audio Completeness", **story-003**: regenerate the 20 legacy
combat/dice/UI/world SFX in `apps/mobile/assets/sounds/*.mp3` via the in-repo
SA3 generator, so every bundled SFX is regenerable from a committed prompt
(the "Audio Must Be Generatable" principle), replacing hand-sourced `.mp3`.

- Prompts already exist: `scripts/audio/generate_spell_sfx.py:PROMPTS` (all 57
  bundled stems, added in story-001).
- The generator: `scripts/audio/generate_spell_sfx_stableaudio.py` (story-002
  added a `--format mp3` ffmpeg transcode path).
- Plan was: run the generator for the 20 legacy keys → audition in Finder →
  commit approved takes. **The generator produces noise, so nothing shipped.**

## 2. Expected vs. observed

- **Expected:** running `generate_spell_sfx_stableaudio.py` (which calls
  `StableAudioModel.generate(...)` from the `stable_audio_3` package, loading
  `stabilityai/stable-audio-3-small-sfx`) produces recognizable SFX, the way it
  did at M17 (the committed spell palette is good, customer-approved in a live
  bake-off).
- **Observed:** every generated clip is **pure noise** (customer auditioned
  multiple; unambiguous). Confirmed noise from BOTH our wrapper AND the
  package's own official `stable-audio` CLI.

## 3. The core contradiction

Same machine, same day:
- **M17 session** (`f1823996-…jsonl`, 2026-07-05 **15:54**): generated the 7
  spell SFX via `stable_audio_3` → **good** (customer A/B bake-off approved,
  committed to `apps/audio/spell_sfx/` + `apps/mobile/assets/sounds/`).
- **This session** (2026-07-05 **~22:00**): identical package + identical cached
  weights → **noise**.

Nothing we could identify changed except elapsed time. This is the crux.

## 4. Environment facts (verified)

### The SA3 package
- `stable-audio-3 == 0.1.0`, installed from
  `git+https://github.com/Stability-AI/stable-audio-3.git@ea9ba361f9e58da6afed1304657e20fda701a9a4`
  (the pin in `scripts/audio/setup_sfx_env.sh`).
- **NOT on PyPI** — `uv pip install stable-audio-3` (no ref) fails "not found in
  the package registry". So the docstring's `pip install stable-audio-3` and the
  git pin resolve to the *same* single 0.1.0; there is no alternate version.
- `StableAudioModel.from_pretrained(model_name)` validates against `all_models`
  (raises on unknown), and `"small-sfx"` is valid → the right model is selected.
- `StableAudioModel.generate(...)` signature defaults: **`steps=8, cfg_scale=1.0`**
  (`site-packages/stable_audio_3/model.py:77`). Output is clamped to `[-1,1]`
  float32 at `model.py:345`, so noise is NOT a save/normalization artifact.
- Package ships an official CLI: `stable-audio` (`stable_audio_3/cli.py`); its
  defaults are also `--steps 8 --cfg-scale 1.0`. `_save_output` just does
  `torchaudio.save(path, audio[i].cpu(), sample_rate)`.
- NOTE: `site-packages/package_readme.md` is a **mis-packaged wandb README**
  (ignore it).

### The model (cached, INTACT)
- `~/.cache/huggingface/hub/models--stabilityai--stable-audio-3-small-sfx/`
  snapshot `ae12755283df9d62ca39a9b050a39a0b607b8c20` (`refs/main`).
- `model.safetensors` = **2,270,384,940 bytes** (~2.27 GB), `t5gemma-b-b-ul2/model.safetensors`
  = **1,183,022,944 bytes** (~1.18 GB), `model_config.json` = 10,454 bytes.
  Total 3.2 GB. **No `.incomplete`/`.lock` files.** Downloaded **Jul 5 14:14**
  — i.e. BEFORE the M17 15:54 session that produced good audio.
- `model_config.json`: `model_type = diffusion_cond_inpaint`, `sample_rate = 44100`,
  `sample_size = 5292032`.
- Gated model; **customer has accepted the HF license** (access confirmed:
  `HfApi().model_info(...)` returns 17 siblings, `gated=auto`). HF token present
  at `~/.cache/huggingface/token`.

### The two venvs
- `scripts/audio/.venv-sa3` — built by `setup_sfx_env.sh` (REBUILT twice this
  session). Has **torch 2.7.1 / torchaudio 2.7.1** (stable-audio-3 HARD-PINS
  `torch==2.7.1`, `torchaudio==2.7.1`), transformers 5.13.0, `stable_audio_3`.
  Note: gitignored at `scripts/audio/.gitignore:2` (`.venv-sa3/`).
- `~/src/clones/stable-audio-tools/venv-sat` — the M17-era harness venv (built
  Mar 2). Has **torch 2.12.0.dev20260302 / torchaudio 2.11.0.dev20260302**,
  `stable_audio_tools 0.0.19`, `soundfile 0.13.1`. This session I added
  `stable_audio_3 0.1.0` via `--no-deps` (kept torch 2.12) and `torchcodec 0.14.0`
  (needed because this torchaudio routes `save()` through torchcodec).

## 5. What was tried, and the result (all NOISE)

| # | Attempt | Env | Result |
|---|---|---|---|
| 1 | `generate_spell_sfx_stableaudio.py`, defaults (steps=8) | .venv-sa3, torch 2.7.1, MPS | NOISE |
| 2 | Bumped `model.generate` to `steps=150, cfg_scale=7` (added `--steps/--cfg-scale` args) | .venv-sa3, torch 2.7.1, MPS | NOISE |
| 3 | Official `stable-audio` CLI, steps 8 AND steps 100/cfg 7 | .venv-sa3, torch 2.7.1, MPS | NOISE (`/tmp/sa3cli/`) |
| 4 | Official CLI `--device cpu`, steps 50/cfg 7 | .venv-sa3, torch 2.7.1, CPU | NOISE (`/tmp/cpu_test/`) |
| 5 | `generate_spell_sfx_stableaudio.py`, steps 8/cfg 1 AND 100/cfg 7 | venv-sat, **torch 2.12 nightly**, MPS | NOISE (`/tmp/sat3_test*`) |

**Therefore ruled out as the cause:** step count, cfg_scale, output
normalization/save path, torch version (2.7.1 *and* 2.12), device (CPU *and*
MPS), our wrapper vs. the official CLI, package version (only 0.1.0 exists),
model-weight integrity (intact, M17-era), and — implicitly — the `transformers`
version (the two venvs have different transformers; both produce noise).

## 6. Dead ends explored

- **`stable_audio_tools` (Open 1.0 harness) cannot load SA3.** `generate_divine_ruin.py`
  + `create_model_from_config` on the SA3 `model_config.json` throws
  `TypeError: TransformerBlock.__init__() got an unexpected keyword argument
  'local_add_cond_dim'` (`stable_audio_tools/models/transformer.py:782`). That
  harness is **Open-1.0-only** (`stable-audio-tools 0.0.19`, model
  `stabilityai/stable-audio-open-1.0`). It generated the older `divine_ruin_audio_v2/`
  assets (March), NOT the M17 SA3 spell palette. Customer confirmed M17 used
  SA3 small-sfx ("the newer stuff", accepted the HF license), so Open 1.0 is not
  the path.
- **The proven Open-1.0 PARAM_PRESETS** (`generate_divine_ruin.py`,
  `dpmpp-3m-sde`, steps 200 / music 250, cfg 5.5–9.0, sigma 0.03/1000, seed
  42+variant) are for `stable_audio_tools`/Open 1.0 — the `stable_audio_3`
  package's `generate()` doesn't take `sampler_type/sigma_min/sigma_max`.

## 7. Strongest un-run lead (recommended first step next session)

**The weights may not actually be binding to the model** → a randomly-initialized
component (esp. the VAE/autoencoder decoder) would emit pure noise regardless of
steps/cfg/torch/device — which fits ALL evidence. Symptom hint: `from_pretrained`
prints `Loading weights: 134/134` **instantly** (~16k–42k it/s).

Concrete checks to run:
- Instrument `load_diffusion_cond` / `from_pretrained` (in `stable_audio_3`,
  `loading_utils.py` / `factory.py` / `model.py`) to print **missing / unexpected
  keys** from the `load_state_dict` call. If the VAE or DiT reports missing keys,
  that's the root cause.
- After load, check a decoder weight tensor's stats (trained vs. `~N(0, init)`).
- Compare the state_dict key names in `model.safetensors` against the model's
  `state_dict()` keys — a prefix/rename mismatch would silently skip loading.

## 8. Other un-run leads

- **Did the machine reboot / take a macOS or Metal/Accelerate update between M17
  (15:54) and now (22:00)?** CPU also fails, which argues against a pure-Metal
  bug, but a system libomp/Accelerate change could still matter. Check `uptime`,
  system update history.
- **Verify the committed good takes still play.** Restore `apps/mobile/assets/sounds/spell_fire.mp3`
  (or the `.wav` at the M17 commit) and confirm it audibly plays a real fire
  spell. (Not yet done this session.) If even the committed audio now sounds
  wrong, something affects playback, not just generation.
- **Find how M17 actually invoked it.** M17 used a now-deleted `/tmp/sa3` temp
  venv: transcript `f1823996-…jsonl` shows
  `/tmp/sa3/bin/python scripts/audio/generate_spell_sfx_stableaudio.py --out-dir /tmp/bakeoff/stableaudio`
  and `--out-dir apps/audio/spell_sfx`, and `afplay "$BAKE/stableaudio/${k}.wav"`
  for the A/B. The exact transitive dep versions in `/tmp/sa3` at 15:54 are
  unrecoverable (venv gone). Re-reading that transcript around the generation +
  bake-off moment may reveal a manual step we missed.

## 9. Key paths / artifacts

- Generator (our wrapper, has uncommitted `--steps/--cfg-scale` edits this session):
  `scripts/audio/generate_spell_sfx_stableaudio.py`
- Prompt SSOT: `scripts/audio/generate_spell_sfx.py:PROMPTS`
- Venv bootstrap (pins the broken git ref, does NOT pin torch): `scripts/audio/setup_sfx_env.sh`
- Working (Open-1.0) harness: `~/src/clones/stable-audio-tools/generate_divine_ruin.py`
  (+ `venv-sat`, `PARAM_PRESETS` at lines ~793-850, `generate_asset` ~877-950)
- Design doc: `docs/audio_sfx_pipeline.md` (§2.5 prior work, §4 keying)
- Model cache: `~/.cache/huggingface/hub/models--stabilityai--stable-audio-3-small-sfx/`
- Noise test outputs (this session): `/tmp/sa3cli/`, `/tmp/cpu_test/`, `/tmp/sat3_test/`, `/tmp/sat3_test_s100/`
- M17 transcripts: `~/.claude/projects/-Users-paulingalls-src-projects-divineruin/f1823996-1f39-4ce0-86cd-51df6360f0ec.jsonl` (bake-off), `ff510ab4-660e-417c-beac-bb8a9112ae7b.jsonl` (last session)
- SMM debt id: `c26e9a4fe04d` (this investigation)

## 10. State of the working tree / sprint (so the next session isn't surprised)

- **Foundation shipped & merged** to `paulingalls/sprint-038-audio-completeness`:
  story-001 (PROMPTS → 57 stems + parity/style guards) and story-002 (spell
  palette `.wav`→`.mp3`, folds the ~2.4 MB `.wav`-bloat debt `4e6fe7870edd`).
- **story-003 is in-progress, solo**, branch `paulingalls/story-003-regen-legacy-sfx`.
  The 20 noise `.mp3` were generated into the working tree then **reverted**
  (`git checkout -- apps/mobile/assets/sounds/`), so the good hand-sourced legacy
  SFX are intact and uncommitted-clean.
- Uncommitted: `scripts/audio/generate_spell_sfx_stableaudio.py` (the
  `--steps/--cfg-scale` additions — harmless, but they did NOT fix the noise;
  keep or revert as you like) and this doc.
- Also broke then rebuilt `.venv-sa3` mid-session (a piecemeal `k-diffusion`
  install upgraded torch and broke `torchaudio`; rebuilt clean via
  `setup_sfx_env.sh`).

## 11. Recommendation

Treat this as **environment/tooling forensics**, not application code. Start a
fresh session focused on §7 (do the weights actually bind?). If confirmed the
model loads correctly and still emits noise, escalate to reproducing the exact
`/tmp/sa3` dependency set from M17 (or Stability's reference inference), rather
than iterating params — params are conclusively not the issue.

---

## 12. RESOLUTION (follow-up session, 2026-07-05 ~22:50)

Every lead above was run to ground; the stack works again with **zero changes**.

**Leads closed:**
- **§7 weights-binding: REFUTED.** All 685 checkpoint keys bind to the model's
  685 `state_dict()` keys (0 dropped, 0 shape mismatches, 0 never-set). The
  T5Gemma encoder binds fully too (`missing_keys: 0`; the 206 "unexpected" keys
  are the unused decoder half of the checkpoint — expected for encoder-only
  load). The instant `Loading weights: 134/134` is normal — safetensors load is
  mmap-based. `bottleneck.noise_scaling_factor` showing `mean=nan` is a red
  herring: `noise_augment_dim=0` makes it an empty tensor (mean of nothing),
  and its use is guarded by `noise_augment_dim > 0`.
- **Weight integrity: PROVEN intact.** HF cache blob filenames are the files'
  sha256; both weight blobs (2.27 GB DiT+VAE, 1.18 GB T5Gemma) checksum-match.
- **Reboot/OS update (§8): NONE.** `uptime` shows the machine up ~30h, spanning
  both the good (15:54) and bad (~22:00) runs; no softwareupdate entries.
- **Dependency drift: NONE.** The M17 "temp venv" was NOT `/tmp/sa3` — it was
  the session scratchpad, and it SURVIVED:
  `/private/tmp/claude-501/-Users-paulingalls-src-projects-divineruin/f1823996-1f39-4ce0-86cd-51df6360f0ec/scratchpad/sa3-venv`
  (plus the original `sfx-bakeoff/stableaudio/*.wav` known-good takes).
  `pip freeze` of that venv vs `.venv-sa3` is **IDENTICAL**.

**The decisive experiment:** re-running the exact M17 command (steps=8,
cfg_scale=1.0) TODAY produces **good audio from BOTH venvs**. Verified by
spectral stats against ground truth: good takes have spectral flatness
~0.002–0.04, RMS-envelope CV ~1.3, std ~0.05; every noise-era output
(`/tmp/sa3cli`, `/tmp/cpu_test`, `/tmp/sat3_test*`) measures flatness 0.2–0.5,
envelope CV ~0.02, std ~0.83 with peak pinned at 1.0 — i.e. a clamped N(0,1)
signal: the initial diffusion noise escaping essentially un-denoised.

**Conclusion:** transient machine state during the 2026-07-05 evening session
(which included two venv rebuilds and multiple 3 GB model loads under sustained
load). It affected every venv/device combination tried that evening and cleared
on its own without a reboot. Exact mechanism not identified; not reproducible.

**Follow-ups for story-003:**
- Revert the uncommitted steps=150/cfg=7 default bump in
  `generate_spell_sfx_stableaudio.py` — its "default 8 = noise" comments are
  now known false, and 150/7 output clips (peak=1.0) where the approved M17
  palette (8/1.0) peaked at ~0.4–0.5.
- The failure mode is silent, so add a cheap post-generation guard to the
  wrapper: if a take's std > ~0.7 (clamped-Gaussian signature), abort and warn
  instead of writing noise for audition.
