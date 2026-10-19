---
name: comfyui-forge-generate2dmap
description: Plan map data and process supplied terrain, tiles, props and backgrounds with local validation and export tools. Use for existing map art; new still-image generation is not configured.
---

# Supplied map art and map data

Use existing images plus structured layouts, collision, navigation and reachability checks. Inspect scripts/ --help and references/ for layer preparation, map validation and engine export. Do not generate missing terrain or props through a cloud/API/host image route. Ask for source art when needed.

Character work belongs to [supplied sprite tools](../comfyui-forge-generate2dsprite/SKILL.md) or [local character animation](../comfyui-forge-video2dsprite/SKILL.md). Do not claim a configured still-image workflow exists.

## Local installation

This unofficial fork uses ONLY local ComfyUI for generation. No cloud providers, API keys, CLI generation or automatic code-art fallback. Still-image generation is not configured; use supplied images. Do not follow historical upstream generation instructions in retained references when they conflict with this policy.

Keep all five comfyui-forge-* sibling skills. Find the permanent repository and configured JSON in `<skills-root>/.comfyui-sprite-forge.install.json` (`project`, `comfyuiConfig`). Use that repository's `.venv/Scripts/python.exe` on Windows or `.venv/bin/python` elsewhere, or another Python with the documented dependencies. Do not copy the author's paths or alter original Sprite Forge settings.

The adapter finds configuration from explicit COMFYUI_FORGE_CONFIG, then the installed manifest, then repository-local local-comfyui/config.local.json. No global environment changes are required. Read the configured API JSON before adapting a workflow; the user's ComfyUI must already run it.
