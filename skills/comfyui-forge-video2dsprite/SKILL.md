---
name: comfyui-forge-video2dsprite
description: Animate supplied characters through local ComfyUI, or process supplied videos into transparent registered sprite animations, loops, GIF previews and standard PNG/sheet/GIF/MP4 delivery. Use for character animation; still-image generation is not configured.
---

# Local character animation

Use the supplied character image as the identity reference, or process an existing source video offline. Before preparing input, follow [specification confirmation and delivery](references/specification-guide.md) and calculate this task's values with `scripts/comfyui_forge_animation_spec.py`. That guide defines first-use confirmation, same-chat reuse, source cadence, final-rate assessment and the pre-generation summary.

## Evaluate the action reference before generation

Assess the requested animation from its actual motion requirements. Infer the intended pose, facing, expression, motion phases, framing and gameplay constraints from the user's text and character image. A sketch or pose reference is optional; motion descriptions are free text. Choose reasonable unspecified details and ask only about ambiguities that materially affect the result.

- If the supplied pose, view and framing can plausibly lead into the intended motion, use it directly. Otherwise, consider an action-specific first frame before submitting video: a large pose/view change, tight clearance or likely clipping can make repeated video attempts ineffective.
- Preserve identity, proportions, costume and colors while designing the action pose and safe framing. Check the full silhouette against any height/space constraint at a consistent character scale; shrinking, stretching or rotating the entire still is not proof of a correct pose.
- Check which image tools are actually available and the user's service preferences. An already authorized external image tool may prepare a separate input asset; if external use is not authorized or conflicts with local-only preferences, ask before using it. With no suitable tool, accept an action still supplied by the user or use their explicitly configured local image workflow; explain the limitation rather than promising generation.
- Show a newly prepared action still for user approval before submitting video. Treat it as an input asset to this skill, retain the original identity reference, and use the approved pose to generate appropriate motion; do not reduce an action that needs substantial movement to an unrequested stationary hold.
- For distinct motion phases, assess whether separate clips and transition references are needed. A first frame does not guarantee the whole motion. Describe the actual motion and its spatial constraints. Explain any required controls the workflow does not support.

## Plan motion space and gameplay behavior

Follow [motion planning and acceptance](references/motion-planning.md) for the full motion envelope, placement, shared scale, translation ownership and repeated-deviation checkpoint. Inspect both prepared input and generated motion before acceptance.

## Pipeline

1. Use `scripts/comfyui_forge_video2dsprite.py doctor` to check ffmpeg/ffprobe. Check generation with the sibling `../comfyui-forge-generate2dmedia/scripts/comfyui_forge_media.py --check`; no GPU submission.
2. Choose the behavioral contract from [generic motion and background handling](references/prompt-rules.md). Prepare with `scripts/comfyui_forge_prepare_i2v_input.py prepare --master IMAGE --motion-type TYPE --description DESCRIPTION --canvas WIDTH,HEIGHT --duration SECONDS --output-dir NEW`. TYPE is cycle, oneshot-return or oneshot-hold. Use confirmed dimensions/seconds and plan motion margins explicitly. Preparation preserves genuine alpha or attempts automatic extraction of any consistent opaque flat background by estimating all four edges. Check the extracted master on light/dark backgrounds and keyChoice.preflight; select a contrasting generation backdrop without changing subject colours. Only stop for user repair if extraction fails or its result cannot reliably preserve the subject. Never edit the user's source.
3. Prepare the prompt targeting2-3 complete action candidates (prefer3, completeness first; one acceptable complete candidate is sufficient), using the source resolution and duration calculated for this task; separate one-shot demonstrations instead of a combo. Generate through `../comfyui-forge-generate2dmedia/scripts/comfyui_forge_route_media.py video --route comfyui --reference INPUT --prompt-file PROMPT --duration SOURCE_SECONDS --out-dir NEW`. When input and prompt are prepared together, pass --preparation registration_job.json so their hashes are verified before submission. Use --last-frame only for a suitable action and a bound tail input. Never retry a pending/unknown submission in a new folder.
4. `scripts/comfyui_forge_video2dsprite.py process` keys and decodes; inspect matte-report and actual frames. Use `scripts/comfyui_forge_register_clip.py apply` (automatic canvas padding retries once only for intact source overflow, without changing scale) or documented tracking for a consistent scale and planned anchor. Follow the translation ownership decision: remove unwanted root travel when the game owns it, preserve intended pose motion and bob, and do not universally lock feet. Registration padding can accommodate intact motion, but cannot restore clipped source pixels.
5. Select ONE complete candidate before time warping. A continuous cycle uses `scripts/comfyui_forge_gait_loop.py select --frames-dir FRAMES --fps SOURCE_FPS --kind cycle --policy cycle --output-dir NEW`; inspect phase/velocity continuity, not just matching endpoint poses. Either one-shot type normally uses `comfyui_forge_retime.py --kind TYPE --range START:END --auto-oneshot --duration-ms FINAL_MS --output-fps FINAL_FPS --output-dir NEW`. The range is one reviewed full demonstration, excluding source-only resets. Do not infer events or phase percentages from its name. Define reviewed source-frame keys/holds only when required by the motion. Retain the initial pose and the intended terminal pose, including a complete recovery when the contract requires it.
6. `scripts/comfyui_forge_finish_frames.py hd --frames REGISTERED --target-height 104 --canvas 128x128 --canvas-anchor 64,116 --output-dir NEW` illustrates the finishing syntax; choose target height and canvas anchor from the reviewed motion envelope and planned placement rather than copying these example values. Preserve the shared scale and directional clearance; inspect and resolve any canvas-fit warning before acceptance. Do not stretch the source to square or resize each frame to its own alpha bounds.
7. Standard finalization: run `scripts/comfyui_forge_finalize_animation.py prepare --finished FINISHED --selection SELECTION --spec SPEC --source MP4 --work-dir NEW`, inspect preview.gif and the light/dark review-contact.png, then run its `approve --work-dir WORK --out-dir OUTPUT --review-note TEXT`. This verifies source/finish hashes and available source-video provenance, materializes exact final playback slots, including intentional holds from the retimed selection, recalculates final seam/drift and records visual acceptance. It uses `scripts/comfyui_forge_deliver_animation.py` with exactly the finished selected RGBA PNGs and the confirmed specification. It exports selected PNGs, a transparent fixed-cell sheet, GIF preview and original source MP4, and makes a ZIP containing only those four kinds. Put its optional receipt at a work-directory `--report` path. Render GIF/sheet/source in the conversation, link the ZIP and retained work directory, and caption cell size/count/layout/baseline timing. Inspect the actual animation and light/dark matte edges.

Each command's --help gives full flags. References cover registration, matte, finishing and standard delivery. No automatic retakes merely for an install check.

Follow [candidate preservation](references/pipeline.md#preserve-candidate-identity-and-validation-context) when passing selections through registration, retiming and finalization.

## Timing and delivery

Use the [specification guide](references/specification-guide.md#final-rate-assessment-and-acceptance) for final-rate notice/approval, exact timing, sheet layout and GIF limitations. Standard finalization is described in pipeline step 7 above.

Pending jobs resume in the same generation folder; unknown submissions require queue/history inspection; completed artifacts are checksum-verified. Report identity, deformation, camera, seam and matte findings from visual review.

## Runtime setup

Find the repository and configuration in `<skills-root>/.comfyui-sprite-forge.install.json` (`project`, `comfyuiConfig`). Use the repository's `.venv/Scripts/python.exe` on Windows or `.venv/bin/python` elsewhere, or a Python with the documented dependencies. Installation steps are in the repository's `INSTALL.md`.

Configuration discovery order: explicit `COMFYUI_FORGE_CONFIG`, installed manifest, then repository-local `local-comfyui/config.local.json`.

## Motion contracts

Choose `cycle`, `oneshot-return` or `oneshot-hold` from the user's intended behavior, as defined in [prompt rules](references/prompt-rules.md). Select one complete reviewed demonstration before timing it; candidate preservation follows [the pipeline](references/pipeline.md#preserve-candidate-identity-and-validation-context).

## Review revisions

See `references/sprite-set.md` for per-take `select --timing-file` revisions. Keep generation plans immutable, preserve prior reviews/deliveries, and reuse the same source clip. Arbitrary legal event labels pass through unchanged; no whitelist or `custom:` prefix is required. Inspect recorded QC failures together with final visuals before accepting. Review GIF/contact sheets and finished frames are hash-checked at delivery. For changed or legacy local stage caches, use `rebuild --from-stage` on the same take as documented in `references/sprite-set.md`; it preserves the source video and never submits generation. A key phase that cannot fit the confirmed playback grid stops with an explanation rather than moving silently.

When the executable workflow provides a seed socket, new generation submissions receive a random integer seed recorded in the job and submitted graph. Workflows without a seed socket skip seed assignment and submit normally. Resume and completed-artifact reuse retain that frozen seed; never resubmit to change the seed of an existing job.
