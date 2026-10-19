---
name: comfyui-forge-video2dsprite
description: Animate supplied characters through local ComfyUI, or process supplied videos into transparent registered sprite animations, loops, GIF previews and engine exports. Use for character animation; still-image generation is not configured.
---

# Local character animation

Use the supplied character image as the identity reference. Before preparing input or generating video, read [specification confirmation and clean delivery](references/specification-guide.md). Run `scripts/animation_spec.py` to calculate proposals and manage project-local confirmed preferences. Present questions and results in the user's language. Clearly separate final game assets from AI source video. First-use proposal: final128x128,1s,8fps; source640x640,3 requested seconds,24fps (default cadence73frames,about3.04s). Ask adopt Yes/No; on No collect final requirements and show calculated performance/balanced/quality/custom choices. Infer or clarify playback mode rather than assuming a loop. Later show saved settings and ask reuse Yes/No. Respect values already supplied and reconcile the actual workflow before using defaults.

## Evaluate the action reference before generation

Apply this assessment to any requested animation, not just named actions or built-in templates. Infer the intended pose, facing, expression, motion phases, framing and gameplay constraints from the user's text and character image. A sketch or pose reference is optional; do not require one. Choose reasonable unspecified details and ask only about ambiguities that materially affect the result.

- If the supplied pose, view and framing can plausibly lead into the intended motion, use it directly. Otherwise, consider an action-specific first frame before submitting video: a large pose/view change, tight clearance or likely clipping can make repeated video attempts ineffective.
- Preserve identity, proportions, costume and colors while designing the action pose and safe framing. Check the full silhouette against any height/space constraint at a consistent character scale; shrinking, stretching or rotating the entire still is not proof of a correct pose.
- Check which image tools are actually available and the user's service preferences. Image 2.5, when available, is an optional example, not a required dependency or a claim that this skill can invoke it. An already authorized external image tool may prepare a separate input asset; if external use is not authorized or conflicts with local-only preferences, ask before using it. Never seek API keys, silently switch services or introduce a provider fallback. With no suitable tool, accept an action still supplied by the user or use their explicitly configured local image workflow; explain the limitation rather than promising generation.
- Show a newly prepared action still for user approval before submitting video. Treat it as an input asset to this skill, retain the original identity reference, and use the approved pose to generate appropriate motion; do not reduce an action that needs substantial movement to an idle hold.
- For distinct motion phases, assess whether separate clips and transition references are needed. A first frame does not guarantee the whole motion. Built-in action labels are preparation templates, not a complete list of supported requests: use a suitable template with a custom prompt when appropriate, and disclose unsupported workflow controls instead of inventing flags.

This optional input-preparation step does not add still-image generation or a cloud route to ComfyUI-Sprite-Forge. Its video adapter continues to use local ComfyUI only.

## Plan motion space and gameplay behavior

Before preparing input or submitting video, read [motion planning and acceptance](references/motion-planning.md). Apply it to any action: budget directional motion margins, preserve identity and a shared character scale, assign translation to the game or animation, plan state transitions and loop behavior, and isolate local motion only when requested. Generation canvas and final game cells are separate; never silently crop, squash or change one action's scale to fit. Inspect the prepared input before submission and the actual animation before acceptance. If retakes keep failing for the same reason, change the pose/reference or framing rather than repeating the same prompt.

## Pipeline

1. Use `scripts/video2dsprite.py doctor` to check ffmpeg/ffprobe. Check generation with the sibling `../comfyui-forge-generate2dmedia/scripts/comfyui_media.py --check`; no GPU submission.
2. `scripts/prepare_i2v_input.py prepare --master IMAGE --action run --canvas 640,640 --duration 3 --output-dir NEW` records one input transform (example values only: substitute the confirmed source canvas/duration). Choose a safe key color. An opaque-looking RGBA background is not already keyed: inspect alpha and prepared input.png; convert a separate source copy to RGB when required so --master-key can key it. Never edit the user's only source.
3. Prepare the prompt for 2-3 complete action candidates (prefer3, completeness first), using source duration from the confirmed spec; separate one-shot demonstrations instead of a combo. Generate through `../comfyui-forge-generate2dmedia/scripts/route_media.py video --route comfyui --reference INPUT --prompt-file PROMPT --duration 3 --out-dir NEW`. Use --last-frame only for a suitable action and a bound tail input. Never retry a pending/unknown submission in a new folder.
4. `scripts/video2dsprite.py process` keys and decodes; inspect matte-report and actual frames. Use `scripts/register_clip.py apply` or documented tracking for a consistent scale and planned anchor. Follow the translation ownership decision: remove unwanted root travel when the game owns it, preserve intended pose motion and bob, and do not universally lock feet. Registration padding can accommodate intact motion, but cannot restore clipped source pixels.
5. `scripts/gait_loop.py select --frames-dir FRAMES --fps 24 --kind gait --state run --output-dir NEW` picks a proposed forward cycle. Inspect it; no ping-pong for running. Exclude start/stop holds. One-shots use retime.py instead.
6. `scripts/finish_frames.py hd --frames REGISTERED --target-height 104 --canvas 128x128 --canvas-anchor 64,116 --output-dir NEW` preserves a shared scale. Do not stretch the source to square or resize each frame to its own alpha bounds.
7. Standard delivery: use `scripts/deliver_animation.py` with exactly the finished selected RGBA PNGs and the confirmed specification. It exports selected PNGs, a transparent fixed-cell sheet, GIF preview and original source MP4, and makes a ZIP containing only those four kinds. Put its optional receipt at a work-directory `--report` path. Render GIF/sheet/source in the conversation, link the ZIP and retained work directory, and caption cell size/count/layout/baseline timing. Inspect the actual animation and light/dark matte edges. `tools/export_preview.py` and engine_export.py remain available for explicitly requested advanced outputs; JSON/APNG/WebM/engine reports are not standard delivery contents.

Each command's --help gives full flags. Legacy advanced references remain for registration, matte, finishing and packaging; local-only policy overrides their generation-provider examples. No automatic retakes merely for an install check.

## Timing and receipts

1second at8fps means8 output frames at125ms each. GIF is limited to10ms timing ticks and binary alpha: use alternating120/130ms for a1s preview and retain125ms in game metadata/APNG. Use a whole step cycle from the longer source, not simply eight evenly spread frames including holds.

pending: resume the same generation folder. unknown: inspect local queue/history. done: checksum-verify and reuse the clip. Report identity changes, deformation, camera drift, seam or matte warnings; a tool success is not art approval.

## Local installation

This unofficial fork uses ONLY local ComfyUI for generation. No cloud providers, API keys, CLI generation or automatic code-art fallback. Built-in still-image generation is not configured; use supplied images or an approved action still prepared separately under the assessment above. Do not follow historical upstream generation instructions in retained references when they conflict with this policy.

Keep all five comfyui-forge-* sibling skills. Find the permanent repository and configured JSON in `<skills-root>/.comfyui-sprite-forge.install.json` (`project`, `comfyuiConfig`). Use that repository's `.venv/Scripts/python.exe` on Windows or `.venv/bin/python` elsewhere, or another Python with the documented dependencies. Do not copy the author's paths or alter original Sprite Forge settings.

The adapter finds configuration from explicit COMFYUI_FORGE_CONFIG, then the installed manifest, then repository-local local-comfyui/config.local.json. No global environment changes are required. Read the configured API JSON before adapting a workflow; the user's ComfyUI must already run it.
