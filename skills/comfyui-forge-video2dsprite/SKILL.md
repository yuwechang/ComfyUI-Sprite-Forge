---
name: comfyui-forge-video2dsprite
description: Animate supplied characters through local ComfyUI, or process supplied videos into transparent registered sprite animations, loops, GIF previews and engine exports. Use for character animation; still-image generation is not configured.
---

# Local character animation

Use the supplied character image as the approved identity reference. Ask for missing action, direction or game timing only when it materially changes the result. Generation defaults are a 3-second request, 24 fps and an input canvas with width and height divisible by32 (tested example1280x736); the configured H3 cadence yields73 frames, about3.04s. Final game size, frame count and playback duration are separate. Read [local usage](references/local-usage.md).

## Pipeline

1. Use `scripts/video2dsprite.py doctor` to check ffmpeg/ffprobe. Check generation with the sibling `../comfyui-forge-generate2dmedia/scripts/comfyui_media.py --check`; no GPU submission.
2. `scripts/prepare_i2v_input.py prepare --master IMAGE --action run --canvas 1280,736 --duration 3 --output-dir NEW` records one input transform. Choose a safe key color. An opaque-looking RGBA background is not already keyed: inspect alpha and prepared input.png; convert a separate source copy to RGB when required so --master-key can key it. Never edit the user's only source.
3. Generate through `../comfyui-forge-generate2dmedia/scripts/route_media.py video --route comfyui --reference INPUT --prompt-file PROMPT --duration 3 --out-dir NEW`. Use --last-frame only for a suitable action and a bound tail input. Never retry a pending/unknown submission in a new folder.
4. `scripts/video2dsprite.py process` keys and decodes; inspect matte-report and actual frames. Use `scripts/register_clip.py apply` for one consistent transform and optional horizontal lock. Preserve flight bob; grow transparent registration padding only when motion was not clipped in the source.
5. `scripts/gait_loop.py select --frames-dir FRAMES --fps 24 --kind gait --state run --output-dir NEW` picks a proposed forward cycle. Inspect it; no ping-pong for running. Exclude start/stop holds. One-shots use retime.py instead.
6. `scripts/finish_frames.py hd --frames REGISTERED --target-height 104 --canvas 128x128 --canvas-anchor 64,116 --output-dir NEW` preserves a shared scale. Do not stretch the source to square or resize each frame to its own alpha bounds.
7. Repository `tools/export_preview.py --frames FINISHED --selection LOOP/selection.json --count 8 --duration 1 --out-dir NEW` exports PNG/APNG/GIF and timing metadata. Omit selection if already passing exactly the desired finished frames. Use `scripts/engine_export.py package` and verify for engine transports; validate_animation.py checks the animation package. Inspect the actual animation and light/dark matte edges before reporting quality.

Each command's --help gives full flags. Legacy advanced references remain for registration, matte, finishing and packaging; local-only policy overrides their generation-provider examples. No automatic retakes merely for an install check.

## Timing and receipts

1second at8fps means8 output frames at125ms each. GIF is limited to10ms timing ticks and binary alpha: use alternating120/130ms for a1s preview and retain125ms in game metadata/APNG. Use a whole step cycle from the longer source, not simply eight evenly spread frames including holds.

pending: resume the same generation folder. unknown: inspect local queue/history. done: checksum-verify and reuse the clip. Report identity changes, deformation, camera drift, seam or matte warnings; a tool success is not art approval.

## Local installation

This unofficial fork uses ONLY local ComfyUI for generation. No cloud providers, API keys, CLI generation or automatic code-art fallback. Still-image generation is not configured; use supplied images. Do not follow historical upstream generation instructions in retained references when they conflict with this policy.

Keep all five comfyui-forge-* sibling skills. Find the permanent repository and configured JSON in `<skills-root>/.comfyui-sprite-forge.install.json` (`project`, `comfyuiConfig`). Use that repository's `.venv/Scripts/python.exe` on Windows or `.venv/bin/python` elsewhere, or another Python with the documented dependencies. Do not copy the author's paths or alter original Sprite Forge settings.

The adapter finds configuration from explicit COMFYUI_FORGE_CONFIG, then the installed manifest, then repository-local local-comfyui/config.local.json. No global environment changes are required. Read the configured API JSON before adapting a workflow; the user's ComfyUI must already run it.
