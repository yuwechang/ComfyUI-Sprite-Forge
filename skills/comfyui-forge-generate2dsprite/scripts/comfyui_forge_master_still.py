#!/usr/bin/env python3
"""Inspect, pad and approve user-supplied character references."""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import comfyui_forge_core  # noqa: E402  (this skill's vendored copy)
import comfyui_forge_matte  # noqa: E402

TOOL_NAME = "master_still"
TOOL_VERSION = comfyui_forge_core.FORGE_PACKAGE_VERSION
MASTER_SCHEMA = "generate2dsprite.master.v1"
SPEC_SCHEMA = "generate2dsprite.master_spec.v1"
PAD_SCHEMA = "generate2dsprite.master_pad.v1"

CANVAS = 1024                    # the master canvas is square
CROP_MARGIN_PX = 6               # Crop margin around the subject, in source pixels.
EDGE_SAFE_PX = 16                # Minimum subject clearance from the canvas edge, in pixels.
MIN_PART_AREA = 24               # source px; smaller alpha islands are specks
GEOMETRY_ALPHA = comfyui_forge_core.ALPHA_GEOMETRY_THRESHOLD  # alpha > 16 counts for geometry
DEFAULT_KEY = "#FF00FF"

FACINGS = ("left", "right", "front", "back", "none")
FINISHES = ("hd", "pixel")
MATTES = ("soft", "dominance", "hard")
KEY_NAMES = {"#FF00FF": "magenta", "#00FF00": "green", "#0000FF": "blue"}
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
SPEC_FIELDS = ("name", "subject", "identity", "recap", "facing", "view", "class", "finish", "key")


@dataclass(frozen=True)
class ClassPreset:
    """Shared padding dimensions for a character framing label."""

    name: str
    subject_height_px: int
    top_margin_px: int
    lead_px: int


class GeometryPresets(dict):
    def __missing__(self,name):
        return ClassPreset(str(name),768,128,0)
CLASSES=GeometryPresets({'subject':ClassPreset('subject',768,128,0)})


_ARTICLE = re.compile(r"^(?:a|an|the)\s+", re.I)


def _ascii(text: Any) -> str:
    return comfyui_forge_core.ascii_text(str(text))


def clean_text(value: Any, field: str) -> str | None:
    """Whitespace-collapsed text, or None when empty."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"spec field {field} must be a string; got {type(value).__name__}.")
    text = " ".join(value.split())
    return text or None


def strip_article(text: str) -> str:
    return _ARTICLE.sub("", text.strip(), count=1)


def strip_period(text: str) -> str:
    return text.strip().rstrip(".").rstrip()


def positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"needs a positive whole number; got {text!r}") from None
    if value < 1:
        raise argparse.ArgumentTypeError(f"needs a positive whole number; got {text!r}")
    return value


def normalise_key(text: Any) -> str:
    """``#RRGGBB`` (upper case) from a hex colour or a declared name; the key must be a chroma colour."""
    value = str(text).strip().lower()
    named = {name: hex_key for hex_key, name in KEY_NAMES.items()}
    if value in named:
        return named[value]
    digits = value[1:] if value.startswith("#") else value
    if not re.fullmatch(r"[0-9a-f]{6}", digits):
        raise ValueError(f"a key needs #RRGGBB, magenta, green or blue; got {text!r}")
    rgb = [int(digits[i:i + 2], 16) for i in (0, 2, 4)]
    if not any(c > 127 for c in rgb) or not any(c <= 127 for c in rgb):
        raise ValueError(f"key {text!r} is not a chroma colour: it needs strong and weak channels "
                         "(use magenta, green or blue)")
    return "#" + digits.upper()


def key_arg(text: str) -> str:
    try:
        return normalise_key(text)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from None


def key_rgb(hex_key: str) -> tuple[int, int, int]:
    return tuple(int(hex_key[i:i + 2], 16) for i in (1, 3, 5))  # type: ignore[return-value]


def probe_image(path: Path) -> tuple[int, int]:
    """(width, height) of an image file; ValueError when it is not one."""
    try:
        with Image.open(path) as image:
            return int(image.width), int(image.height)
    except (OSError, Image.DecompressionBombError) as error:
        raise ValueError(f"{Path(path).name} is not a readable image ({error})") from None


def final_path(output: Path) -> Path:
    output = Path(output)
    return output.parent.resolve() / output.name


def file_ref(path: Path, base: Path, *, size: bool = False) -> dict[str, Any]:
    ref = comfyui_forge_core.file_ref(path, base)
    if size:
        ref["size"] = list(probe_image(path))
    return ref


def load_spec_file(path: Path) -> dict[str, Any]:
    data = comfyui_forge_core.read_json(path)
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} must hold a JSON object")
    data = dict(data)
    if data.pop("schema", SPEC_SCHEMA) != SPEC_SCHEMA:
        raise ValueError(f"expected {SPEC_SCHEMA}")
    unknown = sorted(set(data) - set(SPEC_FIELDS))
    if unknown:
        raise ValueError("unknown master spec fields: " + ", ".join(unknown))
    return data


def _read_text_file(path: str, what: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError(f"{what} {Path(path).name} is not UTF-8 text.") from None


def merge_flags(base: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    spec = dict(base)
    for field in SPEC_FIELDS:
        value = getattr(args, "klass" if field == "class" else field, None)
        if value is not None:
            spec[field] = value
    if args.identity is not None and args.identity_file:
        raise ValueError("pass --identity or --identity-file, not both")
    if args.identity_file:
        spec["identity"] = _read_text_file(args.identity_file, "--identity-file")
    return spec


def normalise_spec(raw: dict[str, Any]) -> dict[str, Any]:
    name = raw.get("name")
    if not isinstance(name, str) or not NAME_RE.fullmatch(name.strip()):
        raise ValueError("--name must be an asset id of 1-64 letters, digits, '.', '_' or '-'")
    finish = str(raw.get("finish") or "hd").strip().lower()
    facing = str(raw.get("facing") or "right").strip().lower()
    if finish not in FINISHES or facing not in FACINGS:
        raise ValueError("invalid finish or facing")
    spec = {"name": name.strip(), "class": str(raw.get("class") or "subject").strip().lower(),
            "finish": finish, "facing": facing, "key": normalise_key(raw.get("key") or DEFAULT_KEY)}
    for field in ("subject", "identity", "recap", "view"):
        spec[field] = clean_text(raw.get(field), field)
    if not spec["subject"] or not spec["identity"]:
        raise ValueError("--subject and --identity (or --identity-file) are required")
    return spec


def spec_document(spec: dict[str, Any]) -> dict[str, Any]:
    return {"schema": SPEC_SCHEMA, **{field: spec.get(field) for field in SPEC_FIELDS}}


def identity_recap(spec: dict[str, Any]) -> str:
    """The noun phrase motion prompts reuse after 'The same': the spec's recap, else subject (identity)."""
    recap = spec.get("recap")
    if not recap:
        recap = f"{strip_period(strip_article(spec['subject']))} ({strip_period(spec['identity'])})"
    return strip_period(strip_article(recap))


def default_view(spec: dict[str, Any]) -> str:
    if spec.get("view"):
        return spec["view"]
    if spec["class"] == "prop":
        return "three-quarter view"
    return {"left": "side view (profile to three-quarter)", "right": "side view (profile to three-quarter)",
            "front": "front view", "back": "back view", "none": "three-quarter view"}[spec["facing"]]


@dataclass(frozen=True)
class Framing:
    canvas: int
    subject_height_px: int
    top_margin_px: int
    lead_px: int
    preset: str

    def record(self) -> dict[str, Any]:
        return {"canvas": [self.canvas, self.canvas], "subject_height_px": self.subject_height_px,
                "top_margin_px": self.top_margin_px, "lead_px": self.lead_px, "preset": self.preset}


def framing_for(klass: str, args: argparse.Namespace | None = None) -> Framing:
    """The class preset, with --subject-height / --top-margin / --lead overrides (preset 'custom')."""
    preset = CLASSES[klass]
    height = getattr(args, "subject_height", None)
    top = getattr(args, "top_margin", None)
    lead = getattr(args, "lead", None)
    custom = any(value is not None for value in (height, top, lead))
    framing = Framing(CANVAS, preset.subject_height_px if height is None else height,
                      preset.top_margin_px if top is None else top, preset.lead_px if lead is None else lead,
                      "custom" if custom else preset.name)
    if not 64 <= framing.subject_height_px <= CANVAS - 2 * EDGE_SAFE_PX:
        raise ValueError(f"--subject-height must be 64-{CANVAS - 2 * EDGE_SAFE_PX} px; "
                         f"got {framing.subject_height_px}.")
    if framing.top_margin_px < 0 or framing.top_margin_px + framing.subject_height_px > CANVAS:
        raise ValueError(f"--top-margin {framing.top_margin_px} with a {framing.subject_height_px} px subject leaves "
                         f"the {CANVAS} px canvas.")
    if not 0 <= framing.lead_px <= CANVAS // 4:
        raise ValueError(f"--lead must be 0-{CANVAS // 4} px; got {framing.lead_px}.")
    return framing


def key_subject(pixels: np.ndarray, key_hex: str, matte: str) -> tuple[np.ndarray, dict[str, Any]]:
    """Input extraction is independent of the requested output key colour."""
    if int(pixels[...,3].min())<250:
        return pixels.copy(), {'requested':matte,'quality':'native_alpha'}
    import comfyui_forge_background_input
    keyed,report=comfyui_forge_background_input.extract(pixels,pixel_art=matte=='hard')
    report.update(requested=matte,quality='flat-background')
    return keyed,report


def subject_parts(alpha: np.ndarray, min_area: int) -> dict[str, Any]:
    """The subject box: every 8-connected part with at least ``min_area`` px of alpha > 16."""
    components = comfyui_forge_core.connected_components(alpha, threshold=GEOMETRY_ALPHA)
    kept = [part for part in components if part["area"] >= min_area]
    if not kept:
        raise ValueError(f"No subject found: no keyed part has {min_area} px or more.")
    x0 = min(part["bbox"][0] for part in kept)
    y0 = min(part["bbox"][1] for part in kept)
    x1 = max(part["bbox"][2] for part in kept)
    y1 = max(part["bbox"][3] for part in kept)
    height, width = alpha.shape
    touches = [side for side, hit in (("left", x0 == 0), ("top", y0 == 0), ("right", x1 == width),
                                      ("bottom", y1 == height)) if hit]
    return {"bbox": [x0, y0, x1, y1], "parts": len(kept), "ignored_parts": len(components) - len(kept),
            "ignored_px": int(sum(part["area"] for part in components if part["area"] < min_area)),
            "touches": touches}


def composite_on_key(rgba: np.ndarray, rgb: Sequence[int]) -> np.ndarray:
    """Straight-alpha 'over' onto the flat key; outside the subject every pixel is exactly the key."""
    alpha = rgba[..., 3:].astype(np.float64) / 255.0
    mixed = rgba[..., :3].astype(np.float64) * alpha + np.asarray(rgb, np.float64) * (1.0 - alpha)
    return np.floor(mixed + 0.5).astype(np.uint8)


def pad_still(pixels: np.ndarray, *, key_hex: str, framing: Framing, facing: str, matte: str = "soft",
              crop_margin: int = CROP_MARGIN_PX, min_part_area: int = MIN_PART_AREA) -> dict[str, Any]:
    """Key, find, crop (margin), LANCZOS-place on the canvas at the class framing, flatten onto the pure key.

    Returns ``padded`` (opaque RGB), ``cutout`` (RGBA), ``framing``, ``transform``, ``matte``,
    ``key_choice`` and ``warnings``. The transform maps source to master: ``master = scale * source +
    offset`` in continuous pixel coordinates.
    """
    warnings: list[str] = []
    keyed, matte_record = key_subject(pixels, key_hex, matte)
    height, width = keyed.shape[:2]
    parts = subject_parts(keyed[..., 3], min_part_area)
    x0, y0, x1, y1 = parts["bbox"]
    box_w, box_h = x1 - x0, y1 - y0
    if box_h < 16 or box_w < 4:
        raise ValueError(f"The subject is too small to pad: {box_w}x{box_h} px.")
    if box_w * box_h >= 0.98 * width * height:
        raise ValueError("The keyed subject fills the whole still: the backdrop was not keyed. Pass the right --key.")
    canvas = framing.canvas
    scale = framing.subject_height_px / box_h
    width_limited = box_w * scale > canvas - 2 * EDGE_SAFE_PX
    if width_limited:
        scale = (canvas - 2 * EDGE_SAFE_PX) / box_w
    sign = {"left": 1.0, "right": -1.0}.get(facing, 0.0)
    half = box_w * scale / 2.0
    centre = canvas / 2.0 + sign * framing.lead_px
    centre = min(max(centre, EDGE_SAFE_PX + half), canvas - EDGE_SAFE_PX - half)
    offset = (centre - scale * (x0 + x1) / 2.0, framing.top_margin_px - scale * y0)
    crop = [max(0, x0 - crop_margin), max(0, y0 - crop_margin), min(width, x1 + crop_margin),
            min(height, y1 + crop_margin)]
    region = np.ascontiguousarray(keyed[crop[1]:crop[3], crop[0]:crop[2]])
    placed = comfyui_forge_core.resample_rgba(region, scale, "lanczos", anchor_src=(0.0, 0.0),
                                      anchor_dst=(scale * crop[0] + offset[0], scale * crop[1] + offset[1]),
                                      out_size=(canvas, canvas))
    placed, hygiene = comfyui_forge_core.alpha_hygiene(placed, mode="floor")
    cutout = np.array(placed, dtype=np.uint8)
    padded = composite_on_key(cutout, key_rgb(key_hex))
    measured = comfyui_forge_core.subject_bbox(cutout[..., 3])
    if measured is None:
        raise ValueError("The placed subject is empty; check --key and --min-part-area.")
    measured_h = measured[3] - measured[1]
    anchor = comfyui_forge_core.anchor_from_mask(comfyui_forge_core.subject_mask(cutout[..., 3]), "stance",
                                         band_rows=max(2, comfyui_forge_core.round_half_up(0.04 * measured_h)))
    if parts["touches"]:
        warnings.append(f"the subject touches the {', '.join(parts['touches'])} edge of the still and may be cut "
                        "off: prepare a source image with more margin")
    if scale > 1.0 + 1e-9:
        warnings.append(f"the subject is upscaled x{scale:.2f} ({box_h} px source height): detail will be soft; "
                        "ask the route for a larger figure")
    if width_limited:
        warnings.append(f"the subject is too wide for the {framing.preset} framing: scaled to fit the width, "
                        f"{measured_h} px tall instead of {framing.subject_height_px} px")
    elif abs(measured_h - framing.subject_height_px) > 3 or abs(measured[1] - framing.top_margin_px) > 3:
        warnings.append(f"the placed subject measures {measured_h} px tall at top {measured[1]} px (target "
                        f"{framing.subject_height_px} px at {framing.top_margin_px} px)")
    choice = comfyui_forge_matte.choose_key_color(keyed, (key_hex.lower(),))
    row = choice["candidates"][0]
    key_choice = {"status": choice["status"], "overlap_share": round(float(row["overlap_share"]), 6),
                  "rule": choice["rule"]}
    if row["rejected"]:
        warnings.append(f"{row['overlap_share']:.1%} of the subject's colours lean to the key {key_hex} (more than "
                        "0.5%): check that those parts survive keying; for purple or pink designs use --key green "
                        "or blue")
    if matte_record.get("qa", {}).get("opaque_key_px", 0) > 0:
        warnings.append(f"{matte_record['qa']['opaque_key_px']} opaque key-coloured pixels remain in the subject: "
                        "check the master over a dark background")
    framing_record = {**framing.record(), "subject_bbox": [int(v) for v in measured],
                      "anchor": [float(anchor[0]), float(anchor[1])],
                      "opaque_area_px": int((cutout[..., 3] >= 128).sum()), "width_limited": bool(width_limited)}
    transform = {
        "mapping": "master = scale * source + offset (continuous pixel coordinates: pixel i spans [i, i + 1))",
        "source_size": [int(width), int(height)],
        "source_subject_bbox": [int(v) for v in parts["bbox"]],
        "crop_box": [int(v) for v in crop],
        "crop_margin_px": int(crop_margin),
        "scale": float(scale),
        "offset": [float(offset[0]), float(offset[1])],
        "canvas": [canvas, canvas],
        "resampler": "box" if scale <= 0.5 else "lanczos",
        "premultiplied": True,
        "alpha_floor_px": int(hygiene["floor_px"]),
        "subject_parts": parts["parts"],
        "ignored_parts": parts["ignored_parts"],
        "ignored_px": parts["ignored_px"],
        "source_touches": parts["touches"],
        "key_rgb": list(key_rgb(key_hex)),
    }
    return {"padded": padded, "cutout": cutout, "framing": framing_record, "transform": transform,
            "matte": matte_record, "key_choice": key_choice, "warnings": warnings}


def _is_rel_path(value: Any) -> bool:
    return isinstance(value, str) and bool(value) and not value.startswith("/") and "\\" not in value and \
        not re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", value)


def _is_sha(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def validate_master(doc: Any) -> list[str]:
    """Errors in a generate2dsprite.master.v1 record (the fields motion steps rely on); empty when valid."""
    if not isinstance(doc, dict):
        return ["master.json must be an object"]
    errors = []
    if doc.get("schema") != MASTER_SCHEMA:
        errors.append(f"schema must be {MASTER_SCHEMA}")
    if not isinstance(doc.get("name"), str) or not NAME_RE.match(doc["name"]):
        errors.append("name must be an asset id")
    if not isinstance(doc.get("identity_recap"), str) or not doc["identity_recap"].strip():
        errors.append("identity_recap must be a non-empty string")
    for field, allowed in (("facing", FACINGS), ("finish", FINISHES), ("class", None)):
        if allowed is not None and doc.get(field) not in allowed:
            errors.append(f"{field} must be one of {', '.join(allowed)}")
    framing = doc.get("framing")
    if not isinstance(framing, dict):
        errors.append("framing must be an object")
    else:
        canvas = framing.get("canvas")
        if not (isinstance(canvas, list) and len(canvas) == 2 and all(isinstance(v, int) and v > 0 for v in canvas)):
            errors.append("framing.canvas must be [width, height]")
        for field in ("subject_height_px", "top_margin_px"):
            if not isinstance(framing.get(field), int) or isinstance(framing.get(field), bool) or framing[field] < 0:
                errors.append(f"framing.{field} must be a whole number >= 0")
    if not isinstance(doc.get("key"), str) or not re.fullmatch(r"#[0-9A-F]{6}", doc["key"]):
        errors.append("key must be #RRGGBB (upper case)")
    files = doc.get("files")
    if not isinstance(files, dict):
        errors.append("files must be an object")
    else:
        for name in ("master", "cutout", "source", "spec"):
            ref = files.get(name)
            if not isinstance(ref, dict) or not _is_rel_path(ref.get("path")) or not _is_sha(ref.get("sha256")):
                errors.append(f"files.{name} must be a fileRef with a relative path and a sha256")
        prompt = files.get("prompt")
        if prompt is not None and (not isinstance(prompt, dict) or not _is_sha(prompt.get("sha256"))):
            errors.append("files.prompt must be null or a fileRef")
    transform = doc.get("transform")
    scale = transform.get("scale") if isinstance(transform, dict) else None
    offset = transform.get("offset") if isinstance(transform, dict) else None
    if not isinstance(scale, (int, float)) or not scale > 0 or not (isinstance(offset, list) and len(offset) == 2):
        errors.append("transform must hold scale > 0 and offset [x, y]")
    if not isinstance(doc.get("route"), str) or not doc["route"].strip():
        errors.append("route must be a non-empty string")
    return errors


def _emit(warnings: Sequence[str]) -> None:
    for warning in warnings:
        print("warning: " + _ascii(warning), file=sys.stderr)


def _still_and_spec(args: argparse.Namespace, warnings: list[str]) -> dict[str, Any]:
    still = getattr(args, "still", None) or getattr(args, "input", None)
    if not still:
        raise ValueError("pass the supplied still: --still/--input PATH.")
    still = Path(still)
    if not still.is_file():
        raise ValueError(f"The still does not exist: {still.as_posix()}")
    base = load_spec_file(Path(args.spec)) if args.spec else {}
    return {"still": still, "base": base}


def cmd_pad(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    warnings: list[str] = []
    context = _still_and_spec(args, warnings)
    base = context["base"]
    klass = (args.klass or base.get("class") or "subject").strip().lower()
    facing = (args.facing or base.get("facing") or "none").strip().lower()
    if facing not in FACINGS:
        raise ValueError(f"facing must be one of {', '.join(FACINGS)}; got {facing!r}.")
    key_hex = normalise_key(args.key or base.get("key") or DEFAULT_KEY)
    framing = framing_for(klass, args)
    image, info = comfyui_forge_core.load_rgba(context["still"])
    result = pad_still(np.asarray(image), key_hex=key_hex, framing=framing, facing=facing, matte=args.matte,
                       crop_margin=args.crop_margin, min_part_area=args.min_part_area)
    warnings += result["warnings"]
    output = Path(args.output_dir)
    with comfyui_forge_core.staged_output(output) as stage:
        comfyui_forge_core.save_png(result["padded"], stage / "padded.png")
        comfyui_forge_core.save_png(result["cutout"], stage / "padded_rgba.png")
        doc = {
            "schema": PAD_SCHEMA, "tool": {"name": TOOL_NAME, "version": TOOL_VERSION},
            "created": comfyui_forge_core.utc_timestamp(),
            "source": {"name": context["still"].name, "sha256": info["sha256"], "bytes": info["bytes"],
                       "size": info["size"]},
            "class": klass, "facing": facing, "key": key_hex,
            "framing": result["framing"], "transform": result["transform"], "matte": result["matte"],
            "key_choice": result["key_choice"],
            "files": {"padded": file_ref(stage / "padded.png", stage, size=True),
                      "cutout": file_ref(stage / "padded_rgba.png", stage, size=True)},
            "warnings": warnings,
        }
        comfyui_forge_core.write_json(stage / "pad.json", doc)
    _emit(warnings)
    final = final_path(output)
    return {"status": "ok", "command": "pad", "output": str(final), "padded": str(final / "padded.png"),
            "cutout": str(final / "padded_rgba.png"), "metadata": str(final / "pad.json"), "class": klass,
            "scale": result["transform"]["scale"], "offset": result["transform"]["offset"],
            "subject_bbox": result["framing"]["subject_bbox"], "warnings": len(warnings)}, 0


def cmd_approve(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    warnings: list[str] = []
    context = _still_and_spec(args, warnings)
    still = context["still"]
    if args.identity_recap is not None and args.identity_recap_file:
        raise ValueError("pass --identity-recap or --identity-recap-file, not both.")
    raw = merge_flags(context["base"], args)
    if args.identity_recap_file:
        raw["recap"] = _read_text_file(args.identity_recap_file, "--identity-recap-file")
    elif args.identity_recap is not None:
        raw["recap"] = args.identity_recap
    spec = normalise_spec(raw)
    spec["recap"] = identity_recap(spec)
    prompt_path = None
    if args.prompt_file:
        prompt_path = Path(args.prompt_file)
        if not prompt_path.is_file():
            raise ValueError(f"--prompt-file {prompt_path.as_posix()} does not exist.")
    route = clean_text(args.route, "route") or "external"
    framing = framing_for(spec["class"], args)
    image, info = comfyui_forge_core.load_rgba(still)
    result = pad_still(np.asarray(image), key_hex=spec["key"], framing=framing, facing=spec["facing"],
                       matte=args.matte, crop_margin=args.crop_margin, min_part_area=args.min_part_area)
    warnings += result["warnings"]
    output = Path(args.output_dir)
    with comfyui_forge_core.staged_output(output) as stage:
        comfyui_forge_core.save_png(result["padded"], stage / "master.png")
        comfyui_forge_core.save_png(result["cutout"], stage / "master_rgba.png")
        source = stage / ("source" + (still.suffix.lower() if still.suffix else ".png"))
        shutil.copyfile(still, source)
        prompt_ref = None
        if prompt_path is not None:
            shutil.copyfile(prompt_path, stage / "prompt.txt")
            prompt_ref = comfyui_forge_core.file_ref(stage / "prompt.txt", stage)
        comfyui_forge_core.write_json(stage / "spec.json", spec_document(spec))
        doc = {
            "schema": MASTER_SCHEMA,
            "tool": {"name": TOOL_NAME, "version": TOOL_VERSION},
            "created": comfyui_forge_core.utc_timestamp(),
            "name": spec["name"],
            "subject": spec["subject"],
            "identity_recap": spec["recap"],
            "facing": spec["facing"],
            "view": default_view(spec),
            "finish": spec["finish"],
            "class": spec["class"],
            "framing": result["framing"],
            "key": spec["key"],
            "files": {
                "master": file_ref(stage / "master.png", stage, size=True),
                "cutout": file_ref(stage / "master_rgba.png", stage, size=True),
                "source": file_ref(source, stage, size=True),
                "spec": comfyui_forge_core.file_ref(stage / "spec.json", stage),
                "prompt": prompt_ref,
            },
            "transform": result["transform"],
            "route": route,
            "provenance": {
                "command": "supplied-image",
                "source_name": still.name,
                "source_sha256": info["sha256"],
                },
            "matte": {**result["matte"], "key_choice": result["key_choice"]},
            "warnings": warnings,
        }
        errors = validate_master(doc)
        if errors:
            raise ValueError("master.json self-check failed: " + "; ".join(errors))
        comfyui_forge_core.write_json(stage / "master.json", doc)
    _emit(warnings)
    final = final_path(output)
    return {"status": "ok", "command": "approve", "output": str(final), "master": str(final / "master.png"),
            "cutout": str(final / "master_rgba.png"), "metadata": str(final / "master.json"), "name": spec["name"],
            "class": spec["class"], "finish": spec["finish"], "facing": spec["facing"], "route": route,
            "framing": {key: result["framing"][key] for key in ("canvas", "subject_height_px", "top_margin_px",
                                                                "subject_bbox")},
            "warnings": len(warnings)}, 0


def add_spec_arguments(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("character metadata")
    group.add_argument("--spec", help="saved character metadata JSON; flags override it")
    group.add_argument("--name", help="asset id")
    group.add_argument("--subject", help="short description of the supplied character")
    group.add_argument("--identity", help="character appearance used in animation prompts")
    group.add_argument("--identity-file", help="UTF-8 file containing the appearance description")
    group.add_argument("--recap", help="identity recap for animation prompts")
    group.add_argument("--facing", choices=FACINGS)
    group.add_argument("--view", help="view of the supplied character image")
    group.add_argument("--class", dest="klass", help="character framing label")
    group.add_argument("--finish", choices=FINISHES)
    group.add_argument("--key", type=key_arg)


def add_pad_arguments(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("framing and keying")
    group.add_argument("--subject-height", type=int,
                       help=f"subject height in px on the {CANVAS} canvas (default: 768)")
    group.add_argument("--top-margin", type=int,
                       help="px from the canvas top to the subject top (default: 128)")
    group.add_argument("--lead", type=int,
                       help="px the subject centre moves away from its facing side (default: 0)")
    group.add_argument("--crop-margin", type=int, default=CROP_MARGIN_PX,
                       help=f"px kept around the subject when cropping (default {CROP_MARGIN_PX})")
    group.add_argument("--matte", choices=MATTES, default="soft",
                       help="forge_matte keyer that finds the subject (default soft)")
    group.add_argument("--min-part-area", type=positive_int, default=MIN_PART_AREA,
                       help=f"parts smaller than this many source px are specks: ignored for the subject box and "
                            f"dropped outside it (default {MIN_PART_AREA})")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="comfyui_forge_master_still.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    pd = sub.add_parser("pad", help="key, crop and LANCZOS-scale a still to the class framing on 1024x1024",
                        description="Flatten the backdrop to the pure key, find the subject with forge_matte, crop "
                                    "it with a 6 px margin and LANCZOS-scale it to the class framing; record the "
                                    "transform.")
    still = pd.add_argument_group("the still")
    still.add_argument("--input", help="supplied character image (any size, flat background or alpha)")
    still.add_argument("--spec", help="spec JSON: class, facing and key come from it")
    still.add_argument("--class", dest="klass", type=str, help="framing label (default subject)")
    still.add_argument("--facing", choices=FACINGS, help="facing direction for placement "
                                                        "(default none)")
    still.add_argument("--key", type=key_arg, help="key colour of the still (default #FF00FF)")
    add_pad_arguments(pd)
    pd.add_argument("--output-dir", required=True, help="new folder (must not exist)")
    pd.set_defaults(func=cmd_pad)

    pa = sub.add_parser("approve", help="pad the chosen still and write master.png and master.json",
                        description="Pad the chosen still to the class framing and write master.png, "
                                    "master_rgba.png, source, spec.json, prompt.txt and master.json "
                                    f"({MASTER_SCHEMA}).")
    chosen = pa.add_argument_group("the chosen still")
    chosen.add_argument("--still", help="the chosen still (any route, or the host's own image tool)")
    chosen.add_argument("--route", help="provenance label for the supplied image (default external)")
    chosen.add_argument("--prompt-file", help="prompt that made --still (copied for provenance)")
    chosen.add_argument("--identity-recap", help="identity recap for motion prompts (default: the spec's recap, "
                                                 "else subject (identity))")
    chosen.add_argument("--identity-recap-file", help="UTF-8 text file holding the identity recap")
    add_spec_arguments(pa)
    add_pad_arguments(pa)
    pa.add_argument("--output-dir", required=True, help="new folder (must not exist)")
    pa.set_defaults(func=cmd_approve)
    return parser


def _check_args(args: argparse.Namespace) -> None:
    margin = getattr(args, "crop_margin", None)
    if margin is not None and not 0 <= margin <= 64:
        raise ValueError(f"--crop-margin must be 0-64 px; got {margin}.")


def run(argv: Sequence[str] | None = None) -> tuple[dict[str, Any], int]:
    """Parse argv and run the command; returns (JSON summary, exit status). Raises on errors."""
    args = build_parser().parse_args(argv)
    _check_args(args)
    return args.func(args)


def _run(argv: Sequence[str] | None = None) -> int:
    summary, code = run(argv)
    print(json.dumps(summary, ensure_ascii=True))
    if code == 1 and summary.get("error"):
        print("error: " + _ascii(summary["error"]), file=sys.stderr)
    return code


def main(argv: Sequence[str] | None = None) -> int:
    return comfyui_forge_core.run_cli(_run, argv)


if __name__ == "__main__":
    raise SystemExit(main())
