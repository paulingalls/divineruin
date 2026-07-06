#!/usr/bin/env bash
# Bootstrap the SFX generation venv reproducibly (M17 / story-002).
#
# Stable Audio 3.0 (torch + the stable-audio-3 package) is NOT a repo dependency —
# it is heavy, build-time-only tooling for (re)generating audio assets. This script
# stands the environment up from the repo on any Mac in one command, at a stable
# gitignored path, with the stable-audio-3 commit pinned for reproducibility — no
# ad-hoc temp venvs. (Docker was considered and rejected: on macOS a container is
# Linux/CPU-only and loses MPS, the whole speed win, for an occasional tool.)
#
# Usage:
#   scripts/audio/setup_sfx_env.sh            # venv at scripts/audio/.venv-sa3
#   scripts/audio/setup_sfx_env.sh /path/venv # custom location
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
VENV="${1:-$HERE/.venv-sa3}"
# Pinned stable-audio-3 commit (Stability-AI/stable-audio-3) — bump deliberately.
SA3_REF="ea9ba361f9e58da6afed1304657e20fda701a9a4"

command -v uv >/dev/null || { echo "uv is required (https://docs.astral.sh/uv/)"; exit 1; }

echo "creating venv at $VENV (python 3.11)"
uv venv "$VENV" --python 3.11
echo "installing stable-audio-3 @ ${SA3_REF:0:12} (pulls torch/torchaudio, heavy) ..."
uv pip install --python "$VENV/bin/python" \
  "git+https://github.com/Stability-AI/stable-audio-3.git@$SA3_REF"

cat <<EOF

Done. Before generating, one-time:
  1. Accept the gated model terms: https://huggingface.co/stabilityai/stable-audio-3-small-sfx
  2. Ensure a HuggingFace token is available (~/.cache/huggingface/token or \$HF_TOKEN).

Generate the spell-cast palette:
  "$VENV/bin/python" scripts/audio/generate_spell_sfx_stableaudio.py --out-dir apps/audio/spell_sfx
EOF
