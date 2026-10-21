#!/usr/bin/env python3
"""Retime one reviewed motion candidate with explicit keys, holds and events."""
from __future__ import annotations

import comfyui_forge_contracts
import argparse
import bisect
import json
import math
import re
import sys
from fractions import Fraction
from pathlib import Path
from typing import Any, Sequence

import numpy as np

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
import comfyui_forge_core  # noqa: E402  (this skill's vendored copy)
import comfyui_forge_gait_loop  # noqa: E402  (selection I/O and frame statistics)

RETIME_VERSION = comfyui_forge_core.FORGE_PACKAGE_VERSION
from comfyui_forge_motion_contract import TYPES
GAIT_KINDS = ('cycle',)
AMBIENT_KINDS = ()
KINDS = TYPES
TICK_HZ = 60
_EVENT = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_.:-]*)\s*@\s*([0-9]+)(t?)\s*$")
_KEY = re.compile(r"^\s*([A-Za-z][A-Za-z0-9_-]*)\s*=\s*([0-9]+)\s*@\s*([0-9]*\.?[0-9]+)\s*(?:\+\s*([0-9]+)\s*(?:ms)?)?\s*$")
_EVENT_SOURCE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_.:-]*)\s*=\s*([0-9]+)\s*$")
AUTO_FLOOR = 0.15           # auto-oneshot: a step (mean |change| 0-255) below this is still, whatever the clip ...
AUTO_ACTIVE = 0.20          # ... and below this share of the clip's 90th-percentile step
AUTO_SETTLE = 0.15          # the settle: the pose stays within 15% of its largest excursion from the first frame
AUTO_HOLD_KEEP = 2          # source frames kept of every static hold inside the action (a beat; the rest is cut)


def parse_spans(text: str, count: int) -> list[int]:
    """Exact source indices from a spans string (see the module help)."""
    indices: list[int] = []
    for item in str(text).split(","):
        item = item.strip()
        try:
            if not item:
                raise ValueError
            if "*" in item:
                frame, _, repeat = item.partition("*")
                times = int(repeat)
                if times < 1:
                    raise ValueError
                values = [int(frame)] * times
            elif ":" in item:
                parts = [int(part) for part in item.split(":")]
                if len(parts) not in (2, 3) or (len(parts) == 3 and parts[2] == 0):
                    raise ValueError
                values = list(range(*parts))
                if not values:
                    raise ValueError(f"span {item!r} is empty: the end is exclusive; use a:b:-1 to play backwards")
            else:
                values = [int(item)]
        except ValueError as error:
            raise ValueError(str(error) if str(error) else
                             f"--spans item {item!r} must be a:b, a:b:step, k or k*n") from None
        indices.extend(values)
    bad = [i for i in indices if not 0 <= i < count]
    if bad:
        raise ValueError(f"--spans frames {bad[:5]} are outside the {count} source frames")
    return indices


def sample_range(start: int, end: int, count: int | None) -> list[int]:
    """[start, end) evenly sampled to ``count`` frames, first and last frame included."""
    frames = end - start
    if count is None or count >= frames:
        return list(range(start, end))
    if count < 1:
        raise ValueError("--max-frames must be at least 1")
    if count == 1:
        return [start]
    return [start + comfyui_forge_gait_loop.round_half_up(Fraction(k * (frames - 1), count - 1)) for k in range(count)]


def scaled_edges(weights: Sequence[int], total: int) -> list[int]:
    """Cumulative edges for ``total`` split in proportion to ``weights`` (half-up rounding,
    exact sum; equal weights give forge_core.frame_durations).
    """
    cumulative = np.concatenate([[0], np.cumsum(weights)]).astype(object)
    whole = int(cumulative[-1])
    return [(2 * int(c) * total + whole) // (2 * whole) for c in cumulative]


def durations_from_edges(edges: Sequence[int], unit: str) -> list[int]:
    durations = [b - a for a, b in zip(edges, edges[1:])]
    if any(d < 1 for d in durations):
        raise ValueError(f"{len(durations)} frames cannot each get at least one {unit} from that total")
    return durations


def tick_durations(ticks: Sequence[int], hz: int) -> tuple[list[int], list[int]]:
    """Integer ms per frame from per-frame ticks on the ``hz`` grid, and the tick edges."""
    edges = np.concatenate([[0], np.cumsum(ticks)]).astype(int).tolist()
    ms = [(2 * t * 1000 + hz) // (2 * hz) for t in edges]
    return [b - a for a, b in zip(ms, ms[1:])], edges


def parse_ticks(text: str, frames: int, weights: Sequence[int]) -> list[int]:
    """--ticks N (split over the frames in proportion to their current durations) or one
    tick count per frame.
    """
    try:
        values = [int(v) for v in str(text).split(",")]
    except ValueError:
        raise ValueError("--ticks must be a total tick count or one integer per frame") from None
    if len(values) == 1 and frames > 1:
        if values[0] < frames:
            raise ValueError(f"--ticks {values[0]} cannot give each of {frames} frames a tick")
        return durations_from_edges(scaled_edges(weights, values[0]), "tick")
    if len(values) != frames or any(v < 1 for v in values):
        raise ValueError(f"--ticks lists {len(values)} values for {frames} frames; each frame needs >= 1 tick")
    return values


def frame_starts(durations: Sequence[int]) -> list[int]:
    return np.concatenate([[0], np.cumsum(durations)]).astype(int).tolist()


def check_policy(kind: str, policy: str, indices: Sequence[int]) -> list[str]:
    """Raise for the two loop rules; return the rules that were applied."""
    if policy == 'pingpong':
        raise ValueError('the selected motion must play forward; synthetic reversal changes its meaning')
    if any(b<a for a,b in zip(indices,indices[1:])):
        raise ValueError('source motion must play forward within one candidate')
    if kind == 'cycle' and policy != 'cycle': raise ValueError('continuous motion requires cycle playback')
    if kind != 'cycle' and policy != 'oneshot': raise ValueError('one-shot motion is not continuous even when its poses match')
    return ['one selected candidate, forward playback', 'ending follows its motion contract']


def parse_event(text: str, tick_mode: bool) -> dict:
    """NAME@MS, or NAME@Nt (ticks) in tick mode."""
    match = _EVENT.match(str(text))
    if not match:
        raise ValueError(f"--event must be NAME@MS or NAME@Nt, got {text!r}")
    name, value, ticks = match.group(1), int(match.group(2)), bool(match.group(3))
    if ticks:
        if not tick_mode:
            raise ValueError(f"--event {text}: tick times need --ticks")
        return {"name": name, "tick": value}
    return {"name": name, "atMs": value}


def place_event(event: dict, starts: Sequence[int], tick_edges: Sequence[int] | None, hz: int) -> dict:
    """Resolve an event to atMs (snapped to the tick grid in tick mode), its tick and its frame."""
    total = starts[-1]
    if tick_edges is not None:
        tick = event["tick"] if "tick" in event else comfyui_forge_gait_loop.round_half_up(Fraction(event["atMs"] * hz, 1000))
        if not 0 <= tick <= tick_edges[-1]:
            raise ValueError(f"event {event['name']} at tick {tick} is outside 0..{tick_edges[-1]}")
        at_ms = (2 * tick * 1000 + hz) // (2 * hz)
        return {**event, "atMs": int(at_ms), "frame": _frame_at(tick_edges, tick), "tick": int(tick)}
    at_ms = event["atMs"]
    if not 0 <= at_ms <= total:
        raise ValueError(f"event {event['name']} at {at_ms} ms is outside 0..{total} ms")
    return {**event, "atMs": int(at_ms), "frame": _frame_at(starts, at_ms)}


def _frame_at(edges: Sequence[int], value: int) -> int:
    """The frame showing at ``value`` on a timeline of frame ``edges`` (the last frame at the end)."""
    return min(len(edges) - 2, bisect.bisect_right(edges, value) - 1)


def tick_grid(rate: Fraction) -> tuple[int, int]:
    """(tick Hz, ticks per frame) of an output frame rate: the 60 Hz grid when a frame is a whole number
    of 60 Hz ticks (12, 15, 20, 30, 60 fps), else the rate's own fraction (24 fps: 24 Hz x 1; 12.5 fps:
    25 Hz x 2, which is exactly 80 ms).
    """
    rate = Fraction(rate)
    if rate <= 0:
        raise ValueError("the output frame rate must be positive")
    per = Fraction(TICK_HZ) / rate
    if per.denominator == 1:
        return TICK_HZ, int(per)
    return int(rate.numerator), int(rate.denominator)


def parse_key(text: str) -> dict:
    """NAME=SRC@FRACTION[+HOLDms] -> {name, source, at, holdMs}."""
    match = _KEY.match(str(text))
    if not match:
        raise ValueError(f"--key must be NAME=SOURCE@FRACTION[+HOLDms], such as marker=31@0.4+60; got {text!r}")
    at = float(match.group(3))
    if not 0.0 < at < 1.0:
        raise ValueError(f"--key {text}: the fraction must lie strictly between 0 and 1")
    return {"name": match.group(1), "source": int(match.group(2)), "at": at,
            "holdMs": int(match.group(4)) if match.group(4) else 0}


def parse_event_source(text: str) -> tuple[str, int]:
    match = _EVENT_SOURCE.match(str(text))
    if not match:
        raise ValueError(f"--event-source must be NAME=SOURCE (a source frame), such as cancel=80; got {text!r}")
    name = match.group(1)
    return name, int(match.group(2))


def motion_profile(clip: comfyui_forge_gait_loop.Clip, start: int, end: int) -> dict:
    """Motion energy of [start, end): ``steps[i]`` is the mean absolute change (0-255, premultiplied RGBA on
    the clip's reduced copies, cropped to the frames' union) into frame start+i (steps[0] = 0), ``pose[i]``
    the same against frame ``start``.
    """
    if clip.reduced is None:
        raise ValueError("motion_profile needs load_clip(..., keep_reduced=True)")
    f = clip.reduction
    boxes = clip.boxes[start:end]
    finite = np.isfinite(boxes).all(axis=1)
    if not finite.any():
        raise ValueError("every frame of the range is blank")
    x0, y0 = int(np.nanmin(boxes[finite, 0]) // f), int(np.nanmin(boxes[finite, 1]) // f)
    x1, y1 = int(-(-np.nanmax(boxes[finite, 2]) // f)), int(-(-np.nanmax(boxes[finite, 3]) // f))
    crops = [np.asarray(clip.reduced[i], np.float32)[y0:y1, x0:x1] for i in range(start, end)]
    steps = np.zeros(len(crops))
    pose = np.zeros(len(crops))
    for i in range(1, len(crops)):
        steps[i] = float(np.abs(crops[i] - crops[i - 1]).mean())
        pose[i] = float(np.abs(crops[i] - crops[0]).mean())
    return {"steps": steps, "pose": pose}


def detect_phases(steps: np.ndarray, pose: np.ndarray) -> dict:
    """Onset, settle and static holds (all relative to the range start) from the motion energy.

    A frame moves when the mean of its step and its neighbours' is at least max(AUTO_FLOOR, AUTO_ACTIVE x
    the 90th-percentile step). The onset is the first moving frame; the settle is the later of the last
    moving frame and the first frame from which the pose stays within AUTO_SETTLE of its largest excursion
    (back at rest). Holds are the runs of still frames between the onset and the settle (a held strike or
    hunch: the generator's slow drift and its duplicated frames stay under the moving threshold).
    """
    count = len(steps)
    padded = np.concatenate([[steps[min(1, count - 1)]], steps, [steps[-1]]])
    smooth = (padded[:-2] + padded[1:-1] + padded[2:]) / 3.0
    smooth[0] = 0.0
    active = max(AUTO_FLOOR, AUTO_ACTIVE * float(np.percentile(smooth[1:], 90))) if count > 1 else AUTO_FLOOR
    moving = smooth >= active
    if not moving.any():
        return {"onset": 0, "settle": count - 1, "holds": [], "active": active, "moving": False}
    onset = int(np.flatnonzero(moving)[0])
    last = int(np.flatnonzero(moving)[-1])
    peak = float(pose.max())
    settle = count - 1
    if peak > 0:
        near = pose <= AUTO_SETTLE * peak
        after = np.flatnonzero(~near[onset:])
        if after.size and int(after[-1]) + onset + 1 < count:
            settle = int(after[-1]) + onset + 1
    settle = max(last, min(settle, count - 1))
    holds = []
    run = None
    for i in range(onset, settle + 1):
        if not moving[i]:
            run = [i, i] if run is None else [run[0], i]
        elif run is not None:
            holds.append(tuple(run))
            run = None
    if run is not None and run[1] < settle:
        holds.append(tuple(run))
    return {"onset": onset, "settle": settle, "holds": holds, "active": round(active, 4), "moving": True}


def auto_oneshot(steps: np.ndarray, pose: np.ndarray, start: int, *, duration_ms: int, rate: Fraction,
                 keys: Sequence[dict] = (), event_sources: Sequence[tuple[str, int]] = ()) -> dict:
    """The played source frames, ticks and events of an automatically retimed one-shot.

    ``steps``/``pose`` cover source frames start, start+1, ...; ``keys`` hold absolute source frames.
    The output starts on the frame before the onset (the rest pose) and ends on the settle frame.
    """
    from comfyui_forge_motion_contract import validate_timing
    if len(steps)!=len(pose) or len(steps)<2:raise ValueError('motion profile needs matching arrays with at least two frames')
    if len({key.get('name') for key in keys})!=len(keys):raise ValueError('key names must be unique')
    validate_timing({key.get('name'):key for key in keys},[{'name':name,'source':source} for name,source in event_sources])
    if any(not start<=source<start+len(steps) for _,source in event_sources):raise ValueError('event source is outside the selected candidate')
    phases = detect_phases(steps, pose)
    first = 0
    last = len(steps) - 1  # retain the selected initial and terminal poses for either one-shot contract
    kept = []
    key_frames = {int(key["source"]) - start for key in keys}
    cut = 0
    hold_runs = []
    for a, b in phases["holds"]:
        if b - a + 1 > AUTO_HOLD_KEEP + 1:
            hold_runs.append((a, b))
    for i in range(first, last + 1):   # a hold keeps its first frames (a beat) and its last (the way out)
        inside = next(((a, b) for a, b in hold_runs if a <= i <= b), None)
        if inside is not None and i - inside[0] >= AUTO_HOLD_KEEP and i != inside[1] and i not in key_frames:
            cut += 1
            continue
        kept.append(i)
    hz, per = tick_grid(rate)
    frame_ms = Fraction(1000, 1) / Fraction(rate)
    exact_frames=Fraction(duration_ms)/frame_ms
    if exact_frames.denominator!=1: raise ValueError('duration times output fps must be an integer; resolve timing before retiming')
    frames=int(exact_frames)
    if frames<2: raise ValueError('a moving one-shot needs at least two playback slots for its endpoints')
    # keys: (output frame, kept position, hold frames, name); the first and the last frame are implicit keys
    pins = [(0, 0, 0, "start")]
    for key in sorted(keys, key=lambda item: item["source"]):
        local = int(key["source"]) - start
        if not first <= local <= last:
            raise ValueError(f"--key {key['name']}={key['source']} lies outside the motion "
                             f"{start + first}-{start + last}; check the source frame")
        position = kept.index(local) if local in kept else min(range(len(kept)), key=lambda p: abs(kept[p] - local))
        frame = int(round(key["at"] * frames))
        if frame < pins[-1][0] + max(1,pins[-1][2]) or frame > frames-2:
            raise ValueError(f"key {key['name']} at phase {key['at']} cannot fit the output grid without moving its timing; increase fps/count or revise the authored phase")
        if position <= pins[-1][1]:
            raise ValueError(f"--key {key['name']} does not come after the previous key in the source")
        hold = int(round(Fraction(int(key.get("holdMs", 0))) / frame_ms))
        pins.append((frame, position, hold, key["name"]))
    pins.append((frames - 1, len(kept) - 1, 0, "end"))
    for a, b in zip(pins, pins[1:]):
        if b[0] <= a[0] + a[2] - 1 or b[1] < a[1]:
            raise ValueError(f"the keys {a[3]} and {b[3]} leave no frames between them; lengthen --duration")
    positions = []
    for (frame_a, pos_a, hold_a, _), (frame_b, pos_b, _, _) in zip(pins, pins[1:]):
        base = frame_a + max(0, hold_a - 1)   # the last output frame that shows the key itself
        for k in range(frame_a, frame_b):
            if k <= base:
                positions.append(pos_a)
            else:
                share = Fraction(k - base, frame_b - base)
                positions.append(min(pos_b, comfyui_forge_gait_loop.round_half_up(pos_a + (pos_b - pos_a) * share)))
    positions.append(len(kept) - 1)
    indices, ticks = [], []
    for position in positions:   # equal neighbours merge into one longer frame
        source = start + kept[position]
        if indices and indices[-1] == source:
            ticks[-1] += per
        else:
            indices.append(source)
            ticks.append(per)
    edges = np.concatenate([[0], np.cumsum(ticks)]).astype(int).tolist()
    frame_of = {}   # output frame (before merging) -> tick
    tick = 0
    for k in range(len(positions)):
        frame_of[k] = tick
        tick += per
    events = [{"name": "in", "tick": 0}]
    for frame, _pos, _hold, name in pins[1:-1]:
        events.append({"name": name,
                       "tick": frame_of[frame]})
    for name, source in event_sources:
        local = source - start
        later = [k for k, position in enumerate(positions) if kept[position] >= local]
        if later:
            events.append({"name": name, "tick": frame_of[later[0]]})
    events.append({"name": "end", "tick": edges[-1]})
    info = {"onset": start + phases["onset"], "settle": start + phases["settle"], "first": start + first,
            "holds": [[start + a, start + b] for a, b in phases["holds"]], "cutFrames": cut,
            "sourceFrames": last - first + 1, "activeStep": phases["active"],
            "outputFps": comfyui_forge_gait_loop.fps_text(Fraction(rate)), "tickHz": hz, "ticksPerFrame": per,
            "keys": [{"name": name, "frame": frame, "tick": frame_of[frame], "holdFrames": hold}
                     for frame, _p, hold, name in pins[1:-1]]}
    return {"indices": indices, "ticks": ticks, "edges": edges, "events": events, "hz": hz,
            "info": info}


def choose_frames(args: argparse.Namespace, clip: comfyui_forge_gait_loop.Clip, fps: Fraction) -> dict:
    """The played source frames from exactly one of --selection, --spans or --range."""
    count = clip.count
    chosen = {"selection": None, "weights": None}
    if args.selection:
        selection = comfyui_forge_gait_loop.read_selection(args.selection)
        comfyui_forge_gait_loop.verify_selection(selection, args.selection, args.frames_dir, clip)
        chosen.update(selection=selection, indices=list(selection["indices"]), weights=list(selection["durations"]),
                      source=f"selection {Path(args.selection).name}",window=(selection["start"],selection["endExclusive"]))
    elif args.spans:
        chosen.update(indices=parse_spans(args.spans, count), source=f"spans {args.spans}")
    elif args.range:
        start, end = comfyui_forge_gait_loop.parse_interval(args.range)
        if end > count:
            raise ValueError(f"--range ends after the last of {count} frames")
        indices = sample_range(start, end, args.max_frames)
        chosen.update(indices=indices, source=f"range {start}:{end}"
                      + (f" sampled to {len(indices)}" if args.max_frames else ""))
    else:
        raise ValueError('choose a reviewed selection, span or candidate range')
    if args.max_frames is not None and not args.range:
        raise ValueError("--max-frames applies to --range")
    return chosen


def timing(args: argparse.Namespace, kind: str, chosen: dict, fps: Fraction) -> dict:
    """Integer durations from one of --ticks, --stride/--speed or --duration; else the
    selection's durations or source timing. Uneven input durations keep their proportions.
    """
    n = len(chosen["indices"])
    base = chosen["weights"] or [1] * n
    flags = [flag for flag, value in (("--duration-ms", args.duration),
                                      ("--ticks", args.ticks),
                                      ("--stride/--speed", args.stride is not None or args.speed is not None))
             if value]
    if len(flags) > 1:
        raise ValueError(f"choose one timing: {', '.join(flags)}")
    result = {"ticks": None, "tick_edges": None, "cadence": None}
    raw=chosen['selection']['raw'] if chosen['selection'] else {}
    if chosen['selection']:comfyui_forge_contracts.timeline(chosen['selection']['durations'],raw)
    if not flags and raw.get('ticks'):
        ticks=raw['ticks'];hz=raw.get('tickHz')
        if len(ticks)!=n or any(type(t) is not int or t<1 for t in ticks) or type(hz) is not int or hz<1:
            raise ValueError('invalid inherited tick timeline')
        result['ticks']=list(ticks);result['tick_hz']=hz
        result['durations'],result['tick_edges']=tick_durations(ticks,hz)
    elif args.ticks:
        result["ticks"] = parse_ticks(args.ticks, n, base)
        result["durations"], result["tick_edges"] = tick_durations(result["ticks"], args.tick_hz)
    elif args.stride is not None or args.speed is not None:
        if kind not in GAIT_KINDS:
            raise ValueError("--stride/--speed apply only to continuous cycles with explicit displacement")
        if (args.stride is None or args.speed is None or not (math.isfinite(args.stride) and math.isfinite(args.speed))
                or args.stride <= 0 or args.speed <= 0):
            raise ValueError("cadence needs both --stride and --speed as positive numbers (world units, units/s)")
        selection = chosen["selection"]
        cycles = args.cycles or (selection["raw"].get("cycles") if selection else None) or 1
        if type(cycles) is not int or cycles < 1:
            raise ValueError("the continuous cycle count must be a whole number >= 1 (--cycles)")
        exact = Fraction(str(args.stride)) * 1000 / Fraction(str(args.speed))
        total = comfyui_forge_gait_loop.round_half_up(exact * cycles)
        result["durations"] = durations_from_edges(scaled_edges(base, total), "ms")
        cadence_ms = Fraction(total, cycles)
        result["cadence"] = {"cadenceMs": int(cadence_ms) if cadence_ms.denominator == 1 else float(cadence_ms),
                             "strideWorldUnits": args.stride, "speedRef": args.speed, "cycles": cycles,
                             "exactCadenceMs": float(exact)}
    elif args.duration is not None:
        if args.duration < n:
            raise ValueError(f"--duration-ms {args.duration} ms cannot give each of {n} frames 1 ms")
        result["durations"] = durations_from_edges(scaled_edges(base, args.duration), "ms")
    else:
        result["durations"] = list(chosen["weights"]) if chosen["weights"] else comfyui_forge_gait_loop.source_durations(n, fps)
    result["starts"] = frame_starts(result["durations"])
    return result


def build_events(args: argparse.Namespace, timeline: dict) -> list[dict]:
    """Explicit authored events; tick mode adds timeline boundaries (in and end);
    plus every --event. Sorted by time.
    """
    edges, starts = timeline["tick_edges"], timeline["starts"]
    events = []
    if edges is not None:
        events.append({"name": "in", "tick": 0})
    for text in args.event_source:
        name,source=parse_event_source(text)
        indices=timeline['indices']
        if source not in indices:raise ValueError('event source was removed from the selected sequence; retain its pose before timing')
        position=indices.index(source)
        events.append({'name':name,'tick':edges[position]} if edges is not None else {'name':name,'atMs':starts[position]})
    inherited=[]
    selection=timeline.get('selection')
    if selection:
        raw=selection['raw'];old_ticks=raw.get('ticks');old_hz=raw.get('tickHz')
        for event in raw.get('events',[]):
            if 'tick' in event:
                if not old_ticks or type(old_hz) is not int or old_hz<1:raise ValueError('inherited event needs its tick timeline')
                phase=Fraction(event['tick'],sum(old_ticks))
            elif 'atMs' in event:phase=Fraction(str(event['atMs']))/sum(selection['durations'])
            else:raise ValueError('inherited event has no timestamp')
            if not 0<=phase<=1:raise ValueError('inherited event is outside the timeline')
            mapped={'name':event['name'],'inheritedFrom':event}
            if edges is not None:mapped['tick']=round(phase*edges[-1])
            else:mapped['atMs']=round(phase*starts[-1])
            inherited.append(mapped)
    custom = inherited+[parse_event(text, edges is not None) for text in args.event]
    if edges is not None and not any(event["name"] == "end" for event in custom):
        events.append({"name": "end", "tick": edges[-1]})
    placed = [place_event(event, starts, edges, args.tick_hz) for event in events + custom]
    unique={(event['name'],event.get('tick'),event['atMs']):event for event in placed}
    return sorted(unique.values(),key=lambda event:(event['atMs'],event['name']))


def retime_auto(args: argparse.Namespace) -> dict:
    """--auto-oneshot: motion-energy retiming of a one-shot (see the module help)."""
    out = Path(args.output_dir)
    fps = comfyui_forge_gait_loop.parse_fps(args.fps)
    if not args.range:
        raise ValueError("--auto-oneshot needs --range A:B (the source frames of the one-shot)")
    if args.duration is None or args.duration < 2:
        raise ValueError("--auto-oneshot needs --duration-ms MS, the game length of the one-shot")
    if args.ticks or args.stride is not None or args.speed is not None or args.max_frames is not None:
        raise ValueError("--auto-oneshot times its frames itself: drop --ticks, --stride, --speed and --max-frames")
    kind = args.kind
    if kind not in TYPES: raise ValueError('--kind requires an explicit motion contract')
    if kind in GAIT_KINDS or kind in AMBIENT_KINDS:
        raise ValueError(f"--auto-oneshot retimes one-shots; {kind} is a loop (use gait_loop select)")
    if args.policy not in (None, "oneshot"):
        raise ValueError("--auto-oneshot writes a oneshot policy")
    clip = comfyui_forge_gait_loop.load_clip(Path(args.frames_dir), fps, 1, allow_blank=True, keep_reduced=True)
    start, end = comfyui_forge_gait_loop.parse_interval(args.range)
    if end > clip.count:
        raise ValueError(f"--range ends after the last of {clip.count} frames")
    if end - start < 3:
        raise ValueError("--auto-oneshot needs at least 3 source frames")
    rate = comfyui_forge_gait_loop.parse_fps(args.output_fps) if args.output_fps else fps
    profile = motion_profile(clip, start, end)
    keys = [parse_key(text) for text in args.key]
    names = [key["name"] for key in keys]
    if len(set(names)) != len(names):
        raise ValueError("every --key needs its own name")
    result = auto_oneshot(profile["steps"], profile["pose"], start, duration_ms=args.duration, rate=rate,
                          keys=keys, event_sources=[parse_event_source(text) for text in args.event_source])
    indices, ticks, hz = result["indices"], result["ticks"], result["hz"]
    durations, edges = tick_durations(ticks, hz)
    starts = frame_starts(durations)
    total = starts[-1]
    rules = check_policy(kind, "oneshot", indices)
    custom = [parse_event(text, True) for text in args.event]
    events = sorted((place_event(event, starts, edges, hz) for event in result["events"] + custom),
                    key=lambda event: (event["atMs"], event["name"]))
    info = result["info"]
    extra: dict[str, Any] = {"ticks": ticks, "tickHz": hz, "auto": info, "motionType":kind}
    method = (f"retime --auto-oneshot: range {start}:{end}, motion {info['first']}-{info['settle']} "
              f"({info['sourceFrames']} source frames, {info['cutFrames']} static hold frames cut), keys "
              + (", ".join(f"{key['name']}@{key['frame']}" for key in info["keys"]) or "none")
              + f"; {len(indices)} frames, {total} ms on {hz} Hz ticks")
    review = ("Check requested timing, key poses, holds and the intended terminal pose at playback speed; motion energy is not artistic approval.")
    with comfyui_forge_core.staged_output(out) as stage:
        document = comfyui_forge_gait_loop.build_selection(clip, stage, indices, durations, policy="oneshot", method=method,
                                             review=review, kind=kind, events=events, extra=extra,
                                             window=(start, end))
        comfyui_forge_gait_loop.write_selection_files(stage, {"selection.json": document})
        rows = [{"frame": p, "sourceIndex": int(i), "startMs": int(starts[p]), "durationMs": int(durations[p]),
                 "ticks": int(ticks[p]), "startTick": int(edges[p])} for p, i in enumerate(indices)]
        checks = [{"id": "durations-sum", "status": "pass" if abs(total-float(args.duration))<=0.5 else "warn", "value": total, "threshold": float(args.duration)},
                  {"id": "integer-durations", "status": "pass", "value": min(durations), "threshold": 1},
                  {"id": "policy-rules", "status": "pass", "value": rules or ["none for this kind"]},
                  {"id": "visual-review", "status": "needs-visual-review", "value": None}]
        steps = [round(float(value), 3) for value in profile["steps"]]
        report = {"schema": "video2dsprite.retime_report.v1",
                  "tool": {"name": "retime", "version": RETIME_VERSION},
                  "frames": {"directory": comfyui_forge_gait_loop.directory_ref(clip.directory, stage), "count": clip.count,
                             "fps": comfyui_forge_gait_loop.fps_text(fps)},
                  "kind": kind, "policy": "oneshot", "source": f"auto-oneshot range {start}:{end}",
                  "cadence": None, "timeline": rows, "events": events, "rules": rules,
                  "auto": {**info, "durationMs": float(args.duration), "motionSteps": steps,
                           "pose": [round(float(value), 3) for value in profile["pose"]]},
                  "qa": comfyui_forge_gait_loop.qa_envelope("needs-visual-review", method, checks,
                                              comfyui_forge_gait_loop.frame_refs(clip, stage, sorted(set(indices))),
                                              [comfyui_forge_gait_loop.file_ref(stage / "selection.json", stage)],
                                              tool={"name": "retime", "version": RETIME_VERSION})}
        comfyui_forge_gait_loop.write_selection_files(stage, {"retime-report.json": report})
    summary = {"output": str(out), "selection": str(out / "selection.json"), "metadata": str(out / "retime-report.json"),
               "frames": len(indices), "durationMs": total, "policy": "oneshot",
               "auto": {key: info[key] for key in ("onset", "settle", "first", "cutFrames", "sourceFrames")}}
    return summary


def retime(args: argparse.Namespace) -> dict:
    if getattr(args, "auto_oneshot", False):
        return retime_auto(args)
    out = Path(args.output_dir)
    fps = comfyui_forge_gait_loop.parse_fps(args.fps)
    if args.tick_hz < 1:
        raise ValueError("--tick-hz must be at least 1")
    if args.cycles is not None and args.cycles < 1:
        raise ValueError("--cycles must be at least 1")
    clip = comfyui_forge_gait_loop.load_clip(Path(args.frames_dir), fps, 1, allow_blank=True)
    chosen = choose_frames(args, clip, fps)
    selection, indices = chosen["selection"], chosen["indices"]
    kind = args.kind or (selection["raw"].get("motionType") or selection["raw"].get("kind") if selection else None)
    if kind not in KINDS:
        raise ValueError(f"--kind is required (one of {', '.join(KINDS)})")
    timeline = timing(args, kind, chosen, fps)
    durations, starts, ticks = timeline["durations"], timeline["starts"], timeline["ticks"]
    total = starts[-1]
    default_policy = "cycle" if kind in GAIT_KINDS or kind in AMBIENT_KINDS else "oneshot"
    policy = args.policy or (selection["policy"] if selection and selection["policy"] else default_policy)
    rules = check_policy(kind, policy, indices)
    args.tick_hz=timeline.get("tick_hz",args.tick_hz)
    timeline["selection"]=selection
    timeline["indices"]=indices
    events = build_events(args, timeline)

    extra: dict[str, Any] = {"motionType":kind}
    if timeline["cadence"]:
        extra.update({key: timeline["cadence"][key] for key in ("cadenceMs", "strideWorldUnits", "speedRef", "cycles")})
    elif selection and selection["raw"].get("cycles"):
        extra["cycles"] = selection["raw"]["cycles"]
    if ticks is not None:
        extra.update({"ticks": ticks, "tickHz": args.tick_hz})
    method = f"retime: {chosen['source']}; {len(indices)} frames, {total} ms" + (
        f" on {args.tick_hz} Hz ticks" if ticks is not None else "")
    review = ("Check the retimed motion, authored events, holds and intended ending at playback speed.")
    with comfyui_forge_core.staged_output(out) as stage:
        document = comfyui_forge_gait_loop.build_selection(clip, stage, indices, durations, policy=policy, method=method,
                                             review=review, kind=kind, events=events, extra=extra,window=chosen.get("window"))
        comfyui_forge_gait_loop.write_selection_files(stage, {"selection.json": document})
        rows = [{"frame": p, "sourceIndex": int(i), "startMs": int(starts[p]), "durationMs": int(durations[p]),
                 **({"ticks": int(ticks[p]), "startTick": int(timeline["tick_edges"][p])} if ticks is not None else {})}
                for p, i in enumerate(indices)]
        checks = [{"id": "durations-sum", "status": "pass", "value": total, "threshold": total},
                  {"id": "integer-durations", "status": "pass", "value": min(durations), "threshold": 1},
                  {"id": "policy-rules", "status": "pass", "value": rules or ["none for this kind"]},
                  {"id": "visual-review", "status": "needs-visual-review", "value": None}]
        report = {"schema": "video2dsprite.retime_report.v1",
                  "tool": {"name": "retime", "version": RETIME_VERSION},
                  "frames": {"directory": comfyui_forge_gait_loop.directory_ref(clip.directory, stage), "count": clip.count,
                             "fps": comfyui_forge_gait_loop.fps_text(fps)},
                  "kind": kind, "policy": policy, "source": chosen["source"],
                  "cadence": timeline["cadence"], "timeline": rows, "events": events,
                  "rules": rules,
                  "qa": comfyui_forge_gait_loop.qa_envelope("needs-visual-review", method, checks,
                                              comfyui_forge_gait_loop.frame_refs(clip, stage, indices),
                                              [comfyui_forge_gait_loop.file_ref(stage / "selection.json", stage)],
                                              tool={"name": "retime", "version": RETIME_VERSION})}
        comfyui_forge_gait_loop.write_selection_files(stage, {"retime-report.json": report})
    summary = {"output": str(out), "selection": str(out / "selection.json"), "metadata": str(out / "retime-report.json"),
               "frames": len(indices), "durationMs": total, "policy": policy}
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--frames-dir", type=Path, required=True, help="RGBA PNG frames on one canvas")
    parser.add_argument("--fps", required=True, help="source frame rate: a number or N/D (24, 24000/1001)")
    parser.add_argument("--output-dir", type=Path, required=True, help="new directory; refused if it exists")
    parser.add_argument("--kind", choices=KINDS,
                        help="motion kind (default: the selection's kind): sets the default policy and the rules")
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--selection", type=Path, help="frame selection v1 or v2")
    choice.add_argument("--spans", help="a:b, a:b:step, k, k*n items, comma separated (0-based, end exclusive)")
    choice.add_argument("--range", help="0-based start:endExclusive, sampled with --max-frames")
    parser.add_argument("--max-frames", type=int, help="--range: evenly sample this many frames")
    parser.add_argument("--duration-ms",dest="duration", type=comfyui_forge_contracts.positive, help="total output duration in ms")
    parser.add_argument("--output-fps", help="automatic single-play output sample rate (default --fps)")
    parser.add_argument("--ticks", help=f"total ticks, or one tick count per frame, at --tick-hz (default {TICK_HZ})")
    parser.add_argument("--tick-hz", type=int, default=TICK_HZ, help=f"tick grid (default {TICK_HZ})")
    parser.add_argument("--stride", type=float, help="continuous cycles: explicit world displacement per period")
    parser.add_argument("--speed", type=float, help="continuous cycles: explicit world units per second")
    parser.add_argument("--cycles", type=int, help="complete periods in the selection (default: the selection's, else 1)")
    parser.add_argument("--event", action="append", default=[], metavar="NAME@MS",
                        help="extra event at ms, or NAME@Nt in ticks (repeatable), e.g. cancel@12t")
    parser.add_argument("--policy", choices=comfyui_forge_gait_loop.LOOP_POLICIES,
                        help="cycle for continuous motion; oneshot for either single-play contract")
    parser.add_argument("--auto-oneshot", action="store_true",
                        help="retime a slow one-shot from its motion energy: needs --range and --duration-ms; "
                             "cuts static holds, pins --key frames and samples on the --output-fps grid")
    parser.add_argument("--key", action="append", default=[], metavar="NAME=SRC@F[+HOLDms]",
                        help="--auto-oneshot: source frame SRC shows at fraction F of the duration and is held HOLD ms "
                             "; repeatable, only explicit reviewed keys")
    parser.add_argument("--event-source", action="append", default=[], metavar="NAME=SRC",
                        help="an event at reviewed source frame SRC; source timing retains that exact pose "
                             "; repeatable")
    return parser


def _run(argv: Sequence[str] | None = None) -> int:
    print(json.dumps(retime(build_parser().parse_args(argv)), ensure_ascii=True))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    return comfyui_forge_core.run_cli(_run, argv)


if __name__ == "__main__":
    raise SystemExit(main())
