---
name: comfyui-forge-codeart2d
description: Use deterministic local code-art utilities only when the user explicitly requests code-drawn art. Never an automatic fallback for unavailable ComfyUI generation.
---

# Explicit offline code art

This skill is only for an explicit request for deterministic code-drawn art. scripts/ and references/ retain the local drawing and export utilities. Read the relevant tool's --help before use and inspect results.

Do not invoke this skill because a local ComfyUI job failed or a still-image workflow is missing. No cloud provider or external generation delegate is available in this fork.

## Local installation

This unofficial fork uses ONLY local ComfyUI for generation. No cloud providers, API keys, CLI generation or automatic code-art fallback. Still-image generation is not configured; use supplied images.

Keep the three animation-core skills together: generate2dmedia, generate2dsprite and video2dsprite. Map/code-art tools are optional installations, never automatic fallbacks. Find the permanent repository and configured JSON in `<skills-root>/.comfyui-sprite-forge.install.json` (`project`, `comfyuiConfig`). Use that repository's `.venv/Scripts/python.exe` on Windows or `.venv/bin/python` elsewhere, or another Python with the documented dependencies. Do not copy the author's paths or alter original Sprite Forge settings.

The adapter finds configuration from explicit COMFYUI_FORGE_CONFIG, then the installed manifest, then repository-local local-comfyui/config.local.json. No global environment changes are required. Read the configured API JSON before adapting a workflow; the user's ComfyUI must already run it.
