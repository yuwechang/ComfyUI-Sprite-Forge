# Animation processing and delivery

Generation uses the local ComfyUI adapter in the sibling `comfyui-forge-generate2dmedia` skill. Processing supplied clips is offline. Keep work products outside installed skill folders.

Follow [the confirmed specification](specification-guide.md) and [generic batch workflow](sprite-set.md). Decode and key the complete source, register it, select one complete demonstration, then apply timing according to the declared behavioral type. Continuous motion requires phase and velocity continuity. Single-play motion retains the intended start/end and any authored event or hold timing; matching endpoint poses alone do not make a continuous cycle.

`comfyui_forge_video2dsprite.py process --video INPUT --output-dir NEW` produces source and transparent frames without generating an alternative uniformly sampled delivery. `comfyui_forge_register_clip.py` performs registration; `comfyui_forge_gait_loop.py` selects continuous candidates; `comfyui_forge_retime.py` handles authored or single-play timing. See each script's `--help` for exact controls. The standard finalizer consumes the selected frame indices and confirmed specification, prepares final-size review artifacts, and requires approval bound to their hash before delivery.

Deliver only the standard ZIP containing selected RGBA PNG frames, sprite sheet, GIF preview and original MP4. Review JSON, contact sheets, manifests and diagnostics stay in work. GIF uses binary alpha and 10 ms time units, so preserve the PNGs and confirmed playback specification as authoritative.

Pairwise candidate analysis checks a configurable memory budget (`COMFYUI_FORGE_ANALYSIS_MEMORY_MB`, positive integer MiB); reduce the reviewed candidate range or adjust that budget when necessary. Never silently truncate a source or change final frame counts to fit a hard-coded limit.

## Preserve candidate identity and validation context

For all three motion types, keep the full source through selection and retain the original selection document. Cropping, registration and retiming must preserve the same candidate, its source mapping, declared motion contract, exact timing, key poses and events. An out-of-bounds crop is an error, not permission to truncate the action.

If selecting before registration, pass `selection.json` to `comfyui_forge_register_clip.py apply --selection SELECTION` instead of a bare `--range`. Registration verifies hashes, records the original-to-registered mapping and retains the candidate with its type-specific validation context. `retime --selection SELECTION` on the registered `frames/` directory rebases source indices while preserving durations, ticks, holds, events and validation dependencies. Further retiming retains the same evidence chain; changing the declared motion type or replacing the candidate with a range is rejected. The original selection and validation inputs must remain available through delivery.

Cycles additionally need the two frames immediately after the candidate: one for pose and the next for velocity. These are validation evidence, not playback frames. For an un-timed cycle, `comfyui_forge_gait_loop.py select` validates the preserved registered candidate without searching for a replacement. Authored cycles with timing/events use retime to retain their timeline. `--cycle-selection` remains a cycle-only form of registration. Single-play candidates retain their initial and terminal poses without adding cycle-only successor frames.

Event sources must survive selection exactly; do not move an event to the next available pose. Required event/key poses and endpoints that exceed the final frame budget cause an error. Inherited events keep their pose and offset within a held pose when the timeline is retimed. The finalizer verifies the source mapping, complete candidate and validation dependencies before review and again before publication; its work receipt maps each delivered frame back to the decoded source. Only playback frames enter the standard ZIP.

For an explicitly reviewed range on an untrimmed clip, `select --candidate START:END` validates that exact half-open interval. Missing successor frames, drift limits and failed pose/velocity closure have separate error messages; missing evidence is not an artistic rejection. Keep the existing thresholds and inspect actual motion even when metrics pass.

## Shared timing and resource checks

Selection tick weights and millisecond durations must describe the same clock (half-up cumulative rounding to milliseconds). An event carrying both tick and millisecond timestamps must agree within that rounding precision. Rejected selections and a playback policy incompatible with the final contract are refused. Generic event labels work across retime, standard finalization and the schemas without a whitelist or custom prefix.

Candidate analysis checks the memory budget before loading reduced frames. If even one reduced pixel per frame cannot fit, it stops with a resource explanation.

Standard GIF preview delays are limited by the format to 65535 centiseconds per encoded frame; excessively long delays are refused with an explanation before writing the GIF.
