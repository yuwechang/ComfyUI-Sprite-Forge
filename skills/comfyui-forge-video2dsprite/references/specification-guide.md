# Specification confirmation and clean delivery

Read before preparing the video input. This is a conversational workflow backed by deterministic offline tools, not a fixed interview for every action. Use `scripts/comfyui_forge_animation_spec.py --help` and `scripts/comfyui_forge_deliver_animation.py --help`.

## Language and stage labels

Use the user's conversation language for every question, choice, explanation, warning and delivery caption. Tool JSON keys and CLI parameters stay unchanged; do not display raw tool JSON as the user interface. A different requested language takes priority.

Always label dimensions/fps/time as either **final game assets** or **AI source video**. Final duration is a baseline animation playback time; the engine may change its speed. Source duration creates selection opportunities, not the final runtime. Infer loop/one-shot/hold and world-translation ownership from the action/context; clarify only when ambiguous. Never assume every action loops, needs anticipation or recovers to its initial pose.

## First use and same-chat reuse

Run `comfyui_forge_animation_spec.py show --settings PROJECT/.comfyui-sprite-forge.preferences.local.json`. A missing file proposes settings without writing anything. Do not store preferences globally or in the skill installation.

1. Respect details the user already supplied. On first use propose final128x128 and1second, explaining that8fps is the initial output default and final selection may adapt within4-16fps. Above16 needs a separate explanation and explicit approval, up to24. Ask adopt Yes/No in the user's language. If No, ask only final cell size and playback seconds; do not require the user to fill in fps. Preserve fields they have already accepted. Infer the playback contract from intent and clarify only consequential ambiguity.
2. Ask only source resolution, using numbered options: **1. Performance512x512; 2. Balanced768x768(default/recommended); 3. Quality1024x1024**. Accept1/2/3. These fixed source canvases do not grow with final sprite dimensions. Do not ask source seconds, source fps or source frame count. Choose source duration as described below and calculate cadence with the planner. Explicit user requests for custom settings still need compatibility review within the stated bounds.
3. Once settings are resolved, show the pre-generation summary below, then generate within the existing authorization. In later tasks within the same conversation, accepted settings may be reused by default without a repeated confirmation, but ALWAYS display the current summary before submission. Reassess motion clearance and source time for the new motion. Do not mistake same-chat reuse for permission to generate without a user task.

## Mandatory pre-generation summary

Use two short sections with the actual values calculated for THIS task. The following is a presentation template, not hardcoded dimensions, seconds or fps. Substitute chosen sizes, source tier and exact requested seconds; disclose aligned frame count and actual source duration as well. Describe8fps as an initial FINAL output default, not the24fps generation cadence. Preserve existing fixed-camera/effects/playback constraints when relevant.

**Final output: {finalWidth}×{finalHeight} | Default8fps | Playback{finalSeconds}s**

- Start with centred placement, then adjust position and margins for the complete motion envelope so the body and all attached parts remain fully in frame; preserve the planned composition in delivery.
- Assess sampling at4-16fps according to the actual motion and rhythm. Above16fps, explain the reason and obtain approval first; the maximum is24fps.
- Include transparent PNGs, a sprite sheet and a GIF preview. If the user explicitly specifies fps, display that actual setting instead of labelling it the8fps default.

**AI source video: {sourceWidth}×{sourceHeight} ({tier}) |24fps | Requested{sourceSeconds}s**

- Choose source duration at2-3 times the final playback duration; neither requested nor actual duration may exceed15s. Aim for2-3 complete demonstrations and select one for delivery; one complete acceptable demonstration is sufficient.
- Actual source: {sourceFrameCount}frames, approximately{actualSourceSeconds}s. Source duration is separate from final game playback duration.

Present every user-facing message, including this pre-generation specification summary, in the user's language unless they explicitly request another language. This English template defines the information to convey, not the output language; translate its headings, explanations and source-tier labels while preserving the actual numbers and technical units. Do not print placeholders, raw JSON, unresolved duration ranges or unchosen tiers to the user. If a later revised generation uses changed settings, show the revised values before submitting it. At delivery report the chosen final fps and total frame count, not the initial8fps baseline.

## Final-rate assessment and acceptance

Use8fps as a starting default, not a required target. Choose the lowest rate that clearly communicates the actual motion and rhythm. The normal assessment choices are4,6,8,10,12,14,16fps; these are choices, not a mandatory sequence of renders. Final fps must be at least4 and at most24. Above16 is exceptional: identify the useful source changes that16fps omits and explain why they matter and obtain explicit user approval BEFORE producing a sprite sheet above16fps. Delegated normal-rate assessment never waives this approval. Source generation stays at24fps; do not increase it to match a final-rate choice.

Before generation, assess the necessary poses, directional changes, transitions and intended holds, rather than assigning a rate from an action-name table. After source review, distinguish incorrect/missing motion, deformation or clipping from a sampling problem. Fix or regenerate a defective source; increasing final fps cannot invent a missing transition. For generation retries follow the repeated-deviation checkpoint in [motion planning](motion-planning.md): the same mismatch in two consecutive reviewed takes requires a user choice before the third submission, even if normal rate/framing adjustments were delegated. Where the source is sound but final sampling loses important changes, revise selection/timing and raise fps as needed. Where near-identical adjacent frames add no useful change, test a lower rate without discarding intentional hold time. A repeated pose may carry authored rhythm rather than waste a frame.

Review the actual final-size animation at its intended playback speed. Contact sheets help inspect poses and bounds but do not replace playback review. When comparing rates, reuse one complete candidate at the same duration, cell size, scale and placement, keeping the same required poses and authored timing as closely as each sampling grid permits. Check whether extra frames improve useful transitions rather than merely extending idle poses. Preserve playback seconds, phase order, required poses and hold durations; do not silently change duration, drop a phase or manufacture distinct poses to meet a count. Final frame count equals seconds times fps; a minimum4fps does not mean every short clip must contain four frames.

Acceptance of the dynamic default authorizes autonomous final-rate assessment within4-16fps. Before applying an initial assessed rate or a revised rate in selection/retiming, tell the user the fps, total frame count, unchanged playback duration and reason; this is notice only, so proceed without waiting for agreement. Above16fps is an approval request, not notice, and must wait for agreement before producing that higher-rate sprite sheet. Choose and revise fps within that range, retain the accepted non-rate settings, save a separate per-action confirmed specification and record the reason and final result in the work review. Do not ask again merely for each authorized rate adjustment or replace the project baseline with an action-specific choice. Otherwise propose and confirm a rate change before delivery. Do not extend this delegation above16fps or change accepted final cell size, playback length or source resolution. Source seconds are recalculated automatically under the agreed2-3x/cap policy and disclosed before generation.

## Calculation and action review

Source choices are fixed: performance512x512, balanced768x768, quality1024x1024, numbered1/2/3. Minimum source dimensions512x512 and maximum1024x1024; balanced is the default. Do not multiply final sprite dimensions by4/5/6 or automatically enlarge the canvas to meet an estimated envelope. Plan placement and directional margins for all attached parts at a consistent character scale, then review actual final-size readability. If the selected canvas cannot fit the current execution, first consider reframing or changing unspecified motion details through prompt/seed retries as described in motion-planning.md. If the constraints still cannot be met, reconcile them rather than silently changing resolution or shrinking one motion.

The adapter requires multiples of32; workflow planning may add stricter alignment or verified minimum dimensions. Check the selected tier against those constraints rather than silently changing its dimensions. `--ratio` and `--envelope` remain planning context, not permission to enlarge the fixed tiers. Custom source dimensions are only for explicit requests and must remain within512-1024 per dimension, aligned and compatible with the final cell size.

Automatically choose requested source seconds from final playback seconds times a factor in2-3 (default3, `--source-factor`), with a15second cap. Use motion complexity, complete candidate time and reset needs to choose the factor; never ask users to supply source seconds, fps or frame count in the normal setup. The planner retains `--source-duration` for internal exact choices, bounded15s. Do not make requested source duration depend on chosen output fps or total final frames. If the cap reduces comparison opportunities, report the actual candidate count; completeness takes priority over forcing2-3 demonstrations.

Cadence alignment must also respect15s. The maximum legal17k+5 count at24fps is345frames (14.375s); the next count362 would exceed15s. The planner, submitter and source contract therefore cap aligned counts at345 instead of padding past the duration ceiling. Always display both requested and actual time. For very short requests cadence may exceed the nominal2-3x ratio, but never the15s hard cap. Count actual complete candidates after generation; do not claim the requested repetition count was achieved without review.

Explain in the user's language: source video is longer to obtain multiple complete candidates and choose one; it does not mean final playback lasts as long or repeats all demonstrations. Final export contains one selected action/period. Resource pressure should first prompt a lower resolution tier, preserving useful action time; do not promise feasibility from VRAM capacity alone.

For source time, the planner and adapter share `comfyui_forge_frame_rules.py`. Source video always uses24fps and integer frames computed by `min(345, max(5, round(a * 24)) + (5 - (max(5, round(a * 24)) % 17)) % 17)`, where a is positive requested seconds at most15 and may be fractional. Actual source seconds are frames/24. Conflicting settings are rejected. Final game playback fps and frame count remain separate from source timing. The length binding receives already aligned frames; do not multiply it by24 again.

Final frame count is final_seconds * final_fps. Noninteger results produce explicit alternatives; do not silently round. The planner cannot save until timing and playback mode are resolved. Events such as hit/release/contact map to selected output frames, not a forced default time fraction. Preserve important action poses before selecting transitions. Report any repeated frames; do not invent unique poses to meet the count.

## Confirmation and preferences

Example commands from the repository root (use the selected Python; substitute the actual paths and confirmed values):

```text
python skills/comfyui-forge-video2dsprite/scripts/comfyui_forge_animation_spec.py plan --cell 64x64 --duration 2 --fps 12 --mode oneshot-return --config local-comfyui/config.local.json --out work/action/spec-proposal.json
python skills/comfyui-forge-video2dsprite/scripts/comfyui_forge_animation_spec.py save --plan work/action/spec-proposal.json --tier balanced --settings .comfyui-sprite-forge.preferences.local.json --confirmed
python skills/comfyui-forge-video2dsprite/scripts/comfyui_forge_animation_spec.py show --settings .comfyui-sprite-forge.preferences.local.json
```

Only use `--confirmed` after the user has accepted the displayed specification, or for a per-action rate choice covered by explicit delegated assessment under the policy above. The file stores numbers, mode, workflow fingerprint and selected tier, not permission for future jobs. Later tasks in the same conversation may reuse accepted settings by default; always show the current summary without a redundant reuse question. A different conversation with saved settings still establishes whether those preferences apply. Reassess motion clearance and automatic source duration for each task. Saved output fps is a starting point under the accepted4-16fps policy, not a fixed per-action rate; above16 always needs separate approval. A changed/missing workflow or source-fps mismatch requires reconciliation and confirmation. Use a new per-action `plan` for automatic source-time/rate decisions and reserve `save --replace` for an accepted project-baseline change; never replace a saved profile merely because the model thinks another tier is better. For a new workflow, pass its config when replanning.

The default settings filename is Git-ignored; keep any custom settings filename outside tracked files or add it to the project ignore rules. Keep proposals, receipts and settings out of public commits and standard delivery archives. Prepared reference dimensions, route duration and workflow fps must come from the confirmed spec; the prepared image determines the source dimensions. The planner never submits GPU work, edits a graph or verifies model quality. Its numerical recommendations require actual input and final-size visual review.

## Standard delivery

After preparing, keying, registering and selecting the final sequence, pass **exactly** the finished RGBA PNGs in playback order to `comfyui_forge_deliver_animation.py`. All frames must already match the confirmed final dimensions and count. Ordered repeated poses are allowed; do not pass the entire raw directory or a selection-policy JSON as a substitute for materializing the final sequence. Preserve the working originals and verified source MP4.

```text
python skills/comfyui-forge-video2dsprite/scripts/comfyui_forge_deliver_animation.py --frames work/action/selected-finished --source work/action/generation/generated.mp4 --spec .comfyui-sprite-forge.preferences.local.json --out-dir outputs/action --report work/action/delivery-report.json
```

Standard ZIP contains only:

```text
frames/frame_0000.png ...  selected finished transparent frames, zero-based padded names
animation-sheet.png      fixed-cell transparent atlas, no trimming or rotation
preview.gif              baseline-time preview
source.mp4               original source video, not a transparent video
```

The sheet defaults to one row below8 total frames (including4 and6), and exactly two rows from8 frames upward, with columns=ceil(totalFrameCount/2). This depends on total delivered frames, not fps or seconds. All cells have the same dimensions; preserve left-to-right then top-to-bottom playback order. An odd total leaves one transparent unused cell at the end. `--columns` remains available for an explicitly requested layout override, not for silently replacing this default. Caption final cell dimensions, total count, columns/rows, order, baseline duration/fps and playback mode in the conversation. Trailing empty cells are not animation frames. List confirmed event frame indices in the conversation if relevant; detailed event JSON stays at work.

GIF is a repeating preview even for a one-shot; explain this for non-looping game actions. Whole-centisecond delays approximate baseline timing; report any total-duration approximation, and retain exact final timing in the work receipt. Identical frames may merge in GIF encoding, while all selected PNG sequence entries remain. GIF binary transparency is not a substitute for inspecting PNG alpha on light/dark backgrounds.

In the final conversation, in order: (1) clickable ZIP; (2) render GIF preview; (3) render animation frame sheet; (4) render/link source video; (5) link the actual retained work directory. Use absolute paths for local media and clickable files, adapting to the host's display support. No raw JSON dumps or long checklists. Report material limitations briefly.

## Source candidates and final playback

Aim for 2-3 complete demonstrations of the same action; one complete acceptable candidate is sufficient. Report the reviewed count and select one whole candidate without source resets. Do not regenerate solely to increase the count. If no usable complete candidate exists, revise the prompt/seed or consider more source time within the agreed limits. See [prompt rules](prompt-rules.md) for motion contracts, input preparation and background extraction.

Use comfyui_forge_finalize_animation.py prepare/approve for final-size sampling, final seam/drift metrics and a hash-bound visual-review note before standard delivery. For action-specific rhythm, pass comfyui_forge_retime.py selection.json: finalization inherits durations, ticks and event poses instead of resampling source frames uniformly. Use --required-frame only for additional reviewed poses; do not infer timing from a motion label. Fixed-rate slots may repeat intentional holds. Inspect final event timing errors and dropped transitions; insufficient slots for required poses are rejected. Non-looping outputs preserve the selected start and terminal frames. Review aids and receipts remain in the work directory, outside the ZIP.
