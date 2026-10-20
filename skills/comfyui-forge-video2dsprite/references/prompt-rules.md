# Generic motion and background handling

The request supplies the actual motion. Choose exactly one behavioral contract: cycle (continuous repetition), oneshot-return (single action with complete recovery to its initial pose), or oneshot-hold (single action retaining its terminal pose). Matching poses alone never turn a single action into continuous movement. No action-name dictionary controls generation, dimensions, registration, timing, events or key poses.

## Input preparation

Use comfyui_forge_prepare_i2v_input.py prepare --master IMAGE --motion-type TYPE --description DESCRIPTION --canvas WIDTH,HEIGHT --duration SECONDS --output-dir NEW. Description states the desired motion, facing, translation ownership, support constraints and spatial needs. --root, --scale, --anchor, --action-padding L,T,R,B and --margin are geometric controls independent of the motion label. Preserve a consistent character scale. --prompt-file may supply the actual prompt; metadata records its hash and declared motionType, not a claim that it obeys the contract. Inspect input.png and the actual prompt before generation. --candidates 2|3 proposes complete source demonstrations; planned intervals are not verified video boundaries.

## Flat background extraction

Preserve real alpha. For opaque or near-opaque250-255 input, first attempt extraction: estimate the dominant background from all four edges, check each edge and overall consistency, then build a boundary-connected colour-distance matte. For a suitable chromatic background, also try soft chroma matting to suppress fringe; retain the distance result if chroma matting would damage subject material. The input background may be any colour, including neutral colours; no named-colour assumption is used. Antialiased boundary pixels are decontaminated locally; opaque subject colours remain unchanged.

Inspect extracted master.png on light and dark backgrounds. Background-coloured regions inside the subject can be indistinguishable from holes or details. If extraction or its quality check fails, stop and ask the user to provide a corrected cutout or suitably separated flat-background image. Do not guess masks, retry destructive key settings or use a new generation to hide a failed extraction. A risky original colour alone is not a reason to stop if extraction succeeds.

After successful extraction, compare generation-background candidates with the subject palette and soft-video-matte risk. Choose a high-contrast low-risk flat colour; it need not match the input background. Replacing an unsafe generation backdrop is safe only after a usable subject matte exists. If none of the tested colours passes, stop for a suitable input rather than forcing a conflicting key. Keep original source bytes and extraction/colour-choice reports.

## Source and final motion

All three types may use2-3 complete independent demonstrations in the source. A cycle flows between periods. One-shots complete their full action and recovery or terminal state; resets occur only between source demonstrations, never inside the selected final action. Completeness takes priority over count. Select one whole candidate before retiming.

For either one-shot type, normally use comfyui_forge_retime.py --kind TYPE --auto-oneshot --range START:END with confirmed final duration and fps. Continuous cycles normally use phase selection, with explicit retiming if their requested rhythm needs it. Any key/hold/event must come from reviewed motion needs and source frames. Uniform temporal spacing is not a universal rule. Keep events and authored timing through comfyui_forge_finalize_animation.py and inspect the final materialized animation.
