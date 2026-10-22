---
name: comfyui-forge-generate2dmedia
description: Generate image-to-video only through local ComfyUI; check local workflow nodes and model filenames and resume existing jobs without re-submitting. Use when another Forge skill needs local generation.
---

# Local ComfyUI provider

`scripts/comfyui_forge_route_media.py` is the only generation entry point. auto/comfyui/local:comfyui all mean the same local provider. Other routes and provider flags are rejected. `image` reports unsupported and stops without fallback.

- `python scripts/comfyui_forge_media.py --check`: local read-only nodes/models check, no generation.
- `python scripts/comfyui_forge_doctor.py --save REPORT.json`: save a local readiness report.
- `python scripts/comfyui_forge_route_media.py video --reference INPUT --prompt-file PROMPT --duration 3 --out-dir NEW --dry-run`: validate without network or filesystem writes.
- Omit --dry-run only when the user requests generation. Canvas comes from reference dimensions. Use the source dimensions/duration confirmed by the animation specification flow, with32-multiple dimensions; frame count uses shared `comfyui_forge_frame_rules.py`. Source timing is fixed at24fps,17k+5,min5; conflicting settings are rejected. Requested seconds may be fractional; submitted frame count is always an integer.
- `python scripts/comfyui_forge_media.py --inspect FOLDER`: read queue/history to identify an unknown submission; no files or server state are modified.
- `python scripts/comfyui_forge_media.py --resume FOLDER`: poll a pending job or verify a completed artifact, no resubmission. Unknown outcomes require queue/history inspection.

Configuration discovery is documented below. For a user's own API-format graph, read [workflow mapping](references/local-workflow.md). Bind nodes from the supplied graph. Output history must contain an MP4 from the configured node; arbitrary SaveVideo shapes are not universally supported.

Only HTTP loopback endpoints are accepted, proxies are ignored and redirects rejected. Independently installed ComfyUI custom nodes are outside this adapter's network boundary.

## Runtime setup

Find the repository and configuration in `<skills-root>/.comfyui-sprite-forge.install.json` (`project`, `comfyuiConfig`). Use the repository's `.venv/Scripts/python.exe` on Windows or `.venv/bin/python` elsewhere, or a Python with the documented dependencies. Installation steps are in the repository's `INSTALL.md`.

Configuration discovery order: explicit `COMFYUI_FORGE_CONFIG`, installed manifest, then repository-local `local-comfyui/config.local.json`.
