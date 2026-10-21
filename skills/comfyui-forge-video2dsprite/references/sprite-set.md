# Generic batch animation workflow

Plan with `comfyui_forge_sprite_set.py plan --master APPROVED_MASTER_JSON --spec CONFIRMED_SPEC_JSON --motions-file DEFINITIONS_JSON --output-dir NEW`.
The specification confirms source canvas/duration and final cell/duration/fps/count before generation. Decimal seconds are supported; frame counts and dimensions are positive integers. A definition has arbitrary `id`, behavioral `type` (`cycle`, `oneshot-return`, `oneshot-hold`) and free `description`. Labels never dispatch motion rules. There is no default action list.

1. `run --plan SET` prepares each supplied master, chooses a safe generation background and submits or resumes its local ComfyUI task. Request 2–3 complete demonstrations. Preparation extracts consistent opaque backgrounds of any colour and compares subject colours before selecting a contrasting background. Extraction failure requires a repaired input; no fabricated subject replacement.
2. Review the source and choose ONE complete demonstration. `select --plan SET --action ID --take N --range START:END` binds the half-open decoded-frame interval to that take's clip hash. One-shots require a reviewed interval. Cycles may use continuity-based automatic selection. Never combine separate demonstrations or include source resets.
3. `run --plan SET` resumes that same take locally. Single-play motion normally uses retiming; `--oneshot-timing source` retains authored source timing. Optional definition `keys` maps arbitrary labels to `{source,at,holdMs}` and `events` contains `{name,source}`. Indices refer to the decoded source, phases to target playback, holds to milliseconds. No event positions are inferred from the action name.
4. `review --plan SET` locates final-size preview, contact sheet and review data. Check subject preservation, complete motion, timing, ending, registration and matte at delivery size. `accept --plan SET --action ID --take N --note TEXT` records the actual visual assessment and review hash.
5. `run --plan SET` verifies that approval and creates the standard ZIP: selected transparent PNG frames, sprite sheet, GIF preview and original MP4. Intermediate reports stay in the work folder. PNGs and the confirmed timing contract are authoritative; GIF has binary transparency and 10 ms timing precision.

Local validation/selection/finishing failures block the existing take. Re-running does not create another GPU job. Pending/unknown submissions keep their original receipt. Only an explicit `retake --plan SET --action ID --fix REASON` requests another take. `report --plan SET` writes progress separately from delivery.

Use geometric options only when required by the actual footprint. No presumed facing, airborne, support or named-action rules are imposed. A terminal hold is not replaced with the initial pose. The confirmed output specification controls dimensions and playback; incompatible overrides fail before generation.

## Reviewed revisions and recovery

`select --plan SET --action ID --take N --range START:END --timing-file TIMING_JSON` can revise one existing single-play take after seeing the actual source. TIMING_JSON contains `keys` and `events`; labels are arbitrary legal identifiers, preserved verbatim. Prior review/finish/motion folders are archived, prior delivery remains intact, and a new review revision gets a separate delivery path. This does not generate a new clip. For cycles, select the reviewed forward range without an authored timing override.

Generation plans become immutable once state exists. A changed plan fails before cached results are reused; restore it and use per-take selection/timing revisions. QC failures remain visible in the review and are bound to its receipt; they are not silently converted to passes. Visual acceptance must address applicable QC findings.

All three motion types share the candidate-preservation contract in [the pipeline](pipeline.md#preserve-candidate-identity-and-validation-context): source mappings, selected endpoints, authored timing/key/event poses and validation inputs survive every local stage. Cycles alone require successor-frame closure evidence. An event pose that cannot fit the playback budget stops processing rather than moving to a later source pose.

Delivery writes a pending work receipt before publishing output. Resume verifies exact inputs, specification and all delivered file hashes, then adopts a completed publication. Missing or changed contents block recovery rather than overwriting the output. Continuous cycle selection never offers reverse playback as a fallback.

Source timing retains authored events on exact source poses and rejects target phase/hold keys rather than ignoring them. Batch cycle selection does not author phase keys/events: use an explicitly authored selection through standalone timing/finalization when those controls are required. Incompatible combinations are rejected before generation.


## Integrity and local recovery

Prepared input/master/prompt, confirmed specification, source MP4, completed local stages and published delivery carry content hashes. A changed file is not accepted merely because its directory exists. Review approval also checks the GIF and contact-sheet hashes. When processing receipts provide source-video provenance, the retained MP4 must match it.

To rebuild local processing while preserving the source video and previous outputs:

```text
comfyui_forge_sprite_set.py rebuild --plan SET/set_plan.json --action ID --take 1 --from-stage keyed
```

Stages are `keyed`, `registered`, `motion`, `finished`, `final-review`. The selected stage and its downstream stages are archived and rebuilt on the next run; no new GPU submission occurs. Legacy cached stages without integrity snapshots require this local rebuild. Changed prepared generation input requires a new plan, not editing a frozen job. Existing selections retain their events and exact tick timeline when passed through retime without timing overrides; explicit duration changes scale event phases. Events outside the selected candidate are refused.
