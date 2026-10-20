---
name: comfyui-forge-generate2dsprite
description: Prepare, key, slice, scale, inspect and package supplied character/sprite art locally. Character animation is routed to comfyui-forge-video2dsprite; creating still images is not configured.
---

# Supplied sprite art

Work from user-supplied images. Use scripts/ --help and references/ for master validation, keying, sheet inspection, slicing, scale registration, palettes, atlas packing and engine exports. Inspect appearance and alpha edges at game size.

Character motion from one still belongs to [local video animation](../comfyui-forge-video2dsprite/SKILL.md). This installation does not generate new master stills or call another image tool as a fallback. For motion requiring a substantially different starting pose, follow the action-reference assessment in the linked animation skill: a separate, user-authorized image tool may prepare an approved input asset, but is not a generation route or dependency of this skill. Text alone can describe the pose; a sketch is optional. master_still supports local preparation/inspection only. Keep one scale and common anchor across an action's frames.

## Local installation

This unofficial fork uses ONLY local ComfyUI for generation. No cloud providers, API keys, CLI generation or automatic code-art fallback. Still-image generation is not configured; use supplied images.

Keep the three animation-core skills together: generate2dmedia, generate2dsprite and video2dsprite. Map/code-art tools are optional installations, never automatic fallbacks. Find the permanent repository and configured JSON in `<skills-root>/.comfyui-sprite-forge.install.json` (`project`, `comfyuiConfig`). Use that repository's `.venv/Scripts/python.exe` on Windows or `.venv/bin/python` elsewhere, or another Python with the documented dependencies. Do not copy the author's paths or alter original Sprite Forge settings.

The adapter finds configuration from explicit COMFYUI_FORGE_CONFIG, then the installed manifest, then repository-local local-comfyui/config.local.json. No global environment changes are required. Read the configured API JSON before adapting a workflow; the user's ComfyUI must already run it.

For master_still pad/approve, input extraction is independent of output key colour: preserve native alpha or attempt any flat opaque backdrop using the sibling animation skill's comfyui_forge_background_input.py. Inspect the result; if extraction/quality fails, stop for the user to repair the input. Do not assume the source backdrop is the requested output key. See the animation skill's references/prompt-rules.md.
