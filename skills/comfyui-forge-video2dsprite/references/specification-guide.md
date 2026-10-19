# Specification confirmation and clean delivery

Read before preparing the video input. This is a conversational workflow backed by deterministic offline tools, not a fixed interview for every action. Use `scripts/animation_spec.py --help` and `scripts/deliver_animation.py --help`.

## Language and stage labels

Use the user's conversation language for every question, choice, explanation, warning and delivery caption. Tool JSON keys and CLI parameters stay unchanged; do not display raw tool JSON as the user interface. A different requested language takes priority.

Always label dimensions/fps/time as either **final game assets** or **AI source video**. Final duration is a baseline animation playback time; the engine may change its speed. Source duration creates selection opportunities, not the final runtime. Infer loop/one-shot/hold and world-translation ownership from the action/context; clarify only when ambiguous. Never assume every action loops, needs anticipation or recovers to idle.

## First use

Run `animation_spec.py show --settings PROJECT/.comfyui-sprite-forge.preferences.local.json`. A missing file proposes first-use settings without writing anything. Do not store preferences in the skill installation, the author's files or a global home setting.

1. Respect specifications already given in this request. Otherwise propose final cells **128x128, 1 second, 8 fps = 8 frames**, and source **640x640, 3 requested seconds, 24 fps**. Explain actual source count/time (default 17k+5: 73 frames, about 3.04s). Use the real configured workflow's fps/cadence if different and explain the difference. Ask **adopt these specifications? [Yes / No]**, localized. Do not repeat questions whose answers are already explicit.
2. Yes adopts the displayed numbers. Resolve any ambiguous action playback mode before saving. No asks for the desired final cell size, baseline seconds and fps, accepting a short response such as `64x64, 2s, 12fps`. If the user changes just one item, retain the other confirmed items. Do not restart every question unnecessarily.
3. Run `animation_spec.py plan` to calculate performance/balanced/quality plus a custom option. Present concrete width/height, actual MP, requested seconds, source fps, legal source frame count and actual duration. Preselect balanced. Explain why it suits the action, not just its label. Users may modify any option.

Example calculation: final 64x64, 2s, 12fps = 24 frames; performance 256x256, balanced 320x320, quality 384x384. Each requests 6s at 24fps; default cadence gives 158 frames, about 6.58s. Final assets still show one selected action/period over 2s.

## Calculation and action review

The tool starts from final width/height times 4/5/6, fits a requested aspect ratio (neutral 1:1), optionally expands the estimated motion envelope and rounds width/height upward to the dimension alignment. These are candidate **canvas** factors inclusive of ordinary breathing room, not minimum guaranteed character anatomy factors. Codex still reviews subject occupancy, full motion envelope, appendages, shared cross-action scale and actual workflow limits. Aim for readable final silhouettes and stable poses, not source microtexture. Avoid arbitrary high-resolution generation for small sprites.

The adapter requires multiples of 32. Optional config `planning.dimension_multiple` adds stricter alignment via a common multiple; `planning.minimum_source_size: [W,H]` records a verified workflow lower bound. Without a verified lower bound the tool says so; confirm compatibility rather than asserting a small candidate can run. Duplicate aligned/minimum-clamped tiers are identified; collapse or explain identical choices. For illegal custom dimensions offer the suggested padded canvas, preserving character aspect and registration. There is no dependency on a resolution-selector node.

`--envelope 1.25,1` expands width for an action; `--ratio 3:4` changes framing. These are estimates, not per-frame resizing. Do not silently override an explicitly selected canvas or change an established character scale. If a new action cannot fit, explain the particular adjustment and confirm it before generating.

Default requested source duration is `max(3, final_baseline_seconds * 3)`. Review complexity and separation/reset time; propose longer source time (often 5-6s) if needed, using `--source-duration`. Target 2-3 complete candidates, preferably 3, with **completeness > clear usable poses > candidate count**. Looping actions repeat full cycles; single actions repeat independent demonstrations with a clear separation/reset, not an unintended combo. Use slower demonstrations when needed to retain enough poses for selection. No need to force source action speed to final game speed. After generation count actual complete candidates; if only one is usable, report it and let the user choose reuse or a revised take rather than claiming success at the target count.

Explain in the user's language: source video is longer to obtain multiple complete candidates and choose one; it does not mean final playback lasts as long or repeats all demonstrations. Final export contains one selected action/period. Resource pressure should first prompt a lower resolution tier, preserving useful action time; do not promise feasibility from VRAM capacity alone.

For source time, the planner and adapter share `frame_rules.py`. Defaults: 24fps, minimum5, multiple17, offset5. Compute `n=max(minimum, round(requested_seconds*fps))`, then `n+=(offset-n)%multiple`; `round` uses Python nearest/ties-to-even. Actual seconds are n/fps. Workflow config may override all frame rules. A supplied config that omits cadence fields follows the adapter's generic1k+0 behavior; the project template explicitly selects17k+5. Do not also run a fixed-24fps seconds Expression on an already aligned frame-count input. Custom source fps must match a private workflow config and its output fps/Expression; the planner refuses a conflicting configured fps. Never modify the user's original workflow or global configuration silently.

Final frame count is final_seconds * final_fps. Noninteger results produce explicit alternatives; do not silently round. The planner cannot save until timing and playback mode are resolved. Events such as hit/release/contact map to selected output frames, not a forced default time fraction. Preserve important action poses before selecting transitions. Report any repeated frames; do not invent unique poses to meet the count.

## Confirmation and preferences

Example commands from the repository root (use the selected Python; substitute the actual paths and confirmed values):

```text
python skills/comfyui-forge-video2dsprite/scripts/animation_spec.py plan --cell 64x64 --duration 2 --fps 12 --mode oneshot --config local-comfyui/config.local.json --out work/action/spec-proposal.json
python skills/comfyui-forge-video2dsprite/scripts/animation_spec.py save --plan work/action/spec-proposal.json --tier balanced --settings .comfyui-sprite-forge.preferences.local.json --confirmed
python skills/comfyui-forge-video2dsprite/scripts/animation_spec.py show --settings .comfyui-sprite-forge.preferences.local.json
```

Only use `--confirmed` after the user has accepted the displayed specification. The file stores numbers, mode, workflow fingerprint and selected tier, not permission for future jobs. Later requests show saved final/source settings and ask **reuse these settings? [Yes / No]**. Yes reuses them subject to the new action's envelope and workflow compatibility; No starts from final requirements again. An explicit request to reuse counts as the answer. A changed/missing workflow or source-fps mismatch requires reconciliation and confirmation. Use a new `plan` to change settings and `save --replace` only after acceptance; never replace a saved profile merely because the model thinks another tier is better. For a new workflow, pass its config when replanning.

The default settings filename is Git-ignored; keep any custom settings filename outside tracked files or add it to the project ignore rules. Keep proposals, receipts and settings out of public commits and standard delivery archives. Prepared reference dimensions, route duration and workflow fps must come from the confirmed spec; the route's `--resolution` is not a resize operation. The planner never submits GPU work, edits a graph or verifies model quality. Its numerical recommendations require actual input and final-size visual review.

## Standard delivery

After preparing, keying, registering and selecting the final sequence, pass **exactly** the finished RGBA PNGs in playback order to `deliver_animation.py`. All frames must already match the confirmed final dimensions and count. Ordered repeated poses are allowed; do not pass the entire raw directory or a selection-policy JSON as a substitute for materializing the final sequence. Preserve the working originals and verified source MP4.

```text
python skills/comfyui-forge-video2dsprite/scripts/deliver_animation.py --frames work/action/selected-finished --source work/action/generation/generated.mp4 --spec .comfyui-sprite-forge.preferences.local.json --out-dir outputs/action --report work/action/delivery-report.json
```

Standard ZIP contains only:

```text
frames/frame_0000.png ...  selected finished transparent frames, zero-based padded names
animation-sheet.png      fixed-cell transparent atlas, no trimming or rotation
preview.gif              baseline-time preview
source.mp4               original source video, not a transparent video
```

The sheet defaults to up to8 columns, read left-to-right then top-to-bottom; `--columns` can change layout. Caption final cell dimensions, total count, columns/rows, order, baseline duration/fps and playback mode in the conversation. Trailing empty cells are not animation frames. List confirmed event frame indices in the conversation if relevant; detailed event JSON stays at work. Engine manifests, WebM/APNG or other advanced formats are optional only when requested, not standard ZIP contents.

GIF is a repeating preview even for a one-shot; explain this for non-looping game actions. Whole-centisecond delays approximate baseline timing; report any total-duration approximation, and retain exact final timing in the work receipt. Identical frames may merge in GIF encoding, while all selected PNG sequence entries remain. GIF binary transparency is not a substitute for inspecting PNG alpha on light/dark backgrounds.

In the final conversation, in order: (1) clickable ZIP; (2) render GIF preview; (3) render animation frame sheet; (4) render/link source video; (5) link the actual retained work directory. Use absolute paths for local media and clickable files, adapting to the host's display support. No raw JSON dumps or long checklists. Report material limitations briefly.

The last sentence is localized, not hardcoded Chinese. Traditional Chinese wording: "其它中間處理檔，如：JSON、日誌、檢查報告與未選影格…等，都留在[工作目錄]，不放進標準交付 ZIP。" Replace the label with a real clickable directory path. English equivalent: "Intermediate files, such as JSON files, logs, inspection reports, and unselected frames, remain in the [working directory] and are excluded from the standard delivery ZIP."
