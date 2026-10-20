#!/usr/bin/env python3
"""One approved still in, a whole game-ready sprite set out.

  plan     Read master.json (generate2dsprite.master.v1) and write a new set folder with
           set_plan.json: one image-to-video clip per action and view, each a loop or a
           motion with explicit spatial requirements, terminal behavior, numeric QC gates, and its own motion
           prompt built from references/motion-prompts.md.
  run      Make every action: comfyui_forge_prepare_i2v_input.py input, motion prompt, generate2dmedia
           the local ComfyUI adapter, comfyui_forge_video2dsprite.py process --matte soft, the numeric QC
           gates, automatic retakes with prompt fixes (up to --max-takes), comfyui_forge_register_clip.py
           apply, comfyui_forge_gait_loop.py select (loops) or comfyui_forge_retime.py (one-shots), comfyui_forge_finish_frames.py
           hd|pixel, comfyui_forge_engine_export.py package and verify. Every step is recorded in
           set_state.json and takes.jsonl, so running it again resumes where it stopped.
  review   Contact sheet per action and take, a cast line-up and review.json, for the host
           agent to LOOK at before it accepts anything.
  accept   Record the agent's semantic approval of one take.
  retake   Record a semantic rejection with a prompt fix; the next run makes a new take.
  report   One JSON with every action's route, takes, QC numbers, loop or timing and output
           files.

Exit codes: 0 done; 1 refused input or failed step; 2 usage.
Generation uses local ComfyUI directly and never selects another provider.
"""
from __future__ import annotations

import comfyui_forge_contracts
import comfyui_forge_animation_spec
import comfyui_forge_finalize_animation
import comfyui_forge_gait_loop
from comfyui_forge_motion_contract import MODES
import argparse
import concurrent.futures
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any, Callable, Sequence

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "comfyui-forge-generate2dmedia" / "scripts"))
from comfyui_forge_frame_rules import frame_count

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import comfyui_forge_core  # noqa: E402  (this skill's vendored copy)
import comfyui_forge_matte  # noqa: E402
import comfyui_forge_colour_lock  # noqa: E402  (sibling: master colours for the colour gate)
import comfyui_forge_prepare_i2v_input as prep  # noqa: E402  (sibling: opaque-master keying, stance anchor, prompt lint)
from comfyui_forge_motion_contract import TYPES, contract, definitions
import comfyui_forge_register_clip  # noqa: E402  (sibling: job geometry, the master as placed in the video)

TOOL_NAME = "sprite_set"
TOOL_VERSION = comfyui_forge_core.FORGE_PACKAGE_VERSION
MASTER_SCHEMA = "generate2dsprite.master.v1"
PLAN_SCHEMA = "video2dsprite.sprite_set_plan.v1"
STATE_SCHEMA = "video2dsprite.sprite_set_state.v1"
TAKE_SCHEMA = "video2dsprite.sprite_set_take.v1"
QC_SCHEMA = "video2dsprite.sprite_set_qc.v1"
REVIEW_SCHEMA = "video2dsprite.sprite_set_review.v1"
REPORT_SCHEMA = "video2dsprite.sprite_set_report.v1"
PLAN_FILE, STATE_FILE, TAKES_FILE = "set_plan.json", "set_state.json", "takes.jsonl"
LIBRARY_FILE = HERE.parent / "references" / "motion-prompts.md"

SCRIPTS = {name: HERE / f"comfyui_forge_{name}.py" for name in
           ("prepare_i2v_input", "video2dsprite", "register_clip", "gait_loop", "retime")}
FINISH_SCRIPT = HERE / "comfyui_forge_finish_frames.py"
TOOL_TIMEOUT = 1800.0
VIEWS = ("side", "front", "back")
FINISHES = ("hd", "pixel")
TARGET_HEIGHT = {"hd": 256, "pixel": 80}      # finished body height in px for a hero
LUMA = np.array([0.299, 0.587, 0.114], np.float32)
QC_SUBJECT_PX = 112                          # QC works on frames reduced to about this body height
GATE_IDS = ("area", "feet", "identity", "zoom", "turn", "edge", "background", "extra", "motion", "end-pose",
            "colour", "timing", "loop", "registration", "keying")


# --------------------------------------------------------------------------- action and canvas presets

@dataclass(frozen=True)
class ActionPreset:
    """How one action is generated and cut."""

    kind: str                  # loop | oneshot
    loop_kind: str | None      # generic cycle analysis
    gait_state: str | None     # optional explicit low-level analysis parameter
    prepare_action: str        # prepare_i2v_input --action (its job records this template)
    canvas: str                # square | tall | wide
    pin_last: bool             # end frame pinned to the master when the route takes a last frame
    lock: str                  # register_clip --lock: feet | none
    airborne: bool             # the feet leave the ground (the feet gate checks start and end only)
    hit_tick: bool             # one-shot with a hit event on its largest reach
    returns_to_rest: bool      # the clip starts and ends on the master pose
    min_motion: float          # pose change (share of the master area) that proves the action happened
    retime_kind: str           # retime.py --kind


def generic_preset(definition):
    rules=contract(definition['type'])
    return ActionPreset('loop' if rules['continuous'] else 'oneshot',
                        'cycle' if rules['continuous'] else None, None, definition['type'],
                        definition.get('framing','square'), False, definition.get('lock','none'),
                        definition.get('airborne',False), False, rules['returnsToRest'],
                        0.02, definition['type'])


PLANTED_CLAUSES = ("feet-planted",)
MOVING_FEET_CLAUSE = "feet-ground-line"

# Explicit geometric framing options; never selected from a motion label.
CANVAS_PRESETS = {"square": {"aspect": None, "headroom": None, "lead": 0.0},
                  "tall": {"aspect": (3, 4), "headroom": 0.34, "lead": 0.0},
                  "wide": {"aspect": (16, 9), "headroom": None, "lead": 0.06}}

BASE_GATES: dict[str, dict[str, Any]] = {
    "area": {"min": 0.72, "max": 1.32, "maxBadShare": 0.1},
    "feet": {"max": 0.05, "badFrames": 3, "mode": "all"},
    # Identity: frame 0 must reproduce the master (start); afterwards the head is matched against the master and
    # frame 0 at 3 scales and a turned or bobbing head only warns (min). Only a severe loss fails: more than half
    # the frames under 0.30 (calibrated on the 2026-10-06 live run, where the old hard 0.5 floor rejected 18 of 24
    # good takes and no real identity loss happened).
    "identity": {"start": 0.8, "min": 0.5, "badFrames": 2, "severe": 0.30, "severeShare": 0.5,
                 "scales": [0.9, 1.0, 1.1]},
    # Colour: a frame is bled when more than 2% of the body shows a hue no master colour at that height has
    # (chroma > 0.05 and 0.06 or more from every master colour of the band, in OKLab a/b); the take fails when 15%
    # of its frames are (live run: 29-41% on the six bled runs, at most 7% on the 24 good takes). Region drift (a
    # part shifted, which the finish's colour lock undoes) only warns: over 0.03 in 40% of the frames.
    "colour": {"foreign": 0.02, "badShare": 0.15, "drift": 0.03, "driftShare": 0.4},
    # Timing (one-shots): the motion from onset to settle and the longest static hold inside it. Too slow warns
    # while the set retimes one-shots (retime --auto-oneshot) and fails when it keeps the clip's speed.
    "timing": {"maxSeconds": 2.0, "maxHoldSeconds": 0.5},
    "zoom": {"max": 0.08},
    "turn": {"enabled": True, "margin": 0.08, "run": 3},
    "edge": {"px": 2},
    "background": {"tolerance": 48.0, "maxImpure": 0.004, "badFrames": 2},
    "extra": {"max": 0.015, "badFrames": 2},
    "motion": {"min": 0.02},
    "endPose": {"enabled": True, "min": 0.8},
    "window": {"loopSeconds": 1.0},
}


# --------------------------------------------------------------------------- small helpers

def _ascii(text: Any) -> str:
    return comfyui_forge_core.ascii_text(str(text))


def _now() -> str:
    return comfyui_forge_core.utc_timestamp()


def _even(value: float) -> int:
    return max(16, 2 * comfyui_forge_core.round_half_up(value / 2))


_ABSOLUTE = re.compile(r"^(?:[A-Za-z]:[\\/]|[\\/]{2}|/)")


_EMBEDDED = re.compile(r"(?<![A-Za-z0-9])(?:[A-Za-z]:[\\/]|\\\\)[^\s\"'<>|*?]*")


def _last_part(path: str) -> str:
    return re.split(r"[\\/]", path.rstrip("\\/"))[-1] or path


def _scrub(value: Any) -> Any:
    """A JSON value with every absolute path cut to its last component, also inside messages (written JSON
    never holds one); keys starting with _ are dropped."""
    if isinstance(value, dict):
        return {str(key): _scrub(item) for key, item in value.items() if not str(key).startswith("_")}
    if isinstance(value, (list, tuple)):
        return [_scrub(item) for item in value]
    if isinstance(value, str):
        if _ABSOLUTE.match(value) and not any(char.isspace() for char in value):
            return _last_part(value)
        return _EMBEDDED.sub(lambda match: _last_part(match.group(0)), value)
    if isinstance(value, np.generic):
        return value.item()
    return value


def _json_line(text: str) -> dict | None:
    """The last line of ``text`` that is a JSON object (every forge CLI prints one summary line)."""
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if isinstance(value, dict):
                return value
    return None


def _error_line(stderr: str) -> str:
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    errors = [line for line in lines if line.startswith("error:")]
    text = errors[-1] if errors else (lines[-1] if lines else "no output")
    return text[6:].strip() if text.startswith("error:") else text


def _natural(path: Path) -> list:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", path.name)]


def _pngs(folder: Path) -> list[Path]:
    return sorted((path for path in folder.glob("*.png") if path.is_file()), key=_natural)


def _ranges(frames: Sequence[int], limit: int = 8) -> str:
    """'3-7, 12, 20-21' for a sorted list of frame numbers."""
    runs: list[list[int]] = []
    for frame in sorted(set(int(f) for f in frames)):
        if runs and frame == runs[-1][1] + 1:
            runs[-1][1] = frame
        else:
            runs.append([frame, frame])
    text = [f"{a}-{b}" if b > a else str(a) for a, b in runs[:limit]]
    return ", ".join(text) + (f" and {len(runs) - limit} more runs" if len(runs) > limit else "")


def _round(value: Any, digits: int = 4) -> Any:
    if isinstance(value, float):
        return round(value, digits) if math.isfinite(value) else None
    if isinstance(value, np.floating):
        return _round(float(value), digits)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (list, tuple)):
        return [_round(item, digits) for item in value]
    if isinstance(value, dict):
        return {key: _round(item, digits) for key, item in value.items()}
    return value


def _move_aside(path: Path) -> Path:
    """Keep an unrecorded leftover (a crash between a tool's publish and the state save) beside the new run."""
    for number in range(1, 1000):
        target = path.with_name(f"{path.name}.orphan-{number}")
        if not os.path.lexists(target):
            os.replace(path, target)
            return target
    raise ValueError(f"too many orphaned copies of {path.name}; clean the folder")


def _write_new_json(path: Path, data: Any) -> None:
    """Publish a JSON file that must not exist yet (no-replace)."""
    stage = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        comfyui_forge_core.write_json(stage, data, no_clobber=False)
        comfyui_forge_core.publish_file_no_replace(stage, path)
    finally:
        stage.unlink(missing_ok=True)


def _publish_png(image: Image.Image | np.ndarray, path: Path) -> None:
    stage = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        comfyui_forge_core.save_png(image, stage)
        comfyui_forge_core.publish_file_no_replace(stage, path)
    finally:
        stage.unlink(missing_ok=True)


def _next_numbered(folder: Path, stem: str, suffix: str) -> Path:
    for number in range(1, 10000):
        candidate = folder / f"{stem}-{number:03d}{suffix}"
        if not os.path.lexists(candidate):
            return candidate
    raise ValueError(f"no free {stem}-NNN{suffix} name in {folder.name}")


def _fps_value(text: Any) -> float:
    return float(_fps_fraction(text))


def _fps_fraction(text: Any) -> Fraction:
    """A frame rate as an exact fraction: 24, "24/1", 12.5, "25/2" (floats are read from their shortest text)."""
    if isinstance(text, Fraction):
        rate = text
    elif isinstance(text, bool):
        raise ValueError(f"frame rate must be a number, got {text!r}")
    elif isinstance(text, int):
        rate = Fraction(text)
    else:
        try:
            rate = Fraction(str(text).strip())
        except (ValueError, ZeroDivisionError):
            raise ValueError(f"frame rate must be a number or N/D, got {text!r}") from None
    if rate <= 0:
        raise ValueError(f"frame rate must be positive, got {text!r}")
    return rate.limit_denominator(1000)


# --------------------------------------------------------------------------- tools by path

class ToolFailure(RuntimeError):
    """A sibling CLI exited non-zero; ``message`` is its error line."""

    def __init__(self, tool: str, code: int, message: str):
        super().__init__(f"{tool} exited {code}: {message}")
        self.tool, self.code, self.message = tool, code, message


def _child_env() -> dict[str, str]:
    return {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"}


def run_tool(script: Path, args: Sequence[Any], *, timeout: float = TOOL_TIMEOUT,
             label: str | None = None) -> tuple[dict, list[str]]:
    """Run a forge CLI by path; returns its one-line JSON summary and its warning lines."""
    label = label or script.name
    argv = [sys.executable, str(script), *(str(arg) for arg in args)]
    try:
        done = subprocess.run(argv, capture_output=True, timeout=timeout, env=_child_env(), check=False)
    except subprocess.TimeoutExpired:
        raise ToolFailure(label, -1, f"timed out after {timeout:g} s") from None
    stdout = done.stdout.decode("utf-8", "replace")
    stderr = done.stderr.decode("utf-8", "replace")
    if done.returncode != 0:
        raise ToolFailure(label, done.returncode, _error_line(stderr))
    summary = _json_line(stdout)
    if summary is None:
        raise ToolFailure(label, 0, "printed no JSON summary line")
    warnings = [line.strip()[8:].strip() for line in stderr.splitlines() if line.strip().startswith("warning:")]
    return summary, warnings


# --------------------------------------------------------------------------- the prompt library

_FENCE = re.compile(r"^```(template|negatives|clauses|gatefix)(?:[ \t]+([A-Za-z0-9_-]+))?[ \t]*\r?\n(.*?)^```[ \t]*$",
                    re.M | re.S)
_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")


@dataclass(frozen=True)
class Library:
    """references/motion-prompts.md: per-action templates, negatives and the failure clause library."""

    sha256: str
    templates: dict[str, str]
    negatives: dict[str, str]
    clauses: dict[str, str]
    gatefix: dict[str, list[str]]


def load_library(path: Path = LIBRARY_FILE) -> Library:
    """Parse the fenced ``template``/``negatives``/``clauses``/``gatefix`` blocks of motion-prompts.md."""
    raw = Path(path).read_bytes()
    text = raw.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")   # a CRLF checkout (core.autocrlf)
    templates: dict[str, str] = {}
    negatives: dict[str, str] = {}
    clauses: dict[str, str] = {}
    gatefix: dict[str, list[str]] = {}
    for kind, name, body in _FENCE.findall(text):
        if kind in ("template", "negatives"):
            target = templates if kind == "template" else negatives
            if not name or name in target:
                raise ValueError(f"{Path(path).name}: every ```{kind} block needs one new action name")
            target[name] = " ".join(body.split())
            continue
        for number, line in enumerate(body.splitlines(), 1):
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            ident, sep, value = line.partition("|")
            ident, value = ident.strip(), " ".join(value.split())
            if not sep or not re.fullmatch(r"[a-z0-9-]+", ident) or not value:
                raise ValueError(f"{Path(path).name}: ```{kind} line {number} must be 'id | text'")
            if kind == "clauses":
                clauses[ident] = value
            else:
                gatefix[ident] = [item.strip() for item in value.split(",") if item.strip()]
    missing = [kind for kind in TYPES if kind not in templates]
    unknown = sorted({ident for ids in gatefix.values() for ident in ids if ident not in clauses})
    unmapped = [gate for gate in GATE_IDS if gate not in gatefix]
    if missing or unknown or unmapped:
        raise ValueError(f"{Path(path).name} is incomplete: templates missing for {missing}, unknown clause ids "
                         f"{unknown}, gates without a fix {unmapped}")
    return Library(comfyui_forge_core.sha256_bytes(raw), templates, negatives, clauses, gatefix)


def fill(text: str, words: dict[str, str]) -> str:
    """Replace {facing}, {toward}, {away}, {pos}, {key}, {style} and {action}; unknown names stay."""
    return _PLACEHOLDER.sub(lambda match: words.get(match.group(1), match.group(0)), text)


def prompt_words(facing: str, key: str, style: str, pronoun: str, action: str) -> dict[str, str]:
    lock = {"left": "LEFT", "right": "RIGHT", "front": "the viewer", "back": "away from the viewer"}[facing]
    toward = {"left": "to the LEFT", "right": "to the RIGHT", "front": "toward the viewer",
              "back": "away from the viewer"}[facing]
    away = {"left": "to the RIGHT", "right": "to the LEFT", "front": "away from the viewer",
            "back": "toward the viewer"}[facing]
    return {"facing": lock, "toward": toward, "away": away, "pos": pronoun, "key": key_words(key)[0],
            "style": style, "action": action}


def key_words(key: str) -> tuple[str, str]:
    """(colour word, background clause) for the flat key backdrop."""
    if key == "magenta":
        return "magenta", "solid flat pure magenta background only for the whole shot"
    if key == "green":
        return "green", "solid flat pure bright green background (#00FF00 green screen) only for the whole shot"
    if key == "blue":
        return "blue", "solid flat pure blue background (#0000FF) only for the whole shot"
    return key, f"solid flat pure {key} background only for the whole shot"


def identity_phrase(recap: str) -> str:
    """'The same <recap>' without a doubled article or a closing full stop."""
    text = " ".join(str(recap).split()).rstrip(" .")
    text = re.sub(r"^(?:the same|a|an|the)\s+", "", text, flags=re.I)
    return text


def moves_feet(entry: dict) -> bool:
    """Only explicit motion properties authorize constraints on moving support points."""
    return bool(entry.get('movesFeet') or entry.get('airborne'))



def build_prompt(entry: dict, plan: dict, fixes: Sequence[str]) -> str:
    """The game-opus55 prompt shape: 'The same <identity>' + facing lock + ONE action + same start
    and end pose + negatives and fix clauses + locked camera, flat key background, exact style."""
    master = plan["masters"][entry["view"]]
    key = entry.get("generationKey",plan["key"])
    words = prompt_words(master["facing"], key, plan["style"], plan["pronoun"], entry["action"])
    if moves_feet(entry):   # an older state may still carry the planted-feet clause: never send it
        planted = {" ".join(str(plan.get("clauses", {}).get(clause, "")).split()).lower() for clause in PLANTED_CLAUSES}
        planted.discard("")
        fixes = [fix for fix in fixes if " ".join(str(fix).split()).lower() not in planted]
    parts = [f"The same {identity_phrase(master['identityRecap'])}. "
             f"Requested motion and constraints: {fill(entry['motion'], words).strip()}"]
    candidates = plan.get("generation", {}).get("candidateCount", 3)
    parts.append(f"The source contains {candidates} complete independent demonstrations of this SAME action for comparison, "
                 "not one action stretched across the full source duration. Completeness comes before count; "
                 "select only ONE demonstration for the final game animation.")
    if entry.get("kind") == "loop":
        parts.append("Each demonstration is one complete motion cycle; continue naturally between cycles without standing pauses.")
    elif entry["returnsToRest"]:
        parts.append("Each candidate starts from the reference pose, performs the complete action and recovers. "
                     "Separate candidates with a brief reset; exclude resets from the selected action.")
    else:
        parts.append("Keep each candidate's intended terminal pose. Reset to the starting pose only BETWEEN source demonstrations; "
                     "that reset is never part of the final single-play action.")
    seen = set()
    for clause in [entry.get("negatives") or "", *fixes]:
        text = fill(str(clause), words).strip()
        if text and text.lower() not in seen:
            seen.add(text.lower())
            parts.append(text if text.endswith((".", "!", "?")) else text + ".")
    parts.append(f"camera locked, no zoom, no pan; {key_words(key)[1]}; keep the exact {plan['style']} look, palette, "
                 "proportions and costume of the still; one action type, repeated as independent candidates.")
    return " ".join(part.strip() for part in parts if part.strip()) + "\n"


def lint_findings(prompt: str, key: str) -> list[dict[str, str]]:
    """prepare_i2v_input lint, minus the numeric work region and timeline rules: the game-opus55 recipe
    frames the clip by the input image and names one action instead."""
    return [item for item in prep.lint_prompt(prompt, key if key in comfyui_forge_matte.DECLARED_KEYS else None)
            if item["rule"] not in ("missing-work-region", "missing-timeline")]


# --------------------------------------------------------------------------- the master

@dataclass(frozen=True)
class Master:
    """generate2dsprite.master.v1 plus the geometry measured on its padded PNG."""

    json_path: Path
    png_path: Path
    data: dict
    name: str
    identity_recap: str
    facing: str
    finish: str
    klass: str
    key: str
    key_rgb: tuple[int, int, int]
    size: tuple[int, int]
    box: tuple[int, int, int, int]
    anchor: tuple[float, float]
    area: int
    framing: dict
    style: str | None


def _parse_key(value: Any) -> tuple[str, tuple[int, int, int]]:
    if isinstance(value, dict):
        value = next((value[k] for k in ("color", "colour", "name", "hex", "rgb", "key") if value.get(k) is not None),
                     None)
    if value is None:
        return "magenta", comfyui_forge_matte.DECLARED_KEYS["magenta"]
    if isinstance(value, (list, tuple)) and len(value) == 3:
        value = "#" + "".join(f"{int(channel):02x}" for channel in value)
    text = str(value).strip().lower()
    if text in comfyui_forge_matte.DECLARED_KEYS:
        return text, tuple(comfyui_forge_matte.DECLARED_KEYS[text])
    digits = text[1:] if text.startswith("#") else text
    if not re.fullmatch(r"[0-9a-f]{6}", digits):
        raise ValueError(f"master.json key must be magenta, green, blue, #rrggbb or [r, g, b]; got {value!r}")
    rgb = tuple(int(digits[i:i + 2], 16) for i in (0, 2, 4))
    for name, declared in comfyui_forge_matte.DECLARED_KEYS.items():
        if tuple(declared) == rgb:
            return name, rgb
    return "#" + digits, rgb


def _parse_facing(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("direction") or value.get("value") or value.get("facing")
    text = str(value or "").strip().lower()
    aliases = {"l": "left", "r": "right", "screen left": "left", "screen right": "right", "viewer": "front",
               "toward the viewer": "front", "away": "back", "away from the viewer": "back"}
    text = aliases.get(text, text)
    if text not in ("left", "right", "front", "back"):
        raise ValueError(f"master.json facing must be left, right, front or back; got {value!r}")
    return text


def _parse_size(value: Any) -> tuple[int, int] | None:
    if isinstance(value, (int, float)) and value > 0:
        return int(value), int(value)
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return int(value[0]), int(value[1])
    if isinstance(value, dict) and "width" in value and "height" in value:
        return int(value["width"]), int(value["height"])
    if isinstance(value, str):
        match = re.fullmatch(r"\s*(\d+)\s*[x,]\s*(\d+)\s*", value)
        if match:
            return int(match.group(1)), int(match.group(2))
    return None


def _master_png_ref(data: dict, base: Path) -> tuple[Path, str | None]:
    """The padded master PNG named in master.json ``files`` (a dict or a list of {path, sha256})."""
    found: list[tuple[str, str, str | None]] = []

    def add(entry: Any, label: str) -> None:
        if isinstance(entry, str):
            found.append((label, entry, None))
        elif isinstance(entry, dict) and isinstance(entry.get("path"), str):
            found.append((" ".join(str(entry.get(k) or "") for k in ("role", "name", "kind")) + " " + label,
                          entry["path"], entry.get("sha256")))
        elif isinstance(entry, dict) and label.lower().endswith(".png"):   # {"master.png": {"sha256": ...}}
            found.append((label, label, entry.get("sha256")))

    files = data.get("files")
    if isinstance(files, dict):
        for name, entry in files.items():
            add(entry, str(name))
    elif isinstance(files, list):
        for entry in files:
            add(entry, "")
    pngs = [item for item in found if item[1].lower().endswith(".png")]
    if not pngs:
        raise ValueError("master.json files names no PNG; it needs the padded master.png with its sha256")

    def rank(item: tuple[str, str, str | None]) -> int:
        words = (item[0] + " " + Path(item[1]).name).lower()
        return 3 if "cutout" in words or "rgba" in words else (2 if "pad" in words else (1 if "master" in words else 0))

    _, relative, digest = max(pngs, key=rank)   # first of the best rank: padded, then master, then any PNG
    path = Path(relative)
    return (path if path.is_absolute() else base / path), digest


def load_master(path: Path) -> Master:
    """Read master.json, check the padded PNG's sha256, key an opaque master like prepare_i2v_input does
    and measure the subject box, the stance anchor and the opaque area."""
    path = Path(path)
    try:
        data = comfyui_forge_core.read_json(path)
    except ValueError as error:
        raise ValueError(f"{path.name} is not valid JSON: {error}") from None
    if not isinstance(data, dict) or data.get("schema") != MASTER_SCHEMA:
        raise ValueError(f"{path.name} is not a {MASTER_SCHEMA} document")
    recap = data.get("identity_recap")
    if not isinstance(recap, str) or len(recap.split()) < 2:
        raise ValueError(f"{path.name} needs identity_recap, the long identity phrase every motion prompt repeats")
    png, digest = _master_png_ref(data, path.parent)
    if not png.is_file():
        raise ValueError(f"the master PNG {png.name} named in {path.name} is missing")
    image, info = comfyui_forge_core.load_rgba(png)
    if digest and str(digest).lower() != info["sha256"]:
        raise ValueError(f"{png.name} changed since {path.name} recorded it (sha256 mismatch)")
    key, key_rgb = _parse_key(data.get("key"))
    pixels = np.asarray(image)
    if int(pixels[..., 3].min()) >= 250:
        pixels, _record = prep.key_opaque_master(pixels, "auto", False)
    risk=prep.key_preflight(pixels,"auto")
    key=risk["recommended"]
    key_rgb=prep.key_rgb(key)
    alpha = pixels[..., 3]
    box = comfyui_forge_core.subject_bbox(alpha)
    if box is None:
        raise ValueError(f"{png.name} has no subject after keying its {key} backdrop")
    anchor = prep.measure_anchor(alpha, "stance")
    finish = str(data.get("finish") or "hd").strip().lower()
    if finish not in FINISHES:
        raise ValueError(f"master.json finish must be hd or pixel; got {data.get('finish')!r}")
    framing = data.get("framing") if isinstance(data.get("framing"), dict) else {}
    stated = _parse_size(framing.get("canvas"))
    if stated is not None and stated != (alpha.shape[1], alpha.shape[0]):
        raise ValueError(f"{path.name} framing.canvas {list(stated)} does not match {png.name} "
                         f"({alpha.shape[1]}x{alpha.shape[0]}); the master.json is stale")
    style = data.get("style") if isinstance(data.get("style"), str) and data.get("style").strip() else None
    return Master(json_path=path, png_path=png, data=data, name=str(data.get("name") or path.parent.name or "sprite"),
                  identity_recap=recap, facing=_parse_facing(data.get("facing")), finish=finish,
                  klass=str(data.get("class") or "hero").strip().lower(), key=key, key_rgb=key_rgb,
                  size=(alpha.shape[1], alpha.shape[0]), box=box, anchor=(float(anchor[0]), float(anchor[1])),
                  area=int((alpha > 127).sum()), framing=framing, style=style)


# --------------------------------------------------------------------------- placement

def placement(master: Master, preset: str) -> dict:
    """The provider canvas of one action: the master placed by one recorded transform (prepare_i2v_input
    --canvas --scale --root --anchor), its margin and the action padding that covers the whole video
    footprint on the master canvas (so register_clip never clips motion)."""
    spec = CANVAS_PRESETS[preset]
    W0, H0 = master.size
    x0, y0, x1, y1 = master.box
    ax, ay = master.anchor
    if spec["aspect"] is None:
        width, height, scale, root = W0, H0, 1.0, (ax, ay)
    else:
        aw, ah = spec["aspect"]
        height = H0
        width = _even(H0 * aw / ah)
        scale = 1.0
        bottom = max(H0 - ay, 8.0)
        root_y = ay
        if spec["headroom"]:
            top = spec["headroom"] * height
            scale = min(1.0, (height - bottom - top) / max(1.0, ay - y0), (width - 16.0) / max(1.0, x1 - x0))
            root_y = height - bottom
        lead = {"left": 1.0, "right": -1.0}.get(master.facing, 0.0) * spec["lead"] * width
        low, high = scale * (ax - x0) + 6.0, width - scale * (x1 - ax) - 6.0
        root_x = min(max(width / 2 + lead, low), high) if low <= high else width / 2
        root = (root_x, root_y)
    offset = (root[0] - scale * ax, root[1] - scale * ay)
    placed = (offset[0] + scale * x0, offset[1] + scale * y0, offset[0] + scale * x1, offset[1] + scale * y1)
    gap = min(placed[0], placed[1], width - placed[2], height - placed[3])
    if gap < 1:
        raise ValueError(f"the master's subject touches the {preset} canvas edge ({width}x{height}); re-pad the master "
                         "with a free margin on every side")
    margin = max(0, min(20, int(math.floor(gap)) - 3))
    padding = [max(0, math.ceil(offset[0] / scale - 1e-9)), max(0, math.ceil(offset[1] / scale - 1e-9)),
               max(0, math.ceil((width - offset[0]) / scale - W0 - 1e-9)),
               max(0, math.ceil((height - offset[1]) / scale - H0 - 1e-9))]
    return {"preset": preset, "canvas": [width, height], "scale": round(scale, 6),
            "root": [round(root[0], 4), round(root[1], 4)], "anchor": [ax, ay],
            "subjectBox": [round(value, 2) for value in placed], "margin": margin, "padding": padding,
            "headroom": round(placed[1] / height, 4)}


# --------------------------------------------------------------------------- QC gates (numeric)

def _block_mean(array: np.ndarray, factor: int) -> np.ndarray:
    """Mean of factor x factor blocks (the trailing partial block is dropped), as float32."""
    if factor <= 1:
        return array.astype(np.float32)
    height, width = (array.shape[0] // factor) * factor, (array.shape[1] // factor) * factor
    cut = array[:height, :width].astype(np.float32)
    return cut.reshape(height // factor, factor, width // factor, factor, *cut.shape[2:]).mean(axis=(1, 3))


@dataclass
class QcFrame:
    """One take frame reduced for the gates: alpha (0-255), luma over mid grey, raw RGB, the edge touch
    measured at full resolution and, for the colour gate, the frame's colours (straight RGBA) reduced half
    as much as the rest."""

    alpha: np.ndarray
    luma: np.ndarray
    raw: np.ndarray | None
    edge: bool
    colour: np.ndarray | None = None


def _block_rgba(rgba: np.ndarray, factor: int) -> np.ndarray:
    """Straight-alpha RGBA reduced by factor x factor blocks on premultiplied colour (uint8)."""
    if factor <= 1:
        return np.asarray(rgba, np.uint8)
    alpha = _block_mean(rgba[..., 3], factor)
    premultiplied = _block_mean(rgba[..., :3].astype(np.float32) * (rgba[..., 3:4].astype(np.float32) / 255.0), factor)
    rgb = np.where(alpha[..., None] > 0.5, premultiplied / np.maximum(alpha[..., None] / 255.0, 1e-6), 0.0)
    return np.dstack([np.clip(rgb + 0.5, 0, 255), np.clip(alpha + 0.5, 0, 255)]).astype(np.uint8)


def qc_frame(rgba: np.ndarray, raw: np.ndarray | None, factor: int, edge_px: int, colour: bool = False) -> QcFrame:
    alpha = rgba[..., 3]
    band = max(1, int(edge_px))
    edge = bool((alpha[:band] > 16).any() or (alpha[-band:] > 16).any()
                or (alpha[:, :band] > 16).any() or (alpha[:, -band:] > 16).any())
    weight = alpha.astype(np.float32) / 255.0
    luma = (rgba[..., :3].astype(np.float32) @ LUMA) * weight + 128.0 * (1.0 - weight)
    return QcFrame(_block_mean(alpha, factor), _block_mean(luma, factor),
                   None if raw is None else _block_mean(raw[..., :3], factor), edge,
                   _block_rgba(rgba, max(1, factor // 2)) if colour else None)


def _box_sum(values: np.ndarray, height: int, width: int) -> np.ndarray:
    table = np.zeros((values.shape[0] + 1, values.shape[1] + 1), np.float64)
    table[1:, 1:] = values.astype(np.float64).cumsum(0).cumsum(1)
    return table[height:, width:] - table[:-height, width:] - table[height:, :-width] + table[:-height, :-width]


def _crop_padded(image: np.ndarray, left: int, top: int, width: int, height: int, fill: float) -> np.ndarray:
    out = np.full((height, width), fill, np.float64)
    x0, y0 = max(0, left), max(0, top)
    x1, y1 = min(image.shape[1], left + width), min(image.shape[0], top + height)
    if x0 < x1 and y0 < y1:
        out[y0 - top:y1 - top, x0 - left:x1 - left] = image[y0:y1, x0:x1]
    return out


def ncc_best(template: np.ndarray, image: np.ndarray, x0: int, y0: int, search: int) -> float | None:
    """Best zero-mean NCC of ``template`` with its top-left within +-search px of (x0, y0) in ``image``
    (padded with the mid-grey backdrop); None for a flat template."""
    height, width = template.shape
    centred = template.astype(np.float64) - float(template.mean())
    norm = math.sqrt(float((centred * centred).sum()))
    if norm < 2.0 * math.sqrt(centred.size):   # luma spread under 2 levels: nothing to match
        return None
    region = _crop_padded(image, x0 - search, y0 - search, width + 2 * search, height + 2 * search, 128.0)
    windows = np.lib.stride_tricks.sliding_window_view(region, (height, width))
    numerator = np.einsum("ijkl,kl->ij", windows, centred)
    count = height * width
    sums = _box_sum(region, height, width)
    spread = np.sqrt(np.maximum(_box_sum(region * region, height, width) - sums * sums / count, 0.0))
    return float((numerator / np.maximum(spread * norm, 1e-9)).max())


def _mask_stats(mask: np.ndarray) -> dict | None:
    rows = np.flatnonzero(mask.any(axis=1))
    if rows.size == 0:
        return None
    columns = np.flatnonzero(mask.any(axis=0))
    box = (int(columns[0]), int(rows[0]), int(columns[-1]) + 1, int(rows[-1]) + 1)
    try:
        ground = comfyui_forge_core.ground_row(mask, min_run=2)
    except ValueError:
        ground = box[3]
    height = max(1, ground - box[1])
    band = max(2, comfyui_forge_core.round_half_up(0.04 * height))
    try:
        stance = float(comfyui_forge_core.anchor_from_mask(mask, "stance", band_rows=band, min_run=2)[0])
    except ValueError:
        stance = (box[0] + box[2]) / 2
    head_rows = mask[box[1]:box[1] + max(1, comfyui_forge_core.round_half_up(0.35 * height))]
    ys, xs = np.nonzero(head_rows)
    top = (float(xs.mean()) + 0.5, float(ys.mean()) + 0.5 + box[1]) if xs.size else ((box[0] + box[2]) / 2, box[1])
    return {"area": int(mask.sum()), "box": box, "ground": ground, "height": height, "stance": stance, "top": top}


def _extra_area(mask: np.ndarray, min_area: int) -> int:
    """Opaque area outside the largest component (components under ``min_area`` are specks)."""
    labels, count = comfyui_forge_core.label_components(mask)
    if count <= 1:
        return 0
    areas = np.bincount(labels.ravel())[1:]
    areas = areas[areas >= min_area]
    return int(areas.sum() - areas.max()) if areas.size > 1 else 0


def _shift(mask: np.ndarray, dx: float, dy: float) -> np.ndarray:
    dx, dy = comfyui_forge_core.round_half_up(dx), comfyui_forge_core.round_half_up(dy)
    out = np.zeros_like(mask)
    height, width = mask.shape
    sx0, sx1, sy0, sy1 = max(0, -dx), min(width, width - dx), max(0, -dy), min(height, height - dy)
    if sx0 < sx1 and sy0 < sy1:
        out[sy0 + dy:sy1 + dy, sx0 + dx:sx1 + dx] = mask[sy0:sy1, sx0:sx1]
    return out


def _iou(first: np.ndarray, second: np.ndarray) -> float:
    union = int((first | second).sum())
    return float((first & second).sum()) / union if union else 0.0


def _head_box(mask: np.ndarray, stats: dict) -> tuple[int, int, int, int] | None:
    """The top of the subject: its top 35%, as wide as its top 20% plus a 10% margin (register_clip qc)."""
    x0, y0, x1, _ = stats["box"]
    height = stats["height"]
    crown = np.flatnonzero(mask[y0:y0 + max(1, comfyui_forge_core.round_half_up(0.2 * height))].any(axis=0))
    if crown.size == 0:
        return None
    margin = comfyui_forge_core.round_half_up(0.1 * (crown[-1] + 1 - crown[0]))
    hx0, hx1 = max(x0, int(crown[0]) - margin), min(x1, int(crown[-1]) + 1 + margin)
    hy0, hy1 = y0, min(mask.shape[0], y0 + max(6, comfyui_forge_core.round_half_up(0.35 * height)))
    return (hx0, hy0, hx1, hy1) if hx1 - hx0 >= 6 and hy1 - hy0 >= 6 else None


def _runs(flags: Sequence[bool]) -> list[tuple[int, int]]:
    """[start, end) of every run of True."""
    runs, start = [], None
    for index, flag in enumerate(list(flags) + [False]):
        if flag and start is None:
            start = index
        elif not flag and start is not None:
            runs.append((start, index))
            start = None
    return runs


def _rolling_median(values: Sequence[float], window: int) -> np.ndarray:
    data = np.asarray(values, np.float64)
    half = max(0, window // 2)
    return np.array([np.median(data[max(0, i - half):i + half + 1]) for i in range(data.size)])


def _scaled(template: np.ndarray, scale: float) -> tuple[np.ndarray, int, int]:
    """``template`` resized by ``scale`` (bilinear) and the offset that keeps it centred on the original."""
    if abs(scale - 1.0) < 1e-9:
        return template, 0, 0
    height, width = template.shape
    size = (max(4, comfyui_forge_core.round_half_up(width * scale)), max(4, comfyui_forge_core.round_half_up(height * scale)))
    resized = np.asarray(Image.fromarray(np.asarray(template, np.float32), "F").resize(size, Image.Resampling.BILINEAR),
                         np.float64)
    return resized, comfyui_forge_core.round_half_up((width - size[0]) / 2), comfyui_forge_core.round_half_up((height - size[1]) / 2)


def _timing_phases(steps: Sequence[float], fps: float) -> dict:
    """One-shot motion from the per-frame luma change (retime --auto-oneshot's rule): moving frames are at least
    max(0.15, 20% of the 90th-percentile step) (3-frame mean); the action runs from the first to the last moving
    frame and the longest still run inside it is the hold."""
    values = np.asarray(steps, np.float64)
    if values.size < 3:
        return {"actionSeconds": 0.0, "holdSeconds": 0.0, "onset": None, "settle": None}
    padded = np.concatenate([[values[min(1, values.size - 1)]], values, [values[-1]]])
    smooth = (padded[:-2] + padded[1:-1] + padded[2:]) / 3.0
    smooth[0] = 0.0
    active = max(0.15, 0.2 * float(np.percentile(smooth[1:], 90)))
    moving = np.flatnonzero(smooth >= active)
    if moving.size == 0:
        return {"actionSeconds": 0.0, "holdSeconds": 0.0, "onset": None, "settle": None}
    onset, settle = int(moving[0]), int(moving[-1])
    longest = run = 0
    for index in range(onset, settle + 1):
        run = run + 1 if smooth[index] < active else 0
        longest = max(longest, run)
    return {"actionSeconds": (settle - onset + 1) / fps, "holdSeconds": longest / fps, "onset": onset,
            "settle": settle, "activeStep": active}


def evaluate_take(frames: Sequence[QcFrame], reference: QcFrame, *, key: str, gates: dict, fps: float,
                  facing: str, kind: str, airborne: bool, returns_to_rest: bool, hit_tick: bool,
                  master: Any = None, timing_mode: str | None = None) -> dict:
    """Score one keyed take against the master as the job placed it (both reduced alike).

    Gates (game-opus55 take loop, recalibrated on the 2026-10-06 live run): opaque-area ratio to the master,
    feet drift (runs: the half-second rolling median, so a flight phase is not drift), identity (frame 0
    against the master; then the head against the master and frame 0 at three scales, a warning unless the
    design is lost in most frames), camera push-in or zoom, turning around (mirrored head NCC and mirrored
    silhouette), edge touch, flat background, detached extra objects, visible motion, colour (``master``:
    colour_lock.master_colours of the placed master; hues the design does not have at that height), one-shot
    timing (slow motion and long holds; warns while the set retimes one-shots, ``timing_mode`` "auto") and,
    for one-shots, the return to the start pose. Returns the QC document with per-frame numbers, the failing
    gate ids, readable reasons with frame numbers, the warnings and the longest usable window of frames that
    pass every per-frame gate."""
    count = len(frames)
    if count < 2:
        raise ValueError("a take needs at least two frames")
    ref_mask = reference.alpha > 127.5
    ref = _mask_stats(ref_mask)
    if ref is None:
        raise ValueError("the master does not land inside the video frame; check the job and the fit")
    ref_area, ref_height = max(1, ref["area"]), max(1, ref["height"])
    min_component = max(2, comfyui_forge_core.round_half_up(0.001 * ref_area))
    ref_extra = _extra_area(ref_mask, min_component)
    head = _head_box(ref_mask, ref)
    search = max(3, comfyui_forge_core.round_half_up(0.15 * ref_height))
    masks = [frame.alpha > 127.5 for frame in frames]
    stats = [_mask_stats(mask) for mask in masks]
    first = stats[0]
    if first is None:
        raise ValueError("frame 0 of the take is empty after keying")
    width = masks[0].shape[1]
    master_t = reference.luma[head[1]:head[3], head[0]:head[2]] if head else None
    frame0_t = frames[0].luma[head[1]:head[3], head[0]:head[2]] if head else None
    declared = key if key in comfyui_forge_matte.DECLARED_KEYS else tuple(int(key[i:i + 2], 16) for i in (1, 3, 5))
    declared_rgb = np.asarray(comfyui_forge_matte.DECLARED_KEYS.get(key, declared), np.float32)
    bg_tol = float(gates["background"]["tolerance"])
    start_ncc = None
    if master_t is not None:
        start_ncc = ncc_best(master_t, frames[0].luma, head[0], head[1], 3)
    id_scales = [float(value) for value in gates["identity"].get("scales", [1.0]) if abs(float(value) - 1.0) > 1e-9]
    scaled_templates = ([_scaled(template, scale) for template in (master_t, frame0_t) for scale in id_scales]
                        if head else [])

    rows: list[dict[str, Any]] = []
    previous_luma = None
    for frame, mask, st in zip(frames, masks, stats):
        row: dict[str, Any] = {"edge": frame.edge}
        row["step"] = 0.0 if previous_luma is None else float(np.abs(frame.luma - previous_luma).mean())
        previous_luma = frame.luma
        if master is not None and frame.colour is not None:
            row.update(comfyui_forge_colour_lock.foreign_drift(frame.colour, master))
        if st is None:
            row.update(empty=True, area=0.0, feet=None, lift=None, pose=1.0, iou0=0.0, extra=0.0, reach=0.0,
                       direct=0.0, mirror=0.0, ncc=None, nccMaster=None, nccMirror=None, nccScaled=None)
        else:
            row["area"] = st["area"] / ref_area
            row["feet"] = (st["ground"] - ref["ground"]) / ref_height
            row["lift"] = (ref["ground"] - st["ground"]) / ref_height
            row["height"] = st["height"] / max(1, first["height"])
            row["pose"] = float((mask ^ masks[0]).sum()) / ref_area
            row["iou0"] = _iou(mask, masks[0])
            row["extra"] = max(0, _extra_area(mask, min_component) - ref_extra) / ref_area
            if facing == "left":
                reach = first["box"][0] - st["box"][0]
            elif facing == "right":
                reach = st["box"][2] - first["box"][2]
            else:
                reach = max(first["box"][0] - st["box"][0], st["box"][2] - first["box"][2])
            row["reach"] = reach / ref_height
            dy = st["ground"] - first["ground"]
            row["direct"] = _iou(mask, _shift(masks[0], st["stance"] - first["stance"], dy))
            row["mirror"] = _iou(mask, _shift(masks[0][:, ::-1], st["stance"] - (width - first["stance"]), dy))
            if head:
                shift = (comfyui_forge_core.round_half_up(st["top"][0] - first["top"][0]),
                         comfyui_forge_core.round_half_up(st["top"][1] - first["top"][1]))
                centres = {(head[0], head[1]), (head[0] + shift[0], head[1] + shift[1])}

                def best(template: np.ndarray, image: np.ndarray = frame.luma) -> float | None:
                    scores = [ncc_best(template, image, x, y, search) for x, y in centres]
                    scores = [score for score in scores if score is not None]
                    return max(scores) if scores else None

                row["ncc"] = best(frame0_t)
                row["nccMaster"] = best(master_t)
                row["nccMirror"] = best(master_t[:, ::-1])
                scores = [value for value in (row["ncc"], row["nccMaster"]) if value is not None]
                for template, dx, dy in scaled_templates:
                    for x, y in centres:
                        value = ncc_best(template, frame.luma, x + dx, y + dy, search)
                        if value is not None:
                            scores.append(value)
                row["nccScaled"] = max(scores) if scores else None
            else:
                row.update(ncc=None, nccMaster=None, nccMirror=None, nccScaled=None)
        if frame.raw is not None:
            covered = comfyui_forge_core.dilate_square(frame.alpha > 2.0, 2)
            background = ~covered
            pixels = int(background.sum())
            raw8 = np.clip(frame.raw + 0.5, 0, 255).astype(np.uint8)
            estimate, _info = comfyui_forge_matte.estimate_key(raw8, declared, ring=1)
            if pixels:
                distance = np.sqrt(((frame.raw[background] - estimate) ** 2).sum(axis=-1))
                row["bg"] = float((distance > bg_tol).sum()) / pixels
            else:
                row["bg"] = 0.0
            row["keyDrift"] = float(np.sqrt(((estimate - declared_rgb) ** 2).sum()))
        rows.append(row)

    gate_results: dict[str, dict[str, Any]] = {}
    failures: list[str] = []
    reasons: list[str] = []
    warnings: list[str] = []
    bad: dict[str, list[bool]] = {}

    def record(gate: str, status: str, value: Any, threshold: Any, frames_bad: Sequence[int] = (),
               reason: str | None = None) -> None:
        gate_results[gate] = {"status": status, "value": _round(value), "threshold": _round(threshold),
                              "frames": [int(i) for i in frames_bad]}
        if status == "fail":
            failures.append(gate)
            if reason:
                reasons.append(f"{gate}: {reason}")
        elif status == "warn" and reason:
            warnings.append(f"{gate}: {reason}")

    # area ratio against the master
    area_gate = gates["area"]
    ratios = [row["area"] for row in rows]
    bad["area"] = [not (area_gate["min"] <= value <= area_gate["max"]) for value in ratios]
    median = float(np.median(ratios))
    share = sum(bad["area"]) / count
    frames_bad = [i for i, flag in enumerate(bad["area"]) if flag]
    ok = area_gate["min"] <= median <= area_gate["max"] and share <= area_gate["maxBadShare"]
    record("area", "pass" if ok else "fail", {"median": median, "min": min(ratios), "max": max(ratios)},
           [area_gate["min"], area_gate["max"]], frames_bad,
           f"opaque area {median:.2f}x the master (band {area_gate['min']}-{area_gate['max']}); out of band in "
           f"frames {_ranges(frames_bad)}")

    # feet drift (airborne actions: only the calm start and end spans; "median": the half-second rolling median,
    # so a run's flight phase is not drift while a run that wanders off the ground line still fails)
    feet_gate = gates["feet"]
    calm = max(2, comfyui_forge_core.round_half_up(0.25 * fps))
    checked = [feet_gate.get("enabled",True)] * count
    if feet_gate.get("enabled",True) and (feet_gate.get("mode") == "start-end" or airborne):
        checked = [i < calm or i >= count - calm for i in range(count)]
    drifts = [abs(row["feet"]) if row["feet"] is not None else 1.0 for row in rows]
    if feet_gate.get("mode") == "median" and not airborne:
        drifts = list(_rolling_median(drifts, max(3, comfyui_forge_core.round_half_up(0.5 * fps)) | 1))
    bad["feet"] = [check and drift > feet_gate["max"] for check, drift in zip(checked, drifts)]
    frames_bad = [i for i, flag in enumerate(bad["feet"]) if flag]
    worst = max((drift for check, drift in zip(checked, drifts) if check), default=0.0)
    record("feet", "skipped" if not feet_gate.get("enabled",True) else "fail" if len(frames_bad) > feet_gate["badFrames"] else "pass", worst, feet_gate["max"],
           frames_bad, f"feet drift up to {worst:.1%} of the body height (limit {feet_gate['max']:.0%}"
           + (", half-second median" if feet_gate.get("mode") == "median" else "") + f") in frames "
           f"{_ranges(frames_bad)}")

    # identity: frame 0 against the master (a hard gate); then the head against the master and frame 0 at the
    # gate's scales, a warning for low frames and a failure only when the design is lost in most frames
    id_gate = gates["identity"]
    scores = [row.get("nccScaled", row.get("ncc")) for row in rows]
    if start_ncc is None or all(value is None for value in scores):
        record("identity", "skipped", None, id_gate["min"])
        bad["identity"] = [False] * count
    else:
        severe = float(id_gate.get("severe", id_gate["min"]))
        severe_share = float(id_gate.get("severeShare", 0.0))
        low_frames = [i for i, value in enumerate(scores) if value is not None and value < id_gate["min"]]
        lost = [i for i, value in enumerate(scores) if value is not None and value < severe]
        low = min(value for value in scores if value is not None)
        start_ok = start_ncc >= id_gate["start"]
        if "severe" in id_gate:
            failed = not start_ok or len(lost) > severe_share * count
            flagged = set(lost)
        else:   # a plan written before the recalibration keeps its hard per-frame floor
            failed = not start_ok or len(low_frames) > id_gate["badFrames"]
            flagged = set(low_frames)
        bad["identity"] = [i in flagged for i in range(count)]
        status = "fail" if failed else ("warn" if len(low_frames) > id_gate["badFrames"] else "pass")
        if not start_ok:
            reason = f"frame 0 does not reproduce the master (head NCC {start_ncc:.2f} < {id_gate['start']})"
        elif failed:
            reason = (f"the head matches the master under {severe} in {len(lost)} of {count} frames ("
                      f"{_ranges(lost)}): the design is lost or the face is covered")
        else:
            reason = (f"the head matches the master only {low:.2f} (warning under {id_gate['min']}) in frames "
                      f"{_ranges(low_frames)}: a turned or bobbing head, or design drift; look at the sheet")
        record("identity", status, {"start": start_ncc, "min": low, "lowFrames": len(low_frames),
                                    "lostFrames": len(lost)},
               {"start": id_gate["start"], "warn": id_gate["min"], "severe": severe, "severeShare": severe_share},
               lost if failed else low_frames, reason)

    # camera push-in or zoom
    zoom_gate = gates["zoom"]
    base_area = max(1, first["area"])
    scales = [math.sqrt(max(row["area"], 0.0) * ref_area / base_area) for row in rows]
    bad["zoom"] = [False] * count
    if kind == "loop":
        window = max(5, comfyui_forge_core.round_half_up(fps))
        smooth = _rolling_median(scales, window)
        deviation = np.abs(smooth - 1.0)
        limit = zoom_gate.get("loopMax", zoom_gate["max"] * 1.25)
        over = np.flatnonzero(deviation > limit)
        if over.size:
            onset = int(over[0])
            bad["zoom"] = [i >= onset for i in range(count)]
        record("zoom", "fail" if over.size else "pass", float(deviation.max()), limit,
               [int(i) for i in over], f"camera zoom: the body scale drifts {float(deviation.max()):.0%} from "
               f"frame 0 (limit {limit:.0%}) from frame {int(over[0]) if over.size else 0}")
    elif returns_to_rest:
        span = list(range(max(1, count - max(3, comfyui_forge_core.round_half_up(0.4 * fps))), count))
        end_scale = float(np.median([scales[i] for i in span]))
        end_height = float(np.median([rows[i].get("height", 1.0) for i in span]))
        zoomed = (abs(end_scale - 1) > zoom_gate["max"] and abs(end_height - 1) > 0.75 * zoom_gate["max"]
                  and (end_scale - 1) * (end_height - 1) > 0)
        record("zoom", "fail" if zoomed else "pass", {"endScale": end_scale, "endHeight": end_height},
               zoom_gate["max"], span if zoomed else [],
               f"camera push-in: the body comes back {end_scale:.2f}x the size of frame 0 at the end (frames "
               f"{_ranges(span)})")
    else:
        record("zoom", "skipped", None, zoom_gate["max"])

    # turning around: the mirrored head matches better and the silhouette agrees
    turn_gate = gates["turn"]
    bad["turn"] = [False] * count
    if not turn_gate.get("enabled", True) or facing in ("front", "back"):
        record("turn", "skipped", None, turn_gate["margin"])
    else:
        flags = []
        for row in rows:
            direct, mirror = row.get("nccMaster"), row.get("nccMirror")
            silhouette = row["mirror"] >= row["direct"] - 0.02
            if direct is not None and mirror is not None:
                flags.append(mirror - direct > turn_gate["margin"] and silhouette)
            else:
                flags.append(row["mirror"] > row["direct"] + 0.1)
        runs = [run for run in _runs(flags) if run[1] - run[0] >= turn_gate["run"]]
        turned = sorted({i for a, b in runs for i in range(a, b)})
        bad["turn"] = [i in set(turned) for i in range(count)]
        evidence = max(((row.get("nccMirror") or 0) - (row.get("nccMaster") or 0) for row in rows), default=0.0)
        record("turn", "fail" if runs else "pass", evidence, turn_gate["margin"], turned,
               f"turned around in frames {_ranges(turned)} (the mirrored head matches {evidence:+.2f} better)")

    # edge touch at full resolution
    bad["edge"] = [row["edge"] for row in rows]
    frames_bad = [i for i, flag in enumerate(bad["edge"]) if flag]
    record("edge", "fail" if frames_bad else "pass", len(frames_bad), 0, frames_bad,
           f"the subject touches the frame edge in frames {_ranges(frames_bad)} (cut by the generator: never pad)")

    # background flatness (raw frames)
    bg_gate = gates["background"]
    if any("bg" in row for row in rows):
        values = [row.get("bg", 0.0) for row in rows]
        bad["background"] = [value > bg_gate["maxImpure"] for value in values]
        frames_bad = [i for i, flag in enumerate(bad["background"]) if flag]
        drift = max(row.get("keyDrift", 0.0) for row in rows)
        record("background", "fail" if len(frames_bad) > bg_gate["badFrames"] else "pass",
               {"worst": max(values), "keyDrift": drift}, bg_gate["maxImpure"], frames_bad,
               f"background not flat in frames {_ranges(frames_bad)} (worst {max(values):.2%} of the backdrop off "
               "the key)")
    else:
        bad["background"] = [False] * count
        record("background", "skipped", None, bg_gate["maxImpure"])

    # detached extra objects (dust, orbs, projectiles)
    extra_gate = gates["extra"]
    extras = [row["extra"] for row in rows]
    bad["extra"] = [value > extra_gate["max"] for value in extras]
    frames_bad = [i for i, flag in enumerate(bad["extra"]) if flag]
    record("extra", "fail" if len(frames_bad) > extra_gate["badFrames"] else "pass", max(extras), extra_gate["max"],
           frames_bad, f"extra objects detached from the body in frames {_ranges(frames_bad)} (worst "
           f"{max(extras):.1%} of the body area)")

    # the action happens
    motion_gate = gates["motion"]
    poses = [row["pose"] for row in rows]
    peak = float(max(poses))
    record("motion", "pass" if peak >= motion_gate["min"] else "fail", peak, motion_gate["min"], [],
           f"no visible action (peak pose change {peak:.1%} of the body area, needs {motion_gate['min']:.1%})")

    # one-shots return to the start pose
    end_gate = gates["endPose"]
    if end_gate.get("enabled", True) and returns_to_rest and kind == "oneshot":
        tail = max(row["iou0"] for row in rows[-3:])
        record("end-pose", "pass" if tail >= end_gate["min"] else "fail", tail, end_gate["min"],
               [] if tail >= end_gate["min"] else list(range(count - 3, count)),
               f"the clip does not return to the start pose (silhouette IoU {tail:.2f} with frame 0)")
    else:
        record("end-pose", "skipped", None, end_gate["min"])

    # colour: hues the design does not have at that height (bleed); region drift only warns (the lock undoes it)
    colour_gate = gates.get("colour") or BASE_GATES["colour"]
    if any("foreign" in row for row in rows):
        foreign = [float(row.get("foreign", 0.0)) for row in rows]
        drifts_c = [float(row.get("drift", 0.0)) for row in rows]
        bad["colour"] = [value > colour_gate["foreign"] for value in foreign]
        frames_bad = [i for i, flag in enumerate(bad["colour"]) if flag]
        drifted = [i for i, value in enumerate(drifts_c) if value > colour_gate["drift"]]
        bled = len(frames_bad) > colour_gate["badShare"] * count
        warned = len(drifted) > colour_gate["driftShare"] * count
        record("colour", "fail" if bled else ("warn" if warned else "pass"),
               {"foreignMax": max(foreign), "bledFrames": len(frames_bad), "driftMax": max(drifts_c),
                "driftedFrames": len(drifted)},
               {"foreign": colour_gate["foreign"], "badShare": colour_gate["badShare"],
                "drift": colour_gate["drift"], "driftShare": colour_gate["driftShare"]},
               frames_bad if bled else drifted,
               (f"colours the master does not have (bleed or tint) on more than {colour_gate['foreign']:.0%} of the "
                f"body in {len(frames_bad)} of {count} frames ({_ranges(frames_bad)})") if bled else
               (f"design colours drift (up to {max(drifts_c):.3f} OKLab) in {len(drifted)} of {count} frames "
                f"({_ranges(drifted)}); the finish's colour lock pulls them back, look at the sheet"))
        if not bled:
            bad["colour"] = [False] * count
    else:
        record("colour", "skipped", None, colour_gate["foreign"])

    # one-shot timing: the generator's slow motion and frozen holds
    timing_gate = gates.get("timing") or BASE_GATES["timing"]
    if kind == "oneshot":
        phases = _timing_phases([row["step"] for row in rows], fps)
        slow = (phases["actionSeconds"] > timing_gate["maxSeconds"]
                or phases["holdSeconds"] > timing_gate["maxHoldSeconds"])
        status = "pass" if not slow else ("warn" if timing_mode == "auto" else "fail")
        record("timing", status, {"actionSeconds": phases["actionSeconds"], "holdSeconds": phases["holdSeconds"]},
               {"maxSeconds": timing_gate["maxSeconds"], "maxHoldSeconds": timing_gate["maxHoldSeconds"]}, [],
               f"slow one-shot: {phases['actionSeconds']:.1f} s of motion (limit {timing_gate['maxSeconds']} s), "
               f"a {phases['holdSeconds']:.1f} s static hold (limit {timing_gate['maxHoldSeconds']} s)"
               + ("; the set retimes it (retime --auto-oneshot)" if timing_mode == "auto" else ""))
    else:
        record("timing", "skipped", None, timing_gate["maxSeconds"])

    # motion landmarks (take frame numbers) for retime: onset, settle, impact, cancel, takeoff, land
    threshold = max(0.01, 0.5 * motion_gate["min"])
    moving = [i for i, value in enumerate(poses) if value > threshold]
    motion: dict[str, Any] = {"peak": peak, "peakFrame": int(np.argmax(poses)),
                              "onset": moving[0] if moving else None, "settle": moving[-1] if moving else None}
    if moving and hit_tick:
        impact = max(range(moving[0], moving[-1] + 1), key=lambda i: (rows[i]["reach"], -i))
        motion["impact"] = int(impact)
        after = [i for i in range(impact + 1, moving[-1] + 1) if poses[i] < 0.5 * poses[impact]]
        motion["cancel"] = after[0] if after else None
    if airborne:
        lifted = [i for i, row in enumerate(rows) if row["lift"] is not None and row["lift"] > 0.03]
        motion["takeoff"] = lifted[0] if lifted else None
        motion["land"] = lifted[-1] + 1 if lifted and lifted[-1] + 1 < count else None

    usable = [not any(bad[name][i] for name in bad) for i in range(count)]
    window = None
    runs = sorted(_runs(usable), key=lambda run: (run[1] - run[0], -run[0]), reverse=True)
    if runs:
        a, b = runs[0]
        if kind == "loop":
            if b - a >= max(8, comfyui_forge_core.round_half_up(gates["window"]["loopSeconds"] * fps)):
                window = [a, b]
        elif moving and a <= max(0, moving[0] - 1) and b >= min(count, moving[-1] + 1):
            window = [a, b]
    per_frame = {name: [_round(row.get(name), 4) for row in rows]
                 for name in ("area", "feet", "lift", "pose", "iou0", "extra", "reach", "direct", "mirror", "ncc",
                              "nccMaster", "nccMirror", "nccScaled", "bg", "foreign", "drift", "step")}
    per_frame["edge"] = [bool(row["edge"]) for row in rows]
    per_frame["usable"] = usable
    per_frame["bad"] = {name: [i for i, flag in enumerate(flags) if flag] for name, flags in bad.items()}
    return {
        "schema": QC_SCHEMA,
        "status": "fail" if failures else "pass",
        "failures": failures,
        "reasons": reasons,
        "warnings": warnings,
        "gates": gate_results,
        "frames": count,
        "fps": _round(fps),
        "usableWindow": window,
        "usableFrames": int(sum(usable)),
        "motion": _round(motion),
        "reference": {"area": ref_area, "height": ref_height, "headBox": list(head) if head else None,
                      "search": search},
        "perFrame": per_frame,
    }


def qc_take(job_path: Path, clean_dir: Path, raw_dir: Path | None, *, key: str, gates: dict, fps: float,
            facing: str, kind: str, airborne: bool, returns_to_rest: bool, hit_tick: bool,
            timing_mode: str | None = None) -> dict:
    """Load a keyed take (video2dsprite process frames-clean and frames-raw) and the master as the job placed it
    in the video, reduce both alike and run evaluate_take (the colour gate learns the master's colours from the
    placed master)."""
    clean = _pngs(clean_dir)
    if len(clean) < 2:
        raise ValueError(f"{clean_dir.name} holds {len(clean)} keyed frames; a take needs at least two")
    raw = _pngs(raw_dir) if raw_dir is not None and raw_dir.is_dir() else []
    if raw and len(raw) != len(clean):
        raw = []
    job = comfyui_forge_register_clip.load_job(job_path)
    view = comfyui_forge_register_clip.load_master_view(job)
    with Image.open(clean[0]) as probe:
        size = probe.size
    fit = comfyui_forge_register_clip.video_fit(job.canvas, size, "auto")
    placed = comfyui_forge_register_clip.place_in_video(view, job, fit)
    box = comfyui_forge_core.subject_bbox(placed[..., 3], 127)
    if box is None:
        raise ValueError("the master does not land inside the video frame")
    factor = max(1, comfyui_forge_core.round_half_up((box[3] - box[1]) / QC_SUBJECT_PX))
    edge_px = int(gates["edge"]["px"])
    reference = qc_frame(placed, None, factor, edge_px)
    try:
        master = comfyui_forge_colour_lock.master_colours(placed)
    except comfyui_forge_colour_lock.ColourLockError:
        master = None
    frames = []
    for index, path in enumerate(clean):
        rgba = np.asarray(Image.open(path).convert("RGBA"))
        if (rgba.shape[1], rgba.shape[0]) != size:
            raise ValueError(f"{path.name} is {rgba.shape[1]}x{rgba.shape[0]}; the take is {size[0]}x{size[1]}")
        rgb = np.asarray(Image.open(raw[index]).convert("RGB")) if raw else None
        frames.append(qc_frame(rgba, rgb, factor, edge_px, colour=master is not None))
    result = evaluate_take(frames, reference, key=key, gates=gates, fps=fps, facing=facing, kind=kind,
                           airborne=airborne, returns_to_rest=returns_to_rest, hit_tick=hit_tick, master=master,
                           timing_mode=timing_mode)
    result["reduction"] = factor
    result["videoSize"] = list(size)
    result["fitApplied"] = fit.applied
    return result


# --------------------------------------------------------------------------- plan

def default_gates(action: str, preset: ActionPreset, klass: str, view: str) -> dict:
    """Geometry/QC constraints from explicit properties, never the motion id."""
    gates = json.loads(json.dumps(BASE_GATES))
    gates["motion"]["min"] = preset.min_motion
    gates["feet"]["enabled"] = preset.lock == "feet"
    if preset.airborne:
        gates["feet"]["mode"] = "start-end"
    if view in ("front", "back"):
        gates["turn"]["enabled"] = False
    if preset.kind == "loop" or not preset.returns_to_rest:
        gates["endPose"]["enabled"] = False
    return gates


def oneshot_timing(entry: dict) -> dict:
    """Explicit timing only; the motion label has no defaults."""
    if entry.get("kind") != "oneshot":
        return {"mode": "loop"}
    timing = entry.get("timing")
    if isinstance(timing, dict) and timing.get("mode") in ("auto", "source"):
        return timing
    return {"mode": "source"}




def _parse_list(text: str, allowed: Sequence[str], name: str) -> list[str]:
    items = [item.strip().lower() for item in str(text).split(",") if item.strip()]
    unknown = [item for item in items if item not in allowed]
    if not items or unknown:
        raise ValueError(f"{name} takes a comma list of {', '.join(allowed)}; got {text!r}")
    return list(dict.fromkeys(items))


def _parse_view_masters(values: Sequence[str]) -> dict[str, Path]:
    found = {}
    for value in values or []:
        view, sep, path = str(value).partition("=")
        view = view.strip().lower()
        if not sep or view not in VIEWS or not path.strip():
            raise ValueError(f"--view-master needs VIEW=master.json with VIEW one of {', '.join(VIEWS)}; got {value!r}")
        found[view] = Path(path.strip())
    return found


def _master_record(master: Master, stage: Path, view: str) -> dict:
    folder = stage / "master" / view
    folder.mkdir(parents=True)
    json_copy, png_copy = folder / "master.json", folder / master.png_path.name
    shutil.copyfile(master.json_path, json_copy)
    shutil.copyfile(master.png_path, png_copy)
    return {"json": comfyui_forge_core.file_ref(json_copy, stage), "png": comfyui_forge_core.file_ref(png_copy, stage),
            "sourceName": master.json_path.name, "name": master.name, "identityRecap": master.identity_recap,
            "facing": master.facing, "finish": master.finish, "class": master.klass, "key": master.key,
            "size": list(master.size), "subjectBox": list(master.box), "anchor": list(master.anchor),
            "area": master.area, "framing": _scrub(master.framing)}


def cmd_plan(args: argparse.Namespace) -> dict:
    """Write a new set folder: master copies, set_plan.json (and nothing else; run does the work)."""
    specification=comfyui_forge_contracts.confirmed(comfyui_forge_core.read_json(Path(args.spec)))
    final=specification['final']
    source=comfyui_forge_contracts.source(specification.get('source',{}))
    if any(a<b for a,b in zip(source['size'],final['size'])):raise ValueError('source dimensions are smaller than final cells')
    if args.duration is not None and Fraction(str(args.duration))!=Fraction(str(source['requestedSeconds'])):raise ValueError('source duration differs from confirmed specification')
    args.duration=source['requestedSeconds']
    args.fps=final['fpsRational'] if args.fps is None else args.fps
    if Fraction(str(args.fps))!=Fraction(str(final['fpsRational'])): raise ValueError('batch fps differs from confirmed specification')
    if args.canvas and prep.parse_size(args.canvas)!=tuple(final['size']): raise ValueError('canvas differs from confirmed specification')
    args.canvas='x'.join(map(str,final['size']))
    if args.canvas_anchor is None: args.canvas_anchor=f"{final['size'][0]//2},{round(final['size'][1]*0.90625)}"
    master = load_master(Path(args.master))
    library = load_library(Path(args.library) if args.library else LIBRARY_FILE)
    motions = definitions(args.motions_file)
    actions = list(motions)
    views = _parse_list(args.views, VIEWS, "--views")
    extra_masters = _parse_view_masters(args.view_master)
    masters: dict[str, Master] = {}
    for view in views:
        if view in extra_masters:
            masters[view] = load_master(extra_masters[view])
        elif view == "side" or ("side" not in views and view == views[0]):
            masters[view] = master   # --master is the side still, or the first view's when side is not planned
        else:
            raise ValueError(f"the {view} view needs its own approved still: --view-master {view}=<master.json>")
        if masters[view].key != master.key:
            raise ValueError(f"every view must share one key colour; {view} uses {masters[view].key}, the master "
                             f"{master.key}")
    finish = args.finish or master.finish
    target = args.target_height or comfyui_forge_core.round_half_up(round(final["size"][1]*0.8125))
    if target < 8:
        raise ValueError("--target-height must be at least 8 px")
    fps=_fps_fraction(args.fps)
    if fps is not None and not 0 < fps <= 100:
        raise ValueError("--fps must match the confirmed rate and be positive and <=100")
    if finish != "pixel" and (args.colors is not None or args.outline is not None):
        raise ValueError("--colors and --outline belong to the pixel finish")
    if args.colors is not None and args.palette:
        raise ValueError("--colors learns a palette; drop it when --palette is given")
    if args.colors is not None and not 2 <= args.colors <= 255:
        raise ValueError("--colors must be 2..255")
    canvas = None
    if args.canvas:
        match = re.fullmatch(r"\s*(\d+)\s*[xX]\s*(\d+)\s*", args.canvas)
        if not match or min(int(match.group(1)), int(match.group(2))) < 4:
            raise ValueError(f"--canvas must be WIDTHxHEIGHT such as 48x64, got {args.canvas!r}")
        canvas = [int(match.group(1)), int(match.group(2))]
    canvas_anchor = None
    if args.canvas_anchor:
        match = re.fullmatch(r"\s*(\d+)\s*,\s*(\d+)\s*", args.canvas_anchor)
        if not match or canvas is None:
            raise ValueError("--canvas-anchor needs X,Y and a --canvas")
        canvas_anchor = [int(match.group(1)), int(match.group(2))]
    for definition in motions.values():
        if definition['type']=='cycle' and final['frameCount']>source['frameCount']:raise ValueError('source has fewer unique frames than required for one final cycle; confirm a longer source')
        if definition['type']=='cycle' and (definition.get('keys') or definition.get('events')):
            raise ValueError('batch continuous-cycle selection does not author phase keys/events; use an explicitly authored selection in the standalone timing/finalization path')
        if args.oneshot_timing=='source' and definition.get('keys'):
            raise ValueError('source timing cannot apply target phase/hold keys; use automatic timing or remove those keys')
        if 'durationSeconds' in definition and fps is not None and (Fraction(str(definition['durationSeconds']))*fps).denominator != 1:
            raise ValueError('final duration times fps must be an integer; resolve the frame budget before planning')
    formats = ["png"]
    style = args.style or master.style or ("16-bit pixel-art" if finish == "pixel" else "HD hand-drawn 2D game-art")
    entries_spec = [(view, action) for view in views for action in actions]
    ref_action = actions[0]
    ref_view = "side" if "side" in views else views[0]
    ref_id = ref_action if ref_view == "side" else f"{ref_view}-{ref_action}"
    output = Path(args.output_dir)
    with comfyui_forge_core.staged_output(output) as stage:
        records = {view: _master_record(item, stage, view) for view, item in masters.items()}
        palette = None
        if args.palette:
            source = Path(args.palette)
            if not source.is_file():
                raise ValueError(f"--palette {source.name} does not exist")
            target_path = stage / "master" / ("palette" + source.suffix.lower())
            shutil.copyfile(source, target_path)
            palette = comfyui_forge_core.file_ref(target_path, stage)
        matte_profile = None
        if args.matte_profile:   # one keying for every clip of the character (video2dsprite.py --matte-profile)
            source = Path(args.matte_profile)
            if not source.is_file():
                raise ValueError(f"--matte-profile {source.name} does not exist")
            target_path = stage / "master" / "matte-profile.json"
            shutil.copyfile(source, target_path)
            matte_profile = comfyui_forge_core.file_ref(target_path, stage)
        plan: dict[str, Any] = {
            "schema": PLAN_SCHEMA,
            "tool": {"name": TOOL_NAME, "version": TOOL_VERSION},
            "createdAt": _now(),
            "name": master.name,
            "class": master.klass,
            "key": master.key,
            "keyRgb": list(master.key_rgb),
            "style": style,
            "pronoun": args.pronoun,
            "views": views,
            "masters": records,
            "generation": {"duration": args.duration, "candidateCount": args.candidates, "fps": 24, "frameCount": frame_count(args.duration),
                           "actualSeconds": frame_count(args.duration) / 24, "maxTakes": 1,
                           "jobs": 1, "pinLastFrame": args.pin_last, "timeoutSeconds": args.gen_timeout},
            "finish": {"mode": finish, "targetHeight": int(target), "scaleRefAction": ref_id, "palette": palette,
                       "colors": args.colors, "outline": args.outline, "canvas": canvas, "canvasAnchor": canvas_anchor,
                       "colourLock": not args.no_colour_lock},
            "matteProfile": matte_profile,
            "sourceCanvas":source.get("size",[640,640]),
            "package": {"formats": formats, "tiers": None,
                        "fps": None if fps is None else (int(fps) if fps.denominator == 1 else float(fps))},
            "library": {"name": LIBRARY_FILE.name if not args.library else Path(args.library).name,
                        "sha256": library.sha256},
            "clauses": library.clauses,
            "gatefix": library.gatefix,
            "actions": [],
        }
        for view, action in entries_spec:
            definition = motions[action]
            preset = generic_preset(definition)
            item = masters[view]
            hover = False
            pin = {"auto": preset.pin_last, "on": preset.returns_to_rest, "off": False}[args.pin_last]
            entry = {
                "id": action if view == "side" else f"{view}-{action}",
                "action": action, "view": view, "kind": preset.kind,
                "motionType": definition["type"], "movesFeet": definition.get("movesFeet",False),
                "candidateRange": definition.get("candidateRange"),
                "loopKind": preset.loop_kind,
                "gaitState": preset.gait_state, "prepareAction": preset.prepare_action,
                "retimeKind": preset.retime_kind, "placement": placement(item, preset.canvas),
                "pinLastFrame": bool(pin), "lock": "none" if hover else preset.lock, "airborne": preset.airborne,
                "hitTick": preset.hit_tick, "returnsToRest": preset.returns_to_rest,
                "motion": definition['description'],
                "negatives": definition.get('negatives',''),
                "gates": default_gates(action, preset, item.klass, view),
            }
            entry_spec={'confirmed':True,'final':comfyui_forge_animation_spec.final_spec(final['size'],
                         definition.get('durationSeconds',final['durationRational']),final['fpsRational'],definition['type'])}
            comfyui_forge_contracts.final(entry_spec['final'])
            if preset.kind=='oneshot' and entry_spec['final']['frameCount']<2:
                raise ValueError('a moving one-shot needs at least two playback slots')
            spec_path=stage/'specifications'/f"{entry['id']}.json"
            spec_path.parent.mkdir(exist_ok=True)
            comfyui_forge_core.write_json(spec_path,entry_spec)
            entry['specification']=comfyui_forge_core.file_ref(spec_path,stage)
            # All source geometry follows the confirmed source canvas at one fixed scale.
            place=entry['placement']; target_canvas=plan['sourceCanvas']
            ratio=min(target_canvas[0]/place['canvas'][0],target_canvas[1]/place['canvas'][1])
            offset=[(target_canvas[i]-place['canvas'][i]*ratio)/2 for i in range(2)]
            place['root']=[place['root'][i]*ratio+offset[i] for i in range(2)]
            place['scale']*=ratio;place['canvas']=target_canvas
            place['subjectBox']=[v*ratio+offset[i%2] for i,v in enumerate(place['subjectBox'])]
            place['margin']*=ratio
            if preset.kind == "oneshot":
                timing = {"mode":args.oneshot_timing, "durationMs":float(Fraction(str(definition.get('durationSeconds',final['durationRational'])))*1000),
                          "keys":definition.get('keys',{}), "events":definition.get('events',[])}
                entry["timing"] = timing
            entry["prompt"] = build_prompt(entry, plan, [])
            entry["lint"] = lint_findings(entry["prompt"], master.key)
            plan["actions"].append(entry)
        plan["estimate"] = {"clips": len(plan["actions"]), "maxClips": len(plan["actions"]) * 1,
                            "maxVideoSeconds": len(plan["actions"]) * 1 * args.duration,
                            "note": "local GPU work; source frames use the fixed 24 fps expression"}
        comfyui_forge_core.write_json(stage / PLAN_FILE, _scrub(plan))
    final = output.parent.resolve() / output.name
    return {"output": str(final), "metadata": str(final / PLAN_FILE), "plan": str(final / PLAN_FILE),
            "name": master.name, "finish": finish, "targetHeight": int(target),
            "actions": [entry["id"] for entry in plan["actions"]],
            "canvases": {entry["id"]: entry["placement"]["canvas"] for entry in plan["actions"]},
            "pinned": [entry["id"] for entry in plan["actions"] if entry["pinLastFrame"]],
            "maxClips": plan["estimate"]["maxClips"],
            "lintWarnings": sum(len(entry["lint"]) for entry in plan["actions"])}


# --------------------------------------------------------------------------- finishing (seam)



def _palette_image(colours: np.ndarray) -> Image.Image:
    """A P-mode palette image for Image.quantize(palette=...); unused slots repeat the first colour."""
    colours = np.asarray(colours, np.uint8).reshape(-1, 3)[:256]
    flat = np.concatenate([colours, np.repeat(colours[:1], 256 - len(colours), axis=0)]).reshape(-1)
    image = Image.new("P", (1, 1))
    image.putpalette([int(value) for value in flat])
    return image


def _load_palette(path: Path) -> np.ndarray:
    if path.suffix.lower() == ".json":
        data = comfyui_forge_core.read_json(path)
        values = data.get("colors") or data.get("colours") or data.get("palette") if isinstance(data, dict) else data
        colours = [[int(str(value).lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)] for value in values or []]
    else:
        rgba = np.asarray(comfyui_forge_core.load_rgba(path)[0])
        colours = np.unique(rgba[rgba[..., 3] > 0][:, :3], axis=0).tolist()
    if not 1 <= len(colours) <= 256:
        raise ValueError(f"palette {path.name} needs 1-256 colours; it has {len(colours)}")
    return np.asarray(colours, np.uint8)






def _tick_grid(fps: Any) -> tuple[int, int]:
    """(tick Hz, ticks per frame): the 60 Hz forge grid when a frame is a whole number of 60 Hz ticks, else the
    rate's own fraction (24 fps: 24 Hz x 1; 12.5 fps or 80 ms frames: 25 Hz x 2)."""
    rate = _fps_fraction(fps)
    per = Fraction(60) / rate
    if per.denominator == 1:
        return 60, int(per)
    return int(rate.numerator), int(rate.denominator)


def _plan_fps(plan: dict) -> Fraction | None:
    """The package frame rate of a plan (an int, a float such as 12.5, or "25/2"), or None for the clip's own."""
    value = (plan.get("package") or {}).get("fps")
    return None if value in (None, 0) else _fps_fraction(value)


# --------------------------------------------------------------------------- the set runner

_CLIP_SUFFIXES = (".mp4", ".webm", ".mov", ".m4v")


def _find_clip(media: Path) -> Path | None:
    """A clip already in the take's media folder (generated earlier, or dropped in by the user or host)."""
    if not media.is_dir():
        return None
    clips = sorted((path for path in media.iterdir() if path.is_file() and path.suffix.lower() in _CLIP_SUFFIXES),
                   key=lambda path: (path.name != "clip.mp4", path.name))
    return clips[0] if clips else None


class SetRunner:
    """set_plan.json + set_state.json: every verb after plan works through this."""

    def __init__(self, plan_path: Path):
        plan_path = Path(plan_path)
        if plan_path.is_dir():
            plan_path = plan_path / PLAN_FILE
        if not plan_path.is_file():
            raise ValueError(f"no {PLAN_FILE} at {plan_path.as_posix()}")
        self.plan_path = plan_path.resolve()
        self.root = self.plan_path.parent
        try:
            plan = comfyui_forge_core.read_json(self.plan_path)
        except ValueError as error:
            raise ValueError(f"{PLAN_FILE} is not valid JSON: {error}") from None
        if not isinstance(plan, dict) or plan.get("schema") != PLAN_SCHEMA:
            raise ValueError(f"{self.plan_path.name} is not a {PLAN_SCHEMA} document")
        self.plan = plan
        self.entries = {entry["id"]: entry for entry in plan["actions"]}
        if any(entry.get('motionType') not in TYPES for entry in self.entries.values()):
            raise ValueError('legacy motion plan: explicitly replan using three generic contracts; preserve and inspect existing job receipts before any generation')
        self.plan_sha = comfyui_forge_core.sha256_file(self.plan_path)
        self.state_path = self.root / STATE_FILE
        if self.state_path.is_file():
            state = comfyui_forge_core.read_json(self.state_path)
            if not isinstance(state, dict) or state.get("schema") != STATE_SCHEMA:
                raise ValueError(f"{STATE_FILE} is not a {STATE_SCHEMA} document")
            if state.get('plan',{}).get('sha256') != self.plan_sha:
                raise ValueError('generation plan changed after this set started; restore the plan. Use select --timing-file to revise existing take timing without generation')
            self.state = state
        else:
            self.state = {"schema": STATE_SCHEMA, "tool": {"name": TOOL_NAME, "version": TOOL_VERSION},
                          "plan": {"path": PLAN_FILE, "sha256": self.plan_sha}, "createdAt": _now(), "runs": 0,
                          "actions": {}, "review": None}
        self.notes: list[str] = []
        self.media_name = ""

    # ----------------------------------------------------------------- bookkeeping

    def rel(self, path: Path | str) -> str:
        return comfyui_forge_core.manifest_path(path, self.root)

    def save(self) -> None:
        self.state["updatedAt"] = _now()
        comfyui_forge_core.write_json(self.state_path, _scrub(self.state), no_clobber=False)

    def astate(self, ident: str) -> dict:
        if ident not in self.entries:
            raise ValueError(f"no action {ident!r} in {PLAN_FILE}; it plans {', '.join(self.entries)}")
        return self.state["actions"].setdefault(ident, {"status": "pending", "round": 1, "fixes": [], "job": None,
                                                        "takes": [], "chosen": None, "accepted": None,
                                                        "output": None, "message": None})

    def take(self, ident: str, number: int) -> dict:
        for record in self.astate(ident)["takes"]:
            if record["take"] == number:
                return record
        raise ValueError(f"{ident} has no take {number}")

    def order(self, only: Sequence[str] | None = None) -> list[str]:
        ids = [entry["id"] for entry in self.plan["actions"]]
        ref = self.plan["finish"].get("scaleRefAction")
        if ref in ids:
            ids.remove(ref)
            ids.insert(0, ref)
        if only:
            unknown = [ident for ident in only if ident not in ids]
            if unknown:
                raise ValueError(f"--actions names {unknown}, not planned (planned: {', '.join(ids)})")
            ids = [ident for ident in ids if ident in only]
        return ids

    def master(self, ident: str) -> dict:
        return self.plan["masters"][self.entries[ident]["view"]]

    def take_dir(self, ident: str, number: int) -> Path:
        return self.root / "actions" / ident / "takes" / f"t{number:02d}"

    def log_take(self, ident: str, record: dict) -> None:
        """Append the take's verdict to takes.jsonl once (an audit log; the state is the truth)."""
        if record.get("logged"):
            return
        qc = record.get("qc") or {}
        line = {"schema": TAKE_SCHEMA, "at": _now(), "action": ident, "take": record["take"],
                "round": record["round"], "status": record["status"], "failures": record.get("failures", []),
                "reasons": record.get("reasons", []), "badFrames": qc.get("badFrames", {}),
                "usableWindow": qc.get("usableWindow"), "fixesUsed": record.get("fixes", []),
                "fixNext": record.get("fixNext", []), "route": record.get("route"),
                "prompt": record.get("prompt"), "clip": record.get("clip"), "message": record.get("message")}
        with open(self.root / TAKES_FILE, "a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(_scrub(line), ensure_ascii=False, allow_nan=False) + "\n")
        record["logged"] = True

    def stage(self, record: dict, name: str, make: Callable[[Path], dict]) -> dict:
        """Run one tool step into <take>/<name> unless the state already records it (resume). A folder the
        state does not know (a crash between publish and save) is kept aside as <name>.orphan-N."""
        stages = record.setdefault("stages", {})
        out = self.root / record["dir"] / name
        done = stages.get(name)
        if done and out.exists():
            if name!='final-review':
                expected=done.get('contentSha256')
                current={p.relative_to(out).as_posix():comfyui_forge_core.sha256_file(p) for p in out.rglob('*') if p.is_file()}
                if not expected or current!=expected:
                    raise ValueError('cached '+name+' is changed or lacks an integrity snapshot; use rebuild --from-stage '+name+' on this take')
            return done
        if os.path.lexists(out):
            self.notes.append(f"kept an unrecorded {self.rel(out)} aside as {_move_aside(out).name}")
        started = time.perf_counter()
        result = make(out)
        result["dir"] = self.rel(out)
        result["seconds"] = round(time.perf_counter() - started, 2)
        if name!='final-review':result['contentSha256']={p.relative_to(out).as_posix():comfyui_forge_core.sha256_file(p) for p in out.rglob('*') if p.is_file()}
        stages[name] = _scrub(result)
        self.save()
        return stages[name]

    def check_masters(self) -> None:
        for view, record in self.plan["masters"].items():
            for role in ("json", "png"):
                path = self.root / record[role]["path"]
                if not path.is_file() or comfyui_forge_core.sha256_file(path) != record[role]["sha256"]:
                    raise ValueError(f"the {view} master {record[role]['path']} is missing or changed since the plan; "
                                     "plan a new set for a new master")

        for ref in (self.plan.get('matteProfile'),self.plan.get('finish',{}).get('palette')):
            if ref and comfyui_forge_core.sha256_file(self.root/ref['path'])!=ref['sha256']:
                raise ValueError('a frozen matte profile or palette changed; restore the planned input')

    # ----------------------------------------------------------------- jobs and prompts

    def ensure_job(self, ident: str) -> dict:
        st = self.astate(ident)
        out = self.root / "actions" / ident / "job"
        if st.get('job'):
            path=out/'registration_job.json'
            if not path.is_file() or comfyui_forge_core.sha256_file(path)!=st['job']['sha256']:
                raise ValueError('prepared job is missing or changed; restore its frozen metadata before continuing')
            prepared=comfyui_forge_core.read_json(path)
            for role in ('input','master','prompt'):
                ref=prepared.get(role)
                if ref and comfyui_forge_core.sha256_file(out/ref['path'])!=ref['sha256']:
                    raise ValueError('prepared '+role+' changed; restore the frozen input before continuing')
            self.entries[ident]['generationKey']=prepared['keyColor']
            return st['job']
        if os.path.lexists(out):
            self.notes.append(f"kept an unrecorded {self.rel(out)} aside as {_move_aside(out).name}")
        entry, master = self.entries[ident], self.master(ident)
        place = entry["placement"]
        out.parent.mkdir(parents=True, exist_ok=True)
        prompt_file = out.parent / f".prompt-{os.getpid()}.txt"
        prompt_file.write_bytes(build_prompt(entry, self.plan, []).encode("utf-8"))
        args = ["prepare", "--master", self.root / master["png"]["path"], "--motion-type", entry["motionType"], "--description", entry["motion"],
                "--output-dir", out, "--canvas", "{},{}".format(*place["canvas"]),
                "--root", "{!r},{!r}".format(*place["root"]), "--scale", repr(place["scale"]),
                "--anchor", "{!r},{!r}".format(*place["anchor"]), "--key", self.plan["key"],
                "--master-key", "auto", "--margin", place["margin"],
                "--action-padding", ",".join(str(v) for v in place["padding"]),
                "--duration", self.plan["generation"]["duration"], "--facing", master["facing"],
                "--candidates", self.plan["generation"].get("candidateCount", 3),
                "--subject", master["name"], "--prompt-file", prompt_file]
        try:
            summary, warnings = run_tool(SCRIPTS["prepare_i2v_input"], args)
        finally:
            prompt_file.unlink(missing_ok=True)
        job = out / 'registration_job.json'
        selected_key=comfyui_forge_core.read_json(job)['keyColor']
        entry['generationKey']=selected_key
        st['generationKey']=selected_key
        actual_prompt=build_prompt(entry,self.plan,[])
        (out/'prompt.txt').write_text(actual_prompt,encoding='utf-8')
        preparation=comfyui_forge_core.read_json(job)
        preparation['prompt']['sha256']=comfyui_forge_core.sha256_file(out/'prompt.txt')
        comfyui_forge_core.write_json(job,preparation,no_clobber=False)
        st["job"] = {"dir": self.rel(out), "job": self.rel(job), "sha256": comfyui_forge_core.sha256_file(job),
                     "input": self.rel(out / "input.png"), "referenceScale": summary.get("referenceScale"),
                     "keyColor": summary.get("keyColor"), "padding": summary.get("padding"),
                     "warnings": len(warnings)}
        self.save()
        return st["job"]

    def open_take(self, ident: str) -> dict:
        """The take to work on: the unfinished one of this round, or a new take with the prompt and every fix."""
        st = self.astate(ident)
        last = st["takes"][-1] if st["takes"] else None
        if last and last["round"] == st["round"] and last["status"] in ("open", "generated", "error"):
            return last
        number = len(st["takes"]) + 1
        folder = self.take_dir(ident, number)
        folder.mkdir(parents=True, exist_ok=True)
        prompt = build_prompt(self.entries[ident], self.plan, [fix["text"] for fix in st["fixes"]])
        payload = prompt.encode("utf-8")
        path = folder / "prompt.txt"
        if path.exists() and path.read_bytes() != payload:
            _move_aside(path)
        if not path.exists():
            with open(path, "xb") as stream:
                stream.write(payload)
        record = {"take": number, "round": st["round"], "dir": self.rel(folder), "status": "open", "createdAt": _now(),
                  "prompt": {"path": self.rel(path), "sha256": comfyui_forge_core.sha256_bytes(payload)},
                  "fixes": [fix["id"] for fix in st["fixes"]], "lint": lint_findings(prompt, self.plan["key"]),
                  "stages": {}}
        st["takes"].append(record)
        st["status"] = "generating"
        self.save()
        return record

    # ----------------------------------------------------------------- generation

    def generate(self, ident: str, record: dict, timeout: float) -> dict:
        """Resume tracked jobs before adopting supplied clips; never resubmit a failed attempt."""
        import comfyui_forge_media
        import comfyui_forge_av
        from types import SimpleNamespace

        folder = self.root / record["dir"]
        media = folder / "media"
        receipt = media / "job.json"
        try:
            if receipt.is_file():
                summary = comfyui_forge_media.resume(media, timeout)
                return {"status": "ok", "route": "local:comfyui", "artifact": Path(summary["artifact"]),
                        "summary": summary, "pinned": summary.get("lastFrameUsed"), "pinNote": None,"submittedNew":False}
            clip = _find_clip(media)
            if clip is not None:
                comfyui_forge_av.probe(clip)
                return {"status": "ok", "route": "supplied", "artifact": clip,
                        "adopted": True, "pinned": None}
            if media.exists():
                raise ValueError("existing media folder has no valid receipt or supplied clip; inspect it before retrying")
            job = self.root / self.astate(ident)["job"]["dir"]
            pin = bool(self.entries[ident]["pinLastFrame"])
            args = SimpleNamespace(reference=str(job / "input.png"), prompt_file=str(folder / "prompt.txt"),
                                   duration=float(self.plan["generation"]["duration"]),
                                   last_frame=str(job / "input.png") if pin else None,
                                   out_dir=str(media), timeout=timeout, dry_run=False)
            binding = folder / "submission-input.json"
            if not binding.exists():
                comfyui_forge_core.write_json(binding, {"input": {"path": str(Path(args.reference).resolve()),
                                                          "sha256": comfyui_forge_core.sha256_file(args.reference)},
                                                 "prompt": {"path": "prompt.txt", "sha256": comfyui_forge_core.sha256_file(args.prompt_file)},
                                                 "candidateCount": self.plan["generation"].get("candidateCount", 3)})
            args.preparation = str(binding)
            summary = comfyui_forge_media.execute(args)
            return {"status": "ok", "route": "local:comfyui", "artifact": Path(summary["artifact"]),
                    "summary": summary, "pinned": pin, "pinNote": None,"submittedNew":True}
        except (comfyui_forge_media.ComfyError, comfyui_forge_av.ForgeAVError, OSError, ValueError, KeyError, TypeError) as exc:
            return {"status": "error", "message": str(exc)}

    def record_generation(self, ident: str, record: dict, result: dict) -> str:
        st = self.astate(ident)
        folder = self.root / record["dir"]
        if result["status"] == "ok":
            clip = Path(result["artifact"])
            record["clip"] = {"path": self.rel(clip), "sha256": comfyui_forge_core.sha256_file(clip)}
            record["route"] = _scrub(result.get("route")) or "unknown"
            record["pinnedLastFrame"] = result.get("pinned")
            if result.get("pinNote"):
                record["pinNote"] = result["pinNote"]
            route_file = folder / "route.json"
            if not route_file.exists():
                _write_new_json(route_file, _scrub({
                    "schema": "video2dsprite.sprite_set_route.v1", "action": ident, "take": record["take"],
                    "provider": self.media_name if not result.get("adopted") else "adopted clip",
                    "route": result.get("route"), "clip": record["clip"], "pinnedLastFrame": result.get("pinned"),
                    "pinNote": result.get("pinNote"), "summary": result.get("summary")}))
            record["status"], record["message"] = "generated", None
            self.save()
            return "ok"
        record["message"] = result["message"]
        record["status"] = "error"
        st["status"] = "error"
        st["message"] = f"take {record['take']}: {result['message']} (resume this take after resolving its receipt; no replacement task was submitted)"
        self.log_take(ident, record)
        self.save()
        return "error"

    # ----------------------------------------------------------------- per-take tools

    def run_key(self, ident: str, record: dict, out: Path) -> dict:
        job = self.root / self.astate(ident)["job"]["dir"]
        args = ["process", "--video", self.root / record["clip"]["path"], "--output-dir", out, "--matte", "soft",
                "--reference", job / "master.png", "--key", self.entries[ident]["generationKey"], "--skip-sampling",
                "--name", f"{ident}-t{record['take']:02d}"]
        if self.plan.get("matteProfile"):
            args += ["--matte-profile", self.root / self.plan["matteProfile"]["path"]]
        summary, warnings = run_tool(SCRIPTS["video2dsprite"], args, label="comfyui_forge_video2dsprite.py process")
        probe = (comfyui_forge_core.read_json(out / "pipeline-meta.json").get("probe") or {})
        return {"frames": summary.get("frames"), "fps": probe.get("fps_rational") or "24/1",
                "size": [probe.get("width"), probe.get("height")], "matte": summary.get("matte"),
                "warnings": warnings[:6]}

    def run_qc(self, ident: str, record: dict) -> dict:
        path = self.root / record["dir"] / "qc.json"
        if record.get("qc") and path.is_file():
            return record["qc"]
        if os.path.lexists(path):
            _move_aside(path)
        entry, st = self.entries[ident], self.astate(ident)
        keyed = self.root / record["stages"]["keyed"]["dir"]
        document = qc_take(self.root / st["job"]["job"], keyed / "frames-clean", keyed / "frames-raw",
                           key=entry["generationKey"], gates=entry["gates"], fps=_fps_value(record["stages"]["keyed"]["fps"]),
                           facing=self.master(ident)["facing"], kind=entry["kind"], airborne=entry["airborne"],
                           returns_to_rest=entry["returnsToRest"], hit_tick=entry["hitTick"],
                           timing_mode=oneshot_timing(entry).get("mode"))
        document.update({"action": ident, "take": record["take"], "clip": record.get("clip"),
                         "job": {"path": st["job"]["job"], "sha256": st["job"]["sha256"]}})
        _write_new_json(path, _scrub(document))
        record["qc"] = {"file": self.rel(path), "status": document["status"], "failures": document["failures"],
                        "reasons": document["reasons"], "warnings": document.get("warnings", []),
                        "usableWindow": document["usableWindow"],
                        "usableFrames": document["usableFrames"], "frames": document["frames"],
                        "motion": document["motion"], "badFrames": document["perFrame"]["bad"],
                        "gates": {name: {"status": gate["status"], "value": gate["value"]}
                                  for name, gate in document["gates"].items()}}
        self.save()
        return record["qc"]

    def run_register(self, ident: str, record: dict, out: Path, window: Sequence[int] | None) -> dict:
        entry, st = self.entries[ident], self.astate(ident)
        keyed = self.root / record["stages"]["keyed"]["dir"]
        height = self.master(ident)["size"][1]
        args = ["apply", "--job", self.root / st["job"]["job"], "--frames", keyed / "frames-clean",
                "--output-dir", out, "--clip", ident, "--max-anchor-error", f"{max(2.0, 0.004 * height):.3g}",
                "--max-scale-error", "0.04"]
        if entry["lock"] == "feet":
            args += ["--lock", "feet"]
        if window:
            args += ["--range", f"{window[0]}:{window[1]}"]
        summary, warnings = run_tool(SCRIPTS["register_clip"], args, label="comfyui_forge_register_clip.py apply")
        return {"frames": summary["frames"], "sourceSize": summary["sourceSize"],
                "sourceAnchor": summary["sourceAnchor"], "fit": summary.get("fitApplied"),
                "range": list(window) if window else None,
                "registration": self.rel(out / "registration.json"), "warnings": warnings[:6]}

    def run_motion(self, ident: str, record: dict, out: Path, tag: str, window: Sequence[int] | None) -> dict:
        """Loops: gait_loop select. One-shots: retime over the motion window with ticks, explicit reviewed keys and events."""
        entry = self.entries[ident]
        registered = record["stages"]["registered" + tag]
        frames = self.root / registered["dir"] / "frames"
        fps_text = record["stages"]["keyed"]["fps"]
        if entry['kind']=='loop' and record.get('candidateRange'):
            first,last=record['candidateRange']
            clip=comfyui_forge_gait_loop.load_clip(frames,comfyui_forge_gait_loop.parse_fps(fps_text))
            if not 0<=first<last<=clip.count: raise ValueError('candidateRange is outside the source')
            indices=list(range(first,last));durations=comfyui_forge_gait_loop.source_durations(last-first,clip.fps)
            with comfyui_forge_core.staged_output(out) as stage:
                selection=comfyui_forge_gait_loop.build_selection(clip,stage,indices,durations,policy='cycle',method='reviewed forward candidate',
                    review='inspect moving phase and velocity',window=(first,last),extra={'motionType':'cycle'})
                comfyui_forge_core.write_json(stage/'selection.json',selection)
            return {'selection':self.rel(out/'selection.json'),'frames':len(indices),'start':first,'endExclusive':last,'policy':'cycle'}
        if entry["kind"] == "loop":
            args = ["select", "--frames-dir", frames, "--fps", fps_text, "--output-dir", out,
                    "--kind", entry["loopKind"]]
            summary, _ = run_tool(SCRIPTS["gait_loop"], args, label="comfyui_forge_gait_loop.py select")
            selection = comfyui_forge_core.read_json(out / "selection.json")
            return {"tool": "gait_loop select", "selection": self.rel(out / "selection.json"),
                    "policy": summary["policy"], "start": summary["start"], "endExclusive": summary["endExclusive"],
                    "frames": summary["frames"], "confidence": summary.get("confidence"),
                    "durationMs": int(sum(selection["durations_ms"])), "fps": selection.get("fps")}
        motion = record["qc"]["motion"]
        offset = window[0] if window else 0
        count = int(registered["frames"])
        timing = record.get("timingOverride") or oneshot_timing(entry)
        if timing.get("mode") == "auto":
            return self.run_auto_oneshot(ident, record, out, frames, fps_text, motion, offset, count, timing)
        if record.get('candidateClipSha256') and record['candidateClipSha256']!=record['clip']['sha256']:
            raise ValueError('candidate belongs to a different source take')
        candidate=record.get('candidateRange')
        if not isinstance(candidate,list) or len(candidate)!=2 or any(type(v) is not int for v in candidate):
            raise ValueError('one-shot processing requires a reviewed candidateRange [start,endExclusive]')
        start,end=candidate[0]-offset,candidate[1]-offset
        if not 0 <= start < end <= count: raise ValueError('candidateRange is outside registered frames')
        if timing.get('keys'):raise ValueError('source timing cannot silently discard authored phase keys; use auto timing')
        args = ['--frames-dir',frames,'--fps',fps_text,'--output-dir',out,'--kind',entry['retimeKind'],
                '--range',f'{start}:{end}','--policy','oneshot']
        for event in timing.get('events',[]):
            frame=event['source']-offset
            if not start<=frame<end:raise ValueError('event source is outside candidateRange')
            args+=['--event-source',f"{event['name']}={frame}"]
        summary, _ = run_tool(SCRIPTS["retime"], args, label="comfyui_forge_retime.py")
        selection = comfyui_forge_core.read_json(out / "selection.json")
        return {"tool": "retime", "selection": self.rel(out / "selection.json"), "policy": "oneshot",
                "start": start, "endExclusive": end, "frames": summary["frames"], "durationMs": summary["durationMs"],
                "events": selection.get("events", [])}

    def run_auto_oneshot(self, ident: str, record: dict, out: Path, frames: Path, fps_text: str, motion: dict,
                         offset: int, count: int, timing: dict) -> dict:
        """comfyui_forge_retime.py --auto-oneshot over the registered frames: the game length and keys from the plan's timing,
        the key source frames and events explicitly reviewed within the selected candidate."""
        entry = self.entries[ident]
        source = _fps_fraction(fps_text)
        target = _plan_fps(self.plan)
        rate = target or source
        keys = timing.get("keys") or {}
        if record.get('candidateClipSha256') and record['candidateClipSha256']!=record['clip']['sha256']:
            raise ValueError('candidate belongs to a different source take')
        candidate=record.get('candidateRange')
        if not isinstance(candidate,list) or len(candidate)!=2 or any(type(v) is not int for v in candidate):
            raise ValueError('review and set candidateRange [start,endExclusive] for ONE complete demonstration before retiming')
        first,last=candidate[0]-offset,candidate[1]-offset
        if not 0 <= first < last <= count:
            raise ValueError('candidateRange lies outside registered frames')
        args = ["--frames-dir", frames, "--fps", fps_text, "--output-dir", out, "--kind", entry['motionType'],
                "--range", f"{first}:{last}", "--auto-oneshot", "--duration-ms", str(timing['durationMs']),
                "--output-fps", f"{rate.numerator}/{rate.denominator}"]
        used=[]
        for name,spec in sorted(keys.items(),key=lambda item:float(item[1].get('at',0))):
            frame=spec.get('source')
            if type(frame) is not int or not first <= frame-offset < last:
                raise ValueError('each reviewed timing key needs an explicit source inside candidateRange')
            hold=spec.get('holdMs',0)
            args += ['--key',f"{name}={frame-offset}@{spec['at']}"+(f'+{hold}' if hold else '')]
            used.append(name)
        for event in timing.get('events',[]):
            frame=event.get('source')
            if type(frame) is not int or not first <= frame-offset < last:
                raise ValueError('event source must lie inside candidateRange')
            args += ['--event-source',f"{event['name']}={frame-offset}"]
        summary, _ = run_tool(SCRIPTS["retime"], args, label="comfyui_forge_retime.py --auto-oneshot")
        selection = comfyui_forge_core.read_json(out / "selection.json")
        hz, _per = _tick_grid(rate)
        return {"tool": "retime --auto-oneshot", "selection": self.rel(out / "selection.json"), "policy": "oneshot",
                "start": first, "endExclusive": last, "frames": summary["frames"], "durationMs": summary["durationMs"],
                "events": selection.get("events", []),
                "timing": {"durationMs": float(timing["durationMs"]), "keys": used,
                           "auto": summary.get("auto")}}




    # ----------------------------------------------------------------- evaluation and retakes


    def evaluate(self, ident, record):
        st=self.astate(ident)
        try:
            self.verify_clip(record)
            self.stage(record,'keyed',lambda out:self.run_key(ident,record,out))
            if not record.get('qc'): self.run_qc(ident,record)
            self.stage(record,'registered',lambda out:self.run_register(ident,record,out,None))
            self.stage(record,'motion',lambda out:self.run_motion(ident,record,out,'',None))
            record.update(status='needs-review',failures=record.get('qc',{}).get('failures',[]),reasons=record.get('qc',{}).get('reasons',[]))
            st['chosen']={'take':record['take'],'window':None,'tag':'','reason':'one selected candidate; final review required'}
            st['status']='chosen';st['message']=None
        except (ToolFailure,ValueError,OSError) as error:
            record['status']='blocked'
            st['chosen']=None;st['status']='blocked';st['message']=str(error)
        self.log_take(ident,record);self.save()



    # ----------------------------------------------------------------- finishing, packaging, verify

    def scale_ref_file(self, ident: str) -> Path | None:
        ref = self.plan["finish"].get("scaleRefAction")
        if not ref or ref == ident:
            return None
        chosen = (self.state["actions"].get(ref) or {}).get("chosen")
        if chosen:
            record = self.take(ref, chosen["take"])
            finished = record.get("stages", {}).get("finished" + chosen.get("tag", ""))
            if finished and finished.get("scaleRef"):
                path = self.root / finished["scaleRef"]
                if path.is_file():
                    return path
        self.notes.append(f"{ident}: the scale reference {ref} has no finished frames; {ident} uses its own rest pose")
        return None

    def ref_palette_file(self, ident: str) -> Path | None:
        """Pixel sets without a plan palette: the palette the scale-reference action learned (palette.json in its
        finish folder), so every action of the character shares one palette."""
        ref = self.plan["finish"].get("scaleRefAction")
        if not ref or ref == ident:
            return None
        chosen = (self.state["actions"].get(ref) or {}).get("chosen")
        if not chosen:
            return None
        finished = self.take(ref, chosen["take"]).get("stages", {}).get("finished" + chosen.get("tag", ""))
        if not finished:
            return None
        path = self.root / finished["dir"] / "palette.json"
        return path if path.is_file() else None

    def run_finish(self, ident: str, record: dict, out: Path, tag: str) -> dict:
        finish = self.plan["finish"]
        frames = self.root / record["stages"]["registered" + tag]["dir"] / "frames"
        scale_ref = self.scale_ref_file(ident)
        palette = self.root / finish["palette"]["path"] if finish.get("palette") else None
        pixel = finish["mode"] == "pixel"
        shared = self.ref_palette_file(ident) if pixel and palette is None else None
        lock = None
        if finish.get("colourLock", True):
            master = self.root / self.astate(ident)["job"]["dir"] / "master.png"
            if master.is_file():
                with Image.open(master) as image:   # the keyed job master; an opaque one cannot be a lock master
                    keyed = image.convert("RGBA").getchannel("A").getextrema()[0] < 255
                lock = master if keyed else None
                if not keyed:
                    self.notes.append(f"{ident}: the job master has no transparency; finished without the colour lock")
        script,name=FINISH_SCRIPT,'comfyui_forge_finish_frames.py'
        args = [finish["mode"], "--frames", frames, "--output-dir", out]
        if scale_ref is not None:   # finish_frames.py takes --scale-ref OR --target-height, never both
            args += ["--scale-ref", scale_ref]
        else:
            args += ["--target-height", finish["targetHeight"]]
        if palette is not None or shared is not None:
            args += ["--palette", palette or shared]
        elif pixel and finish.get("colors"):
            args += ["--colors", int(finish["colors"])]
        if pixel and finish.get("outline"):
            args += ["--outline", finish["outline"]]
        if finish.get("canvas"):
            args += ["--canvas", "{}x{}".format(*finish["canvas"])]
            if finish.get("canvasAnchor"):
                args += ["--canvas-anchor", "{},{}".format(*finish["canvasAnchor"])]
        if lock is not None:
            args += ["--colour-lock", lock]
        if self.entries[ident]["kind"] == "oneshot":
            args += ["--loop-policy", "oneshot"]
        summary, _ = run_tool(script, args, label=name)
        frames_dir = None
        for key in ("framesDir", "frames_dir"):
            if isinstance(summary.get(key), str) and Path(summary[key]).is_dir():
                frames_dir = Path(summary[key])
        if frames_dir is None:
            frames_dir = out / "frames" if (out / "frames").is_dir() and _pngs(out / "frames") else out
        files = _pngs(frames_dir)
        if not files:
            raise ValueError(f"{name} wrote no PNG frames into {self.rel(out)}")
        with Image.open(files[0]) as image:
            size = list(image.size)
        anchor = summary.get("anchor") or summary.get("sourceAnchor")
        if not (isinstance(anchor, (list, tuple)) and len(anchor) == 2):
            rest = np.asarray(comfyui_forge_core.load_rgba(files[0])[0])[..., 3] > 127
            stats = _mask_stats(rest)
            band = max(2, comfyui_forge_core.round_half_up(0.04 * stats["height"]))
            anchor = list(comfyui_forge_core.anchor_from_mask(rest, "stance", band_rows=band, min_run=2))
        reference = next((summary[key] for key in ("scale_ref", "scaleRef", "metadata")
                          if isinstance(summary.get(key), str) and Path(summary[key]).is_file()), None)
        return {"finisher": name, "mode": finish["mode"], "targetHeight": finish["targetHeight"],
                "frames": len(files), "framesDir": self.rel(frames_dir), "size": size,
                "anchor": [float(anchor[0]), float(anchor[1])], "scale": summary.get("scale"),
                "scaleRef": self.rel(reference) if reference else None,
                "scaleRefFrom": self.rel(scale_ref) if scale_ref else None}




    def verify_clip(self, record: dict) -> None:
        """Check the frozen input even when later processing stages already exist."""
        clip = record.get("clip") or {}
        path = self.root / clip.get("path", "")
        if not path.is_file() or comfyui_forge_core.sha256_file(path) != clip.get("sha256"):
            raise ValueError("source clip is missing or its checksum changed; inspect this take before continuing")

    def post_process(self,ident):
        st=self.astate(ident);chosen=st.get('chosen')
        if not chosen:return
        record=self.take(ident,chosen['take'])
        if st.get('status')=='done':return
        try:
            self.verify_clip(record)
            self.stage(record,'finished',lambda out:self.run_finish(ident,record,out,''))
            spec_ref=self.entries[ident]['specification'];spec_path=self.root/spec_ref['path']
            if comfyui_forge_core.sha256_file(spec_path)!=spec_ref['sha256']:raise ValueError('confirmed specification changed')
            review=self.stage(record,'final-review',lambda out:self.prepare_final(ident,record,out,spec_path))
            work=self.root/review['dir']
            acceptance=st.get('accepted')
            if not acceptance:
                st['status']='needs-review';st['message']='inspect final preview and light/dark contact sheet, then accept with a review note'
            else:
                if comfyui_forge_core.sha256_file(work/'review.json')!=acceptance['reviewSha256']:
                    prior=comfyui_forge_core.read_json(work/'review.json')
                    if prior.get('acceptedReviewSha256')!=acceptance['reviewSha256']:
                        raise ValueError('final review changed since acceptance; inspect and accept again')
                output=self.root/'outputs'/ident/f"take-{record['take']}-review-{record.get('reviewRevision',1)}"
                delivered=comfyui_forge_finalize_animation.approve(work,output,acceptance['note'])
                st['output']={'take':record['take'],'package':self.rel(output),'files':delivered['files'],'outputSha256':delivered['outputSha256']}
                st['status']='done';st['message']=None
        except (ToolFailure,ValueError,OSError) as error:
            st['status']='blocked';st['message']=str(error)
        self.save()

    def prepare_final(self,ident,record,out,spec_path):
        finished=self.root/record['stages']['finished']['dir']
        selection=self.root/record['stages']['motion']['selection']
        receipt=comfyui_forge_finalize_animation.prepare(finished,selection,spec_path,self.root/record['clip']['path'],out)
        if record.get('qc'):
            qc_path=self.root/record['qc']['file']
            receipt['qualityChecks']=comfyui_forge_core.read_json(qc_path)
            receipt['inputs'].append({'path':str(qc_path),'sha256':comfyui_forge_core.sha256_file(qc_path)})
            comfyui_forge_core.write_json(out/'review.json',receipt,no_clobber=False)
        return {'review':str(out/'review.json'),'sourceIndices':receipt['sourceIndices']}

    # ----------------------------------------------------------------- the whole run

    def verify_delivery(self,ident):
        st=self.astate(ident);output=st.get('output') or {};folder=self.root/output.get('package','')
        expected=output.get('outputSha256')
        if expected is None:
            chosen=st.get('chosen') or {};record=self.take(ident,chosen.get('take'))
            review=record.get('stages',{}).get('final-review',{})
            receipt=self.root/review.get('dir','')/'delivery.json'
            expected=comfyui_forge_core.read_json(receipt).get('outputSha256') if receipt.is_file() else None
        actual={p.relative_to(folder).as_posix():comfyui_forge_core.sha256_file(p) for p in folder.rglob('*') if p.is_file()} if folder.is_dir() else {}
        if not expected or actual!=expected:raise ValueError('completed delivery is missing or changed; inspect the retained delivery before continuing')

    def run(self,only=None,*,timeout=1200):
        self.check_masters();self.media_name='local:comfyui';order=self.order(only);generated=0
        for ident in order:
            st=self.astate(ident)
            try:
                if st.get('status')=='done':self.verify_delivery(ident);continue
                ref=self.entries[ident].get('specification')
                if ref and comfyui_forge_core.sha256_file(self.root/ref['path'])!=ref['sha256']:raise ValueError('confirmed specification changed')
                self.ensure_job(ident)
                last=st['takes'][-1] if st['takes'] else None;selected=st.get('selectedTake')
                record=self.take(ident,selected) if selected is not None else (last if last and last.get('round')==st['round'] else self.open_take(ident))
                if not record.get('clip'):
                    result=self.generate(ident,record,timeout)
                    if self.record_generation(ident,record,result)=='error':continue
                    generated+=int(result.get('submittedNew',False))
                self.evaluate(ident,record);self.post_process(ident)
            except (ToolFailure,ValueError,OSError) as error:
                st['status']='blocked';st['message']=str(error);self.save()
        return self.summary(order,generated)

    def summary(self, order: Sequence[str], generated: int) -> tuple[dict, int]:
        actions = {}
        for ident in order:
            st = self.astate(ident)
            actions[ident] = {"status": st["status"], "takes": len(st["takes"]),
                              "chosen": (st.get("chosen") or {}).get("take"),
                              "accepted": bool(st.get("accepted")),
                              "package": (st.get("output") or {}).get("package"),
                              "message": st.get("message")}
        statuses = {item["status"] for item in actions.values()}
        if statuses <= {"done"}:
            status, code = "complete", 0
        elif statuses <= {"done", "done-warn"}:
            status, code = "complete-with-warnings", 0
        else:
            status, code = "incomplete", 1
        summary = {"output": str(self.root), "plan": str(self.plan_path), "state": str(self.state_path),
                   "status": status, "generated": generated, "media": self.media_name,
                   "finisher": "comfyui_forge_finish_frames.py", "actions": actions,
                   "needsReview": [ident for ident, item in actions.items() if not item["accepted"]],
                   "notes": [_ascii(note) for note in self.notes[:12]]}
        return summary, code


# --------------------------------------------------------------------------- review sheets

def cmd_review(args):
    runner=SetRunner(Path(args.plan));items=[]
    for ident in runner.order():
        st=runner.astate(ident)
        if not st.get('chosen'):continue
        record=runner.take(ident,st['chosen']['take'])
        stage=record.get('stages',{}).get('final-review')
        if stage:
            work=runner.root/stage['dir']
            items.append({'id':ident,'take':record['take'],'preview':str(work/'preview.gif'),
                          'contact':str(work/'review-contact.png'),'review':str(work/'review.json'),'qualityChecks':record.get('qc',{})})
    return {'status':'needs-review','items':items,'instruction':'inspect the actual final animation, contract, timing and light/dark alpha edges before accepting'}


# --------------------------------------------------------------------------- accept, retake, report

def _parse_window(text: str | None) -> list[int] | None:
    if not text:
        return None
    match = re.fullmatch(r"\s*(\d+)\s*:\s*(\d+)\s*", text)
    if not match or int(match.group(2)) <= int(match.group(1)):
        raise ValueError(f"--window needs START:END (0-based take frames, END exclusive); got {text!r}")
    return [int(match.group(1)), int(match.group(2))]


def cmd_accept(args):
    runner=SetRunner(Path(args.plan));st=runner.astate(args.action)
    record=runner.take(args.action,args.take)
    if not args.note or not args.note.strip():raise ValueError('a final visual-review note is required')
    stage=record.get('stages',{}).get('final-review')
    if not stage or not st.get('chosen') or st['chosen']['take']!=args.take:
        raise ValueError('prepare and inspect this take final review before acceptance')
    work=runner.root/stage['dir'];review=comfyui_forge_core.read_json(work/'review.json')
    if review['edgeTouchFrames']:raise ValueError('resolve final framing before accepting')
    st['accepted']={'take':args.take,'note':args.note.strip(),'reviewSha256':comfyui_forge_core.sha256_file(work/'review.json')}
    runner.save()
    return {'status':'accepted','next':'run the same plan to deliver the reviewed animation'}


def cmd_select(args):
    runner=SetRunner(Path(args.plan));st=runner.astate(args.action);record=runner.take(args.action,args.take)
    runner.verify_clip(record)
    window=_parse_window(args.range)
    count=record.get('stages',{}).get('registered',{}).get('frames')
    if count is None or window[1]>count:raise ValueError('decode/register and inspect source before selecting a candidate')
    timing_file=getattr(args,'timing_file',None)
    if timing_file:
        authored=comfyui_forge_core.read_json(Path(timing_file))
        entry=runner.entries[args.action]
        definition={'id':'reviewed','type':entry['motionType'],'description':'reviewed timing',
                    'keys':authored.get('keys',{}),'events':authored.get('events',[])}
        # Use the same complete validation as motion definitions, without editing the immutable generation plan.
        from comfyui_forge_motion_contract import validate_timing
        validate_timing(definition['keys'],definition['events'])
        for item in [*definition['keys'].values(),*definition['events']]:
            if not window[0]<=item['source']<window[1]:raise ValueError('timing source is outside selected candidate')
        base=oneshot_timing(entry)
        if entry['kind']!='oneshot':raise ValueError('authored take timing requires a single-play contract')
        if base.get('mode')=='source' and definition['keys']:raise ValueError('source timing cannot apply target phase keys')
        record['timingOverride']={**base,'keys':definition['keys'],'events':definition['events']}
    invalidate_stages(runner,args.action,record,'motion')
    record['candidateRange']=window;record['candidateClipSha256']=record['clip']['sha256']
    record['stages'].pop('motion',None);record['status']='generated';st['status']='selected';st['accepted']=None
    runner.save();return {'status':'selected','candidateRange':window,'take':args.take}


def invalidate_stages(runner,ident,record,from_stage):
    order=('keyed','registered','motion','finished','final-review')
    if from_stage not in order:raise ValueError('unknown processing stage')
    for name in order[order.index(from_stage):]:
        previous=record.get('stages',{}).pop(name,None)
        if previous:
            path=runner.root/previous['dir']
            if path.exists():_move_aside(path)
    if from_stage=='keyed':record.pop('qc',None)
    record['reviewRevision']=record.get('reviewRevision',1)+1
    st=runner.astate(ident)
    if st.get('output'):st.setdefault('previousOutputs',[]).append(st.pop('output'))
    st.update(chosen=None,selectedTake=record['take'],accepted=None,status='selected',message=None)

def cmd_rebuild(args):
    runner=SetRunner(Path(args.plan));record=runner.take(args.action,args.take);runner.verify_clip(record)
    invalidate_stages(runner,args.action,record,args.from_stage);runner.save()
    return {'status':'local-rebuild-planned','take':record['take'],'fromStage':args.from_stage,'newGeneration':False}


def cmd_retake(args: argparse.Namespace) -> dict:
    runner = SetRunner(Path(args.plan))
    st = runner.astate(args.action)
    fixes = []
    for value in args.fix:
        text = " ".join(str(value).split())
        if not text:
            raise ValueError("--fix needs a clause id from motion-prompts.md or the clause text")
        if text in PLANTED_CLAUSES and moves_feet(runner.entries.get(args.action, {})):
            text = MOVING_FEET_CLAUSE   # preserve explicit movement of support points
            if text not in runner.plan["clauses"]:   # a plan from before the clause existed
                fixes.append({"id": text, "text": load_library().clauses[text]})
                continue
        if text in runner.plan["clauses"]:
            fixes.append({"id": text, "text": runner.plan["clauses"][text]})
        else:
            fixes.append({"id": "agent", "text": text})
    chosen = st.get("chosen")
    if chosen:
        runner.take(args.action, chosen["take"])["review"] = {"verdict": "retake", "at": _now(),
                                                              "fixes": [fix["id"] for fix in fixes]}
    st["round"] = int(st.get("round", 1)) + 1
    known = {fix["text"].lower() for fix in st["fixes"]}
    for fix in fixes:
        if fix["text"].lower() not in known:
            st["fixes"].append({**fix, "source": "agent", "round": st["round"]})
            known.add(fix["text"].lower())
    st.pop("selectedTake",None)
    st.update(chosen=None, accepted=None, status="pending", message=None)
    with open(runner.root / TAKES_FILE, "a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(_scrub({"schema": TAKE_SCHEMA, "at": _now(), "action": args.action,
                                        "take": chosen["take"] if chosen else None, "round": st["round"],
                                        "status": "retake-requested", "fixNext": [fix["id"] for fix in fixes],
                                        "reasons": [fix["text"] for fix in fixes]}), ensure_ascii=False) + "\n")
    runner.save()
    return {"output": str(runner.root), "metadata": str(runner.state_path), "action": args.action,
            "round": st["round"], "fixes": [fix["id"] for fix in fixes], "status": "pending",
            "next": "run comfyui_forge_sprite_set.py run to generate the retake"}


def build_report(runner):
    actions=[]
    for ident in runner.order():
        st=runner.astate(ident)
        actions.append({'id':ident,'motionType':runner.entries[ident]['motionType'],'status':st['status'],
                        'message':st.get('message'),'chosen':st.get('chosen'),'accepted':bool(st.get('accepted')),
                        'outputs':st.get('output'),'takes':len(st['takes'])})
    return {'schema':REPORT_SCHEMA,'status':'complete' if all(a['status']=='done' for a in actions) else 'incomplete',
            'actions':actions,'delivery':'selected PNGs, transparent sheet, GIF, retained source MP4 only'}


def cmd_report(args: argparse.Namespace) -> dict:
    runner = SetRunner(Path(args.plan))
    report = _scrub(build_report(runner))
    if args.output:
        path = Path(args.output)
        if os.path.lexists(path):
            raise ValueError(f"{path.name} already exists; reports are never overwritten")
        path.parent.mkdir(parents=True, exist_ok=True)
    else:
        folder = runner.root / "reports"
        folder.mkdir(exist_ok=True)
        path = _next_numbered(folder, "report", ".json")
    _write_new_json(path, report)
    return {"output": str(path.resolve()), "metadata": str(path.resolve()), "status": report["status"],
            "actions": {item["id"]: item["status"] for item in report["actions"]},
            "needsReview": report["needsReview"]}


# --------------------------------------------------------------------------- CLI

def _positive_int(low: int, high: int) -> Callable[[str], int]:
    def parse(text: str) -> int:
        try:
            value = int(text)
        except ValueError:
            raise argparse.ArgumentTypeError(f"needs a whole number {low}-{high}; got {text!r}") from None
        if not low <= value <= high:
            raise argparse.ArgumentTypeError(f"needs a whole number {low}-{high}; got {text!r}")
        return value
    return parse


def _seconds(low: float, high: float) -> Callable[[str], float]:
    def parse(text: str) -> float:
        try:
            value = float(text)
        except ValueError:
            raise argparse.ArgumentTypeError(f"needs seconds {low:g}-{high:g}; got {text!r}") from None
        if not (math.isfinite(value) and low <= value <= high):
            raise argparse.ArgumentTypeError(f"needs seconds {low:g}-{high:g}; got {text!r}")
        return value
    return parse


def cmd_run(args: argparse.Namespace) -> tuple[dict, int]:
    runner = SetRunner(Path(args.plan))
    generation = runner.plan["generation"]
    only = [item.strip() for item in args.actions.split(",") if item.strip()] if args.actions else None
    return runner.run(only,
                      timeout=args.timeout or float(generation.get("timeoutSeconds") or 1200))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="comfyui_forge_sprite_set.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    pl = sub.add_parser("plan", help="write a new set folder with set_plan.json from an approved master.json",
                        description="Read master.json (generate2dsprite.master.v1) and write a new set folder: "
                                    "master copies and set_plan.json with one clip per action and view.")
    pl.add_argument("--spec",required=True,help="confirmed animation specification JSON")
    pl.add_argument("--master", required=True, help="master.json (generate2dsprite.master.v1); its padded PNG is "
                                                    "found through its files entry and checked by sha256")
    pl.add_argument("--output-dir", required=True, help="new set folder (refused if it exists)")
    pl.add_argument('--motions-file',required=True,help='JSON list: arbitrary id, type, description and confirmed timing/properties')
    pl.add_argument("--views", default="side", help="comma list of side, front, back (default side)")
    pl.add_argument("--view-master", action="append", default=[], metavar="VIEW=FILE",
                    help="master.json of another view (front or back); repeatable")
    pl.add_argument("--finish", choices=FINISHES, help="hd (full colour) or pixel (one palette); default: the "
                                                       "master's finish, else hd")
    pl.add_argument("--target-height", type=_positive_int(8, 4096),
                    help="finished body height in pixels; defaults to the confirmed cell geometry")
    pl.add_argument("--fps",
                    help="optional playback rate assertion; must match the confirmed specification")
    pl.add_argument("--colors", type=int,
                    help="pixel finish without --palette: palette size learned from the scale-reference action and "
                         "shared by every action (default 32)")
    pl.add_argument("--outline", choices=("selective", "dark", "none"),
                    help="pixel finish: 1 px outline (default selective; comfyui_forge_finish_frames.py --outline)")
    pl.add_argument("--canvas", help="fixed cell WIDTHxHEIGHT for every finished frame, such as 48x64")
    pl.add_argument("--canvas-anchor", help="X,Y of the anchor inside the --canvas cell")
    pl.add_argument("--no-colour-lock", action="store_true",
                    help="do not lock the finished colours to the master (comfyui_forge_finish_frames.py --colour-lock, on by "
                         "default for sets)")
    pl.add_argument('--oneshot-timing',choices=('auto','source'),default='auto',help='one-shot timing: retime or retain selected source timing')
    pl.add_argument("--duration", type=float, default=None, help="requested clip seconds, decimals allowed (default 3)")
    pl.add_argument("--candidates", type=int, choices=(2,3), default=3, help="complete same-action source demonstrations")
    pl.add_argument('--pin-last',choices=('auto','on','off'),default='auto',help='auto/off: no tail binding; on: only one-shots returning to their initial pose')
    pl.add_argument("--gen-timeout", type=_seconds(30, 7200), default=1200.0,
                    help="seconds one generation may take (default 1200)")
    pl.add_argument("--style", help="the 'keep the exact <style> look' words (default from the finish)")
    pl.add_argument("--pronoun", default="their", help="possessive in the templates: his, her, its, their (default)")
    pl.add_argument("--palette", help="pixel finish: shared palette PNG or JSON for the whole cast")
    pl.add_argument("--matte-profile",
                    help="character matte profile (video2dsprite.character_profile.v1) passed to every clip's keying, "
                         "e.g. to pin despill 'all' when the generator tints the subject with the key")
    pl.add_argument("--library", help="motion-prompts.md to read (default: this skill's references copy)")
    pl.set_defaults(func=cmd_plan)

    rn = sub.add_parser("run", help="resume one source take per motion, prepare final review, then deliver accepted results",
                        description="Make every planned action; running it again resumes from set_state.json.")
    rn.add_argument("--plan", required=True, help="set_plan.json (or its set folder)")
    rn.add_argument("--actions", help="comma list of action ids to work on (default: every planned action)")
    rn.add_argument("--timeout", type=_seconds(30, 7200), help="override the plan's generation timeout")

    rv = sub.add_parser("review", help="contact sheets per take, finished strips, a cast line-up and review.json",
                        description="Write the review images; the agent must look at every one before accept.")
    rv.add_argument("--plan", required=True, help="set_plan.json (or its set folder)")
    rv.set_defaults(func=cmd_review)

    ac = sub.add_parser("accept", help="record the agent's approval of one take after looking at its sheet")
    ac.add_argument("--plan", required=True, help="set_plan.json (or its set folder)")
    ac.add_argument("--action", required=True, help="action id")
    ac.add_argument("--take", required=True, type=_positive_int(1, 999), help="take number")
    ac.add_argument("--note", help="what was checked")
    ac.set_defaults(func=cmd_accept)

    sel=sub.add_parser('select',help='record one reviewed candidate in an existing generated take')
    sel.add_argument('--plan',required=True);sel.add_argument('--action',required=True);sel.add_argument('--take',required=True,type=int)
    sel.add_argument('--range',required=True);sel.add_argument('--timing-file',help='reviewed keys/events JSON bound to this take');sel.set_defaults(func=cmd_select)

    rb=sub.add_parser('rebuild',help='archive affected local stages and rebuild the same source without generation')
    rb.add_argument('--plan',required=True);rb.add_argument('--action',required=True);rb.add_argument('--take',type=int,required=True)
    rb.add_argument('--from-stage',choices=('keyed','registered','motion','finished','final-review'),required=True)
    rb.set_defaults(func=cmd_rebuild)

    rt = sub.add_parser("retake", help="reject an action semantically; the next run makes a new take with the fix")
    rt.add_argument("--plan", required=True, help="set_plan.json (or its set folder)")
    rt.add_argument("--action", required=True, help="action id")
    rt.add_argument("--fix", required=True, action="append",
                    help="clause id from motion-prompts.md (for example never-turn) or the clause text; repeatable")
    rt.set_defaults(func=cmd_retake)

    rp = sub.add_parser("report", help="one JSON with routes, takes, QC numbers, loops or timing and output files")
    rp.add_argument("--plan", required=True, help="set_plan.json (or its set folder)")
    rp.add_argument("--output", help="new report file (default <set>/reports/report-NNN.json)")
    rp.set_defaults(func=cmd_report)
    return parser


def _run(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "run":
        summary, code = cmd_run(args)
        print(json.dumps(summary, ensure_ascii=True))
        if code:
            failing = [f"{ident} {item['status']}" + (f" ({item['message']})" if item.get("message") else "")
                       for ident, item in summary["actions"].items() if item["status"] not in ("done", "done-warn")]
            raise ValueError("the set is incomplete: " + "; ".join(failing))
        return 0
    print(json.dumps(args.func(args), ensure_ascii=True))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Usage errors exit 2; refused input or a failed step exits 1."""
    return comfyui_forge_core.run_cli(_run, argv, expected=comfyui_forge_core.CLI_EXPECTED_ERRORS + (ToolFailure,))


if __name__ == "__main__":
    raise SystemExit(main())
