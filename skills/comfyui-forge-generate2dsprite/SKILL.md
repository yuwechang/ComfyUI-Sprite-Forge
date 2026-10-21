---
name: comfyui-forge-generate2dsprite
description: Prepare and approve a supplied character reference for this project's local ComfyUI video-to-sprite workflow. Not a standalone still-art, sheet-processing or engine-export skill.
---

# Video reference preparation

Use this helper only to inspect, key, pad and approve supplied reference art for the sibling video animation pipeline. `scripts/comfyui_forge_master_still.py` writes the master asset and geometry required by batch video processing. Read [master preparation](references/master-still.md); inspect the actual silhouette, alpha and placement. New still-image generation is not configured.

Character animation, registration, colour finishing, selection, retiming and standard PNG/sheet/GIF/MP4 delivery belong to the sibling [local video animation skill](../comfyui-forge-video2dsprite/SKILL.md). Standalone icon/sheet processing and unrelated exports are outside this fork.

## Local installation

This unofficial fork uses ONLY local ComfyUI for generation. No cloud providers, API keys, CLI generation or automatic code-art fallback. Still-image generation is not configured; use supplied images.

Keep the three animation-core skills together: generate2dmedia, generate2dsprite and video2dsprite. This fork contains only the three animation-core skills. Use only this project's scripts or their installed copies, never another project's skill programs. Keep the declared Python/FFmpeg dependencies and configured local ComfyUI connection. Find the permanent repository and configured JSON in `<skills-root>/.comfyui-sprite-forge.install.json` (`project`, `comfyuiConfig`). Use that repository's `.venv/Scripts/python.exe` on Windows or `.venv/bin/python` elsewhere, or another Python with the documented dependencies. Do not copy the author's paths or alter original Sprite Forge settings.

The adapter finds configuration from explicit COMFYUI_FORGE_CONFIG, then the installed manifest, then repository-local local-comfyui/config.local.json. No global environment changes are required. Read the configured API JSON before adapting a workflow; the user's ComfyUI must already run it.
