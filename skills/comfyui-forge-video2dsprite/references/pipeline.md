# Animation processing and delivery

Generation uses the local ComfyUI adapter in the sibling `comfyui-forge-generate2dmedia` skill. Processing supplied clips is offline. Keep work products outside installed skill folders.

Follow [the confirmed specification](specification-guide.md) and [generic batch workflow](sprite-set.md). Decode and key the complete source, register it, select one complete demonstration, then apply timing according to the declared behavioral type. Continuous motion requires phase and velocity continuity. Single-play motion retains the intended start/end and any authored event or hold timing; matching endpoint poses alone do not make a continuous cycle.

`comfyui_forge_video2dsprite.py process --video INPUT --output-dir NEW --skip-sampling` produces source and transparent frames without generating an alternative uniformly sampled delivery. `comfyui_forge_register_clip.py` performs registration; `comfyui_forge_gait_loop.py` selects continuous candidates; `comfyui_forge_retime.py` handles authored or single-play timing. See each script's `--help` for exact controls. The standard finalizer consumes the selected frame indices and confirmed specification, prepares final-size review artifacts, and requires approval bound to their hash before delivery.

Deliver only the standard ZIP containing selected RGBA PNG frames, sprite sheet, GIF preview and original MP4. Review JSON, contact sheets, manifests and diagnostics stay in work. GIF uses binary alpha and 10 ms time units, so preserve the PNGs and confirmed playback specification as authoritative.

Standard delivery is selected transparent PNG frames, sprite sheet, GIF preview and source MP4. This fork does not supply a separate engine transport or runtime.

Source processing has no fixed 600-frame ceiling. Pairwise candidate analysis checks a configurable memory budget (`COMFYUI_FORGE_ANALYSIS_MEMORY_MB`, positive integer MiB); reduce the reviewed candidate range or adjust that budget when necessary. Never silently truncate a source or change final frame counts to fit a hard-coded limit.


## Shared timing and resource checks

Selection tick weights and millisecond durations must describe the same clock (half-up cumulative rounding to milliseconds). An event carrying both tick and millisecond timestamps must agree within that rounding precision. Rejected selections and a playback policy incompatible with the final contract are refused. Generic event labels work across retime, standard finalization and the schemas without a whitelist or custom prefix.

The auxiliary HTML reviewer uses the same configurable analysis memory budget before loading its feature arrays. If even one reduced pixel per frame cannot fit the budget, analysis stops with a resource explanation; reducing dimensions cannot solve that condition. There is no fixed source-frame ceiling.

Advanced video exports also use forward `cycle` or `oneshot` playback; reverse-cycle synthesis is removed. An explicit `--cycles` value counts complete continuous periods and must be an integer. Standard GIF preview delays are limited by the format to 65535 centiseconds per encoded frame; excessively long delays are refused with an explanation before writing the GIF.
