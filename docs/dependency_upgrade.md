# Python dependency upgrade

Registry snapshot: 2026-09-18  
Toolchain: CPython 3.14.7; uv 0.10.6

## apps/agent

| Group | Dependency | Requested | Resolved / installed | Latest stable | Holdback |
|---|---|---|---|---|---|
| runtime | livekit-agents | `~=1.8.2` | 1.8.2 / 1.8.2 | 1.8.2 | — |
| runtime | livekit-plugins-anthropic | `~=1.8.2` | 1.8.2 / 1.8.2 | 1.8.2 | — |
| runtime | livekit-plugins-deepgram | `~=1.8.2` | 1.8.2 / 1.8.2 | 1.8.2 | — |
| runtime | livekit-plugins-inworld | `~=1.8.2` | 1.8.2 / 1.8.2 | 1.8.2 | — |
| runtime | asyncpg | `>=0.31.0` | 0.31.0 / 0.31.0 | 0.31.0 | — |
| runtime | redis | `>=8.1.0` | 8.1.0 / 8.1.0 | 8.1.0 | — |
| runtime | anthropic | `>=0.125.0,<1` | 0.125.0 / 0.125.0 | 1.7.0 | livekit-plugins-anthropic==1.8.2 requires anthropic<1,>=0.41: Anthropic 1.7.0 is outside the plugin's published constraint; the project mirrors the same <1 cap. |
| runtime | httpx | `>=0.28.1` | 0.28.1 / 0.28.1 | 0.28.1 | — |
| dev | docker | `>=7.2.0` | 7.2.0 / 7.2.0 | 7.2.0 | — |
| dev | pillow | `>=12.3.0` | 12.3.0 / 12.3.0 | 12.3.0 | — |
| dev | pyright | `>=1.1.414` | 1.1.414 / 1.1.414 | 1.1.414 | — |
| dev | pytest | `>=9.1.1` | 9.1.1 / 9.1.1 | 9.1.1 | — |
| dev | pytest-asyncio | `>=1.4.0` | 1.4.0 / 1.4.0 | 1.4.0 | — |
| dev | pytest-bdd | `>=8.1.0` | 8.1.0 / 8.1.0 | 8.1.0 | — |
| dev | pytest-cov | `>=7.1.0` | 7.1.0 / 7.1.0 | 7.1.0 | — |
| dev | pytest-xdist | `>=3.8.0` | 3.8.0 / 3.8.0 | 3.8.0 | — |
| dev | ruff | `>=0.16.8` | 0.16.8 / 0.16.8 | 0.16.8 | — |
| dev | testcontainers | `>=4.15.0` | 4.15.0 / 4.15.0 | 4.15.0 | — |

## scripts

| Group | Dependency | Requested | Resolved / installed | Latest stable | Holdback |
|---|---|---|---|---|---|
| runtime | asyncpg | `>=0.31.0` | 0.31.0 / 0.31.0 | 0.31.0 | — |

The committed `uv.lock` files are the exact transitive dependency record.
