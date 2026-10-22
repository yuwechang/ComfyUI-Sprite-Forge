# Generic prompt and correction library

Descriptions are authored for the actual request. These structural templates are motion contracts, not a supported-action list. Only apply correction clauses compatible with the explicit contract and motion properties.

```template cycle
{action}. Repeat complete continuous periods with matching moving phase and no stationary boundary.
```
```template oneshot-return
{action}. Complete each independent action and recover to the exact initial pose.
```
```template oneshot-hold
{action}. Complete each independent action and keep its intended terminal pose; no final recovery.
```

```clauses
never-turn | The character keeps facing {facing} the whole time: never turns around, never shows {pos} back and never faces the camera.
camera-locked | Locked camera and constant character size: no zoom, no push-in, no pull-out, no pan; the character is exactly the same size in every frame, before and after the action.
constant-size | The character keeps exactly the same size and proportions as the still in every frame; arms, legs and the weapon never grow longer.
feet-planted | Respect the explicit support constraints while preserving intended movement.
feet-ground-line | Respect the planned root trajectory without freezing moving support points.
inside-frame | The whole body, the weapon and every moving part stay fully inside the frame with a clear margin on every side; nothing is cut off by the frame edge.
flat-background | The background stays solid flat pure {key} for the whole shot: no floor, no ground, no shadow, no gradient, no glow, no haze, no light.
no-extras | Keep only the character and elements required by the requested action; remove unrequested effects or objects.
identity-lock | Preserve the reference character identity, proportions, colours, costume and equipment throughout the clip.
face-visible | Keep the face readable when required by the action, while allowing natural occlusion from the requested movement.
keep-colours | The colours stay exactly as in the still in every frame: no tint, no colour shift, no darkening and no glow on the character.
same-start-end | Complete recovery to the initial pose only for returning single-play candidates.
starts-from-still | The first frame is exactly the supplied image: the same pose, position and size; the motion starts from there.
single-action | Each candidate is one complete requested motion; source repetitions remain independent.
weapon-shape | Preserve the reference weapon count, shape and proportions throughout its movement.
no-text | No text, letters, glyphs, writing or logos anywhere.
no-flares | No cross flares, no starbursts, no four-point sparkles, no lens flares.
visible-motion | The motion is clearly visible at game size: a full, readable {action} with real movement of the body, not a still image.
in-place | The character stays in the same spot and never travels across the frame; the game moves the sprite.
fluid-motion | Preserve requested rhythm and intentional key holds without unrequested pauses.
steady-cycle | Preserve the intended rhythm and match moving phase and velocity at the continuous boundary.
no-blur | No motion-blur smears, no afterimages, no colour fringing on the weapon.
```

```gatefix
area | constant-size, camera-locked
feet | feet-ground-line
identity | identity-lock
zoom | camera-locked
turn | never-turn
edge | inside-frame
background | flat-background
extra | no-extras
motion | visible-motion, single-action
end-pose | same-start-end
colour | keep-colours
timing | fluid-motion
loop | steady-cycle
registration | starts-from-still, camera-locked
keying | flat-background, inside-frame
```
