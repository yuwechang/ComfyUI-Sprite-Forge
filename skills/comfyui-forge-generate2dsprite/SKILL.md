---
name: comfyui-forge-generate2dsprite
description: Prepare, key, slice, scale, inspect and package supplied character/sprite art locally. Character animation is routed to comfyui-forge-video2dsprite; creating still images is not configured.
---

# Supplied sprite art

Work from user-supplied images. Use scripts/ --help and references/ for master validation, keying, sheet inspection, slicing, scale registration, palettes, atlas packing and engine exports. Inspect appearance and alpha edges at game size.

Character motion from one still belongs to [local video animation](../comfyui-forge-video2dsprite/SKILL.md). This installation does not generate new master stills or call another image tool as a fallback. master_still generation will stop because no image workflow is configured; use its prepare/inspection capabilities only where appropriate. Keep one scale and common anchor across an action's frames.

## Local installation

This unofficial fork uses ONLY local ComfyUI for generation. No cloud providers, API keys, CLI generation or automatic code-art fallback. Still-image generation is not configured; use supplied images. Do not follow historical upstream generation instructions in retained references when they conflict with this policy.

Keep all five comfyui-forge-* sibling skills. Find the permanent repository and configured JSON in `<skills-root>/.comfyui-sprite-forge.install.json` (`project`, `comfyuiConfig`). Use that repository's `.venv/Scripts/python.exe` on Windows or `.venv/bin/python` elsewhere, or another Python with the documented dependencies. Do not copy the author's paths or alter original Sprite Forge settings.

The adapter finds configuration from explicit COMFYUI_FORGE_CONFIG, then the installed manifest, then repository-local local-comfyui/config.local.json. No global environment changes are required. Read the configured API JSON before adapting a workflow; the user's ComfyUI must already run it.
