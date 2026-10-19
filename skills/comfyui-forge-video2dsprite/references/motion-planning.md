# Motion planning and acceptance

Use for any animation request. Action examples and built-in template names are not an exhaustive support list. These are decision criteria, not fixed margins, compulsory stages or promises that the model can perform every action.

## 1. Budget motion space before generating

A tightly cropped character image is an identity reference, not necessarily a safe video input. Preserve it and prepare a separate input: scale uniformly, expand the canvas and place the character with clear space on all four sides. Allocate more room in the directions required by the expected motion envelope, camera view and pose changes. Count hair, clothing, held items and effects that are actually requested, not just the torso. Never use one universal padding percentage.

Inspect the complete prepared input and record canvas size, scale, placement, anchor and expected envelope. Match workflow dimensional constraints (this setup uses multiples of 32); padding must not silently alter saved registration geometry. Keep a compatible scale across action references rather than auto-fitting each action independently. Whole-subject clipping in a generated source cannot be repaired by later transparent padding: choose an intact window or revise framing/reference before regenerating.

Generation canvas and final sprite cells serve different purposes. Plan space at generation time, then place the finished animation using the shared character scale and agreed pivot. If an intact motion cannot fit the target cell at that scale, present a suitable larger cell/envelope or pose adjustment; do not silently shrink one action, squash the art or crop extremities.

## 2. Preserve identity and cross-action proportions

Use the original identity reference even when an action-specific still is created. Check head-to-body ratio, limb lengths, body shape, clothes, face, colors and accessories before approving the pose. Do not turn a stylized nonhuman design into human anatomy to make a pose easier. Estimate a shared scale from comparable anatomy or a documented character profile, not each pose's bounding-box height. Foreshortening and pose changes alter bounds without changing anatomical size.

Use a fixed scale throughout each clip and across the character's actions. Do not resize or crop each frame to its own alpha bounds. If reference generation changes the anatomy or model scale, correct it or report the mismatch; a smaller final silhouette does not prove that an anatomical clearance requirement was met. Measure requested clearance against an equivalent standing/reference scale, including all extremities.

## 3. Decide who owns translation

Determine from the request and game context whether world translation is supplied by game code or the animation. When the game owns it, request stationary framing and remove unintended root travel/camera drift during registration while retaining limb articulation, intended local bob and pose changes. If the animation owns travel, preserve the intended path and document it.

Choose a meaningful anchor/tracker for the action; feet, hips, torso or a stable point may be suitable. Do not universally pin feet on airborne or rotating motion. Do not universally center the alpha centroid: changing poses move that centroid without world travel, and intended lowering must stay low. Document any tracked offsets and distinguish global translation removal from actual pose stabilization. Use a consistent runtime pivot/conversion across states and review transitions at game scale.

## 4. Plan state entry, exit and loop semantics

Infer or clarify whether the requested motion needs anticipation, an active phase, recovery, a sustained cycle or a terminal hold. Omit phases the user does not want; do not add a standing pause or return to idle by default. Consider shared phases and separate clips for distinct states when they improve game transitions. Keep pose, orientation, scale and pivot compatible at joins.

Use first/last-frame bindings only when the workflow supports them and the intended end state warrants them. They do not guarantee closure. For sustained motion, select and visually review a coherent cycle. One-shots use action-aware timing/retiming. Do not reverse directional locomotion or ordered actions as a shortcut. A documented ping-pong loop can suit reversible secondary sway, but inspect turnaround pauses and disclose repeated/reversed source frames. Source duration/fps and game frame count/playback time remain independent.

## 5. Scope local motion when appropriate

If only secondary parts should move, identify moving and fixed regions explicitly; otherwise preserve the substantial motion required by the action. Request stable expression, anatomy and camera where needed. If generation disturbs fixed parts, local compositing may isolate the intended movement. Record the regions/base frame, inspect joins, and preserve each animated layer's changing alpha using proper RGBA compositing; never freeze a still alpha over moving RGB. Region isolation must not hide missing required action or be described as an unmodified model result.

## 6. Inspect before accepting or retrying

Watch the source video and the final animation, inspect a contact sheet and matte edges on light/dark backgrounds, and check game-scale readability, identity, anatomy, clipping, camera/root drift, transitions, loop seam, requested clearance and fixed/moving regions. Numeric/tool success is not art approval. Verify output dimensions, timing, transparency and any reported hashes; state unresolved warnings and untested engine behavior.

Reuse completed generation for changes limited to frame selection, timing, registration or export. Resume pending jobs; inspect unknown jobs before any retry. When the same pose/framing error persists, stop repeating the unchanged prompt and reassess the action still, framing or segmentation. Existing authorization covers routine repairs, but does not authorize indefinite GPU retries or changing services. Explain a material workflow change or limitation before continuing beyond the agreed scope.
