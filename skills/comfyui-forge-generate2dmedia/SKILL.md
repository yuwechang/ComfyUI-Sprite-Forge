---
name: comfyui-forge-generate2dmedia
description: Generate image-to-video only through local ComfyUI; check local workflow nodes and model filenames and resume existing jobs without re-submitting. No cloud, credentials or CLI fallback. Use when another Forge skill needs local generation.
---

# Local ComfyUI provider

`scripts/route_media.py` is the only generation entry point. auto/comfyui/local:comfyui all mean the same local provider. Other routes and provider flags are rejected. `image` reports unsupported and stops without fallback.

- `python scripts/comfyui_media.py --check`: local read-only nodes/models check, no generation.
- `python scripts/forge_doctor.py --save REPORT.json`: same local readiness, never key/CLI inspection.
- `python scripts/route_media.py video --reference INPUT --prompt-file PROMPT --duration 3 --out-dir NEW --dry-run`: validate without network or filesystem writes.
- Omit --dry-run only when the user requests generation. Canvas comes from reference dimensions; --resolution does not resize it. Request3s,24fps,32-multiple dimensions; frame count follows configured cadence.
- `python scripts/comfyui_media.py --resume FOLDER`: poll a pending job or verify a completed artifact, no resubmission. Unknown outcomes require queue/history inspection.

Configuration discovery is documented below. For a user's own API-format graph, read [workflow mapping](references/local-workflow.md). Do not guess node IDs, alter ComfyUI or download models. Output history must contain an MP4 from the configured node; arbitrary SaveVideo shapes are not universally supported.

Only HTTP loopback endpoints are accepted, proxies are ignored and redirects rejected. Independently installed ComfyUI custom nodes are outside this adapter's network boundary. Model filenames are not evidence of official provenance.

## Local installation

This unofficial fork uses ONLY local ComfyUI for generation. No cloud providers, API keys, CLI generation or automatic code-art fallback. Still-image generation is not configured; use supplied images. Do not follow historical upstream generation instructions in retained references when they conflict with this policy.

Keep all five comfyui-forge-* sibling skills. Find the permanent repository and configured JSON in `<skills-root>/.comfyui-sprite-forge.install.json` (`project`, `comfyuiConfig`). Use that repository's `.venv/Scripts/python.exe` on Windows or `.venv/bin/python` elsewhere, or another Python with the documented dependencies. Do not copy the author's paths or alter original Sprite Forge settings.

The adapter finds configuration from explicit COMFYUI_FORGE_CONFIG, then the installed manifest, then repository-local local-comfyui/config.local.json. No global environment changes are required. Read the configured API JSON before adapting a workflow; the user's ComfyUI must already run it.
