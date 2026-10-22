---
name: comfyui-forge-generate2dsprite
description: Prepare and approve a supplied character reference for this project's local ComfyUI video-to-sprite workflow. Not a standalone still-art, sheet-processing or engine-export skill.
---

# Video reference preparation

Use this helper only to inspect, key, pad and approve supplied reference art for the sibling video animation pipeline. `scripts/comfyui_forge_master_still.py` writes the master asset and geometry required by batch video processing. Read [master preparation](references/master-still.md); inspect the actual silhouette, alpha and placement. New still-image generation is not configured.

Character animation, registration, colour finishing, selection, retiming and standard PNG/sheet/GIF/MP4 delivery belong to the sibling [local video animation skill](../comfyui-forge-video2dsprite/SKILL.md). Standalone icon/sheet processing and unrelated exports are outside this fork.

## Runtime setup

Find the repository and configuration in `<skills-root>/.comfyui-sprite-forge.install.json` (`project`, `comfyuiConfig`). Use the repository's `.venv/Scripts/python.exe` on Windows or `.venv/bin/python` elsewhere, or a Python with the documented dependencies. Installation steps are in the repository's `INSTALL.md`.

Configuration discovery order: explicit `COMFYUI_FORGE_CONFIG`, installed manifest, then repository-local `local-comfyui/config.local.json`.
