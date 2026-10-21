"""Shared chroma keying and colour repair.

Images use 8-bit straight-alpha RGBA; output RGB is zero where alpha is zero.
Keys accept declared names, #rrggbb strings or RGB triples.
Canonical copies and skill destinations are listed in shared/VENDORED.json.
"""

from __future__ import annotations

import math
import operator
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, NamedTuple, Sequence

import numpy as np
from PIL import Image

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import comfyui_forge_core  # noqa: E402  (the sibling copy: shared/ or the skill's scripts/)

_CORE_API = str(getattr(comfyui_forge_core, "FORGE_CORE_API_VERSION", "")).split(".")
if _CORE_API[0] != "1" or len(_CORE_API) < 2 or not _CORE_API[1].isdigit() or int(_CORE_API[1]) < 1:
    raise ImportError("forge_matte needs forge_core API version 1.1 or a later 1.x next to it; "
                      "run tools/comfyui_forge_vendor_sync.py --write.")


DECLARED_KEYS = {"magenta": (255, 0, 255), "green": (0, 255, 0), "blue": (0, 0, 255)}
KEY_QUALITIES = ("hard", "soft", "dominance", "auto")
DESPILL_MODES = ("off", "edge", "all", "auto")

KEY_MATERIAL_SHARE_MAX = 0.005   # subject owns no key-coloured material at or below this share (auto despill)
KEY_TOLERANCE = 48.0             # RGB distance of key noise (codec ring noise p99.9 7, max 35)
OVERLAP_DOMINANCE = 40.0         # a design colour this key-dominant fights the key (choose_key_color)
SPILL_HUE_BALANCE = 0.5          # matte_qa: two-channel key spill keeps min/max of its channels at or above this
LOCAL_BACKGROUND_RADIUS = 12     # px window of the local background estimate B(x)

_LUMA = (0.299, 0.587, 0.114)
_YCC = np.array([[0.299, 0.587, 0.114],
                 [-0.168736, -0.331264, 0.5],
                 [0.5, -0.418688, -0.081312]], np.float32)
_KEY_SEARCH = 160.0       # ring pixels this close to the declared key are key candidates
_MIN_KEY_SHARE = 0.12     # ... and they must be at least this share of the ring
_MIN_KEY_DOMINANCE = 60.0  # an estimated key must still lean this far to its channels
_MIN_COVERAGE = 0.01      # below this share of key pixels, an image with alpha keeps its own alpha
_OPAQUE = 250             # ring pixels at or above this alpha count as opaque backdrop


@dataclass(frozen=True)
class KeyParams:
    """Soft-matte parameters. STILL_KEY_PARAMS uses defaults for full-resolution still images."""

    w_chroma: float = 0.2     # chroma weight in the matting space (luma weight 1)
    t_bg: float = 18.0        # weighted |C-K| at/below: background
    t_fg: float = 40.0        # weighted |C-K| at/above: subject-like (outline core etc.)
    keylike: float = 0.5      # key dominance >= keylike * the key's (and |S-SK| < t_fg): background
    r_a: int = 3              # alpha zone: px from background where partial alpha is allowed
    r_c: int = 6              # colour-clean zone: px from background (chroma smear reach 3-5 px)
    radius: int = 4           # candidate search radius (px)
    tau: float = 6.0          # residual allowance (weighted units)
    kappa: float = 0.6        # residual allowance proportional to |p-K|
    temp: float = 0.4         # soft-min temperature over candidate alphas
    a_lo: float = 0.04        # alpha below -> 0
    a_hi: float = 0.96        # alpha above -> 1
    unmix_from: float = 0.0   # luma blend toward the exact un-mix: from 0 here to 1 at alpha 1
    excess_slack: float = 3.0  # allowed key excess above the local deep-interior excess
    ref_r: int = 10           # neighbourhood (px) for the local excess reference (box mean)
    speck_steps: int = 3      # hysteresis steps from alpha >= 0.5
    monotone: bool = True     # alpha non-decreasing inward along distance-to-background levels
    interior_despill: bool = False  # clamp key excess on ALL visible pixels (see the auto rule)
    snap: str = "ramp"        # "ramp": (a-a_lo)/(a_hi-a_lo) clipped; "hard": cut at a_lo/a_hi
    refine: str = "none"      # "guided": luma-guided filter on alpha in the zone (worse on video)
    gf_r: int = 2             # guided filter radius
    gf_eps: float = 0.004     # guided filter regulariser (alpha and luma/255 units)

    def __post_init__(self) -> None:
        if self.snap not in ("ramp", "hard") or self.refine not in ("none", "guided"):
            raise ValueError("KeyParams.snap must be 'ramp' or 'hard'; refine 'none' or 'guided'.")
        if not (self.w_chroma > 0 and 0 <= self.t_bg < self.t_fg and 0 <= self.a_lo < self.a_hi <= 1
                and self.temp > 0 and min(self.r_a, self.radius) >= 1
                and min(self.r_c, self.ref_r, self.speck_steps, self.gf_r) >= 0):
            raise ValueError(f"Invalid KeyParams: {self}")

    def to_dict(self) -> dict:
        return asdict(self)


STILL_KEY_PARAMS = KeyParams(w_chroma=1.0, r_c=3)  # stills have full-resolution chroma


class _KeyModel(NamedTuple):
    rgb: np.ndarray            # float32 (3,)
    high: tuple[int, ...]      # the key's channels (above mid-grey)
    low: tuple[int, ...]       # the other channels
    luma_gain: float           # BT.601 luma of the key channels, restored by despill


def _key_rgb(key: Any) -> np.ndarray:
    """A key name, ``#rrggbb`` or an RGB triple as a float32 ``(3,)`` array."""
    if isinstance(key, str):
        text = key.strip().lower()
        if text in DECLARED_KEYS:
            return np.array(DECLARED_KEYS[text], np.float32)
        digits = text[1:] if text.startswith("#") else text
        if len(digits) == 6:
            try:
                return np.array([int(digits[i:i + 2], 16) for i in (0, 2, 4)], np.float32)
            except ValueError:
                pass
        raise ValueError(f"Unknown key {key!r}; use magenta, green, blue, #rrggbb or an RGB triple.")
    value = np.asarray(key, dtype=np.float32).reshape(-1)
    if value.shape != (3,) or not np.all(np.isfinite(value)) or value.min() < 0 or value.max() > 255:
        raise ValueError(f"A key colour needs three channel values in 0..255; got {key!r}.")
    return value


def _key_model(key: Any) -> _KeyModel:
    rgb = _key_rgb(key)
    high = tuple(int(c) for c in np.flatnonzero(rgb > 127.5))
    low = tuple(int(c) for c in np.flatnonzero(rgb <= 127.5))
    if not high or not low:
        raise ValueError(f"Key {rgb.tolist()} is not a chroma colour; it needs both strong and weak channels.")
    return _KeyModel(rgb, high, low, round(sum(_LUMA[c] for c in high), 6))


def _dominance(rgb: np.ndarray, model: _KeyModel) -> np.ndarray:
    """``min(key channels) - max(other channels)``: for magenta exactly ``min(R, B) - G``."""
    high = [rgb[..., c] for c in model.high]
    low = [rgb[..., c] for c in model.low]
    lead = high[0] if len(high) == 1 else np.minimum(high[0], high[1])
    rest = low[0] if len(low) == 1 else np.maximum(low[0], low[1])
    return lead - rest


def _hex(rgb: Sequence[float]) -> str:
    return "#" + "".join(f"{int(round(float(v))):02x}" for v in rgb)


def _pixels(image: Any) -> np.ndarray:
    """uint8 ``H x W x 3`` or ``H x W x 4`` array of an Image or array (premultiplied modes refused)."""
    if isinstance(image, Image.Image):
        if image.mode in ("RGBa", "La"):
            raise ValueError(f"Expected straight alpha; got premultiplied mode {image.mode}.")
        if image.mode not in ("RGB", "RGBA"):
            image = image.convert("RGBA" if "A" in image.getbands() or "transparency" in image.info else "RGB")
        return np.asarray(image)
    array = np.asarray(image)
    if array.dtype != np.uint8 or array.ndim != 3 or array.shape[2] not in (3, 4):
        raise ValueError(f"Expected an 8-bit RGB or RGBA image; got {array.dtype} {array.shape}.")
    return array


def _rgba(image: Any) -> np.ndarray:
    """A new uint8 RGBA array (RGB input becomes opaque)."""
    array = _pixels(image)
    if array.shape[2] == 4:
        return array.copy()
    return np.dstack([array, np.full(array.shape[:2], 255, np.uint8)])


def _split(image: Any) -> tuple[np.ndarray, np.ndarray | None]:
    """``(rgb, alpha)`` uint8 arrays; alpha is None for RGB input."""
    array = _pixels(image)
    if array.shape[2] == 3:
        return array, None
    return array[..., :3], array[..., 3]


def _mask(mask: Any, shape: tuple[int, int], name: str) -> np.ndarray | None:
    if mask is None:
        return None
    array = np.asarray(mask, dtype=bool)
    if array.shape != shape:
        raise ValueError(f"{name} mask shape {array.shape} does not match the image {shape}.")
    return array


def _grow(mask: np.ndarray) -> np.ndarray:
    """One 8-neighbour (3 x 3) dilation step; the canvas exterior never counts."""
    grown = mask.copy()
    grown[:, 1:] |= mask[:, :-1]
    grown[:, :-1] |= mask[:, 1:]
    result = grown.copy()
    result[1:] |= grown[:-1]
    result[:-1] |= grown[1:]
    return result


def _box_max(image: np.ndarray, radius: int) -> np.ndarray:
    result = image.copy()
    for _ in range(radius):
        grown = result.copy()
        np.maximum(grown[:, 1:], result[:, :-1], out=grown[:, 1:])
        np.maximum(grown[:, :-1], result[:, 1:], out=grown[:, :-1])
        step = grown.copy()
        np.maximum(step[1:], grown[:-1], out=step[1:])
        np.maximum(step[:-1], grown[1:], out=step[:-1])
        result = step
    return result


def _box_sum(image: np.ndarray, radius: int) -> np.ndarray:
    """Sum over a ``(2r+1)^2`` window via an integral image (edges clipped), as float32.

    The integral image accumulates in the input's dtype (float32 in v13);
    pass float64 when whole-image sums can exceed 2**24.
    """
    height, width = image.shape
    integral = np.zeros((height + 1, width + 1), np.float64)
    integral[1:, 1:] = image.cumsum(0).cumsum(1)
    y0 = np.clip(np.arange(height) - radius, 0, height)
    y1 = np.clip(np.arange(height) + radius + 1, 0, height)
    x0 = np.clip(np.arange(width) - radius, 0, width)
    x1 = np.clip(np.arange(width) + radius + 1, 0, width)
    return (integral[y1][:, x1] - integral[y0][:, x1] - integral[y1][:, x0] + integral[y0][:, x0]).astype(np.float32)


def _guided_filter(guide: np.ndarray, source: np.ndarray, radius: int, eps: float) -> np.ndarray:
    """He et al. guided filter with a grey guide; box sums via integral images."""
    count = _box_sum(np.ones_like(guide), radius)
    mean_i = _box_sum(guide, radius) / count
    mean_p = _box_sum(source, radius) / count
    cov_ip = _box_sum(guide * source, radius) / count - mean_i * mean_p
    var_i = _box_sum(guide * guide, radius) / count - mean_i * mean_i
    a = cov_ip / (var_i + eps)
    b = mean_p - a * mean_i
    return (_box_sum(a, radius) / count) * guide + _box_sum(b, radius) / count


def _disk(radius: int) -> np.ndarray:
    offsets = [(dy, dx) for dy in range(-radius, radius + 1) for dx in range(-radius, radius + 1)
               if (dy or dx) and dy * dy + dx * dx <= radius * radius + radius]
    return np.array(offsets, np.int32).reshape(-1, 2)


def _border_connected(mask: np.ndarray, connectivity: int) -> np.ndarray:
    """True pixels whose ``connectivity``-connected component touches the canvas edge."""
    labels, count = comfyui_forge_core.label_components(mask, connectivity)
    touching = np.zeros(count + 1, bool)
    if count:
        for edge in (labels[0], labels[-1], labels[:, 0], labels[:, -1]):
            touching[edge] = True
        touching[0] = False
    return touching[labels]


def _to_oklab(rgb: np.ndarray) -> np.ndarray:
    """sRGB 0..255 (any shape ``... x 3``) to OKLab (Ottosson 2020), float32."""
    c = np.asarray(rgb, np.float32) / np.float32(255.0)
    linear = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4).astype(np.float32)
    lms = linear @ np.array([[0.4122214708, 0.5363325363, 0.0514459929],
                             [0.2119034982, 0.6806995451, 0.1073969566],
                             [0.0883024619, 0.2817188376, 0.6299787005]], np.float32).T
    return np.cbrt(lms) @ np.array([[0.2104542553, 0.7936177850, -0.0040720468],
                                    [1.9779984951, -2.4285922050, 0.4505937099],
                                    [0.0259040371, 0.7827717662, -0.8086757660]], np.float32).T


def _matting_space(w_chroma: float) -> tuple[np.ndarray, np.ndarray]:
    """``(M, M^-1)``: RGB to the weighted space ``(Y, sqrt(w)Cb, sqrt(w)Cr)`` and back."""
    weight = np.float32(np.sqrt(w_chroma))
    matrix = (_YCC * np.array([[1.0], [weight], [weight]], np.float32)).astype(np.float32)
    return matrix, np.linalg.inv(matrix).astype(np.float32)


def _ring_mask(height: int, width: int, ring: int) -> np.ndarray:
    mask = np.zeros((height, width), bool)
    mask[:ring] = mask[-ring:] = True
    mask[:, :ring] = mask[:, -ring:] = True
    return mask


def estimate_key(rgb: Any, declared: Any = "magenta", ring: int = 8) -> tuple[np.ndarray, dict[str, Any]]:
    """Estimate the key from border pixels near the declared colour.

    Use their median when enough candidates exist and the estimate remains key-like;
    otherwise retain the declared key. Returns the estimate and sampling diagnostics.
    """
    ring = operator.index(ring)
    if ring < 1:
        raise ValueError("ring must be at least 1 px.")
    colour, alpha = _split(rgb)
    model = _key_model(declared)
    pixels = colour.astype(np.float32)
    height, width = pixels.shape[:2]
    opaque = None if alpha is None else alpha >= _OPAQUE
    native = alpha is not None and bool((alpha < 255).any())
    ring_mask = _ring_mask(height, width, min(ring, max(1, height // 2), max(1, width // 2)))
    ring_all = int(ring_mask.sum())
    if opaque is not None:
        ring_mask &= opaque
    samples = pixels[ring_mask].reshape(-1, 3)
    info: dict[str, Any] = {
        "declared": declared if isinstance(declared, str) else _hex(model.rgb),
        "declared_rgb": [int(v) for v in model.rgb],
        "ring_px": int(samples.shape[0]),
        "native_alpha": native,
        "use_native_alpha": False,
    }
    key = model.rgb.copy()
    reason = None
    near = np.sqrt(((samples - model.rgb) ** 2).sum(-1)) <= _KEY_SEARCH if samples.size else np.zeros(0, bool)
    info["near_share"] = float(near.sum() / max(1, ring_all))
    if near.sum() < _MIN_KEY_SHARE * ring_all or not near.any():
        reason = f"fewer than {_MIN_KEY_SHARE:.0%} of the border ring is near the declared key"
    else:
        first = np.median(samples[near], axis=0).astype(np.float32)
        close = np.sqrt(((samples - first) ** 2).sum(-1)) <= KEY_TOLERANCE
        key = np.median(samples[close], axis=0).astype(np.float32)
        if float(_dominance(key, model)) < _MIN_KEY_DOMINANCE:
            reason = f"the border median {_hex(key)} is not key-coloured (dominance below {_MIN_KEY_DOMINANCE:g})"
            key = model.rgb.copy()
    valid = reason is None
    offset = pixels - key
    covered = (offset * offset).sum(-1) <= KEY_TOLERANCE * KEY_TOLERANCE
    considered = opaque if opaque is not None else np.ones((height, width), bool)
    coverage = float((covered & considered).sum() / max(1, int(considered.sum())))
    ring_share = float(np.mean(np.sqrt(((samples - key) ** 2).sum(-1)) <= KEY_TOLERANCE)) if samples.size else 0.0
    if native and (coverage < _MIN_COVERAGE or samples.shape[0] < 0.5 * ring_all):
        info["use_native_alpha"] = True
        reason = "the image has real transparency and almost no key-coloured backdrop"
    info.update({
        "key": [round(float(v), 2) for v in key],
        "source": "native_alpha" if info["use_native_alpha"] else ("border_median" if valid else "declared"),
        "valid": valid,
        "reason": reason,
        "ring_share": ring_share,
        "coverage": coverage,
        "distance_from_declared": round(float(np.sqrt(((key - model.rgb) ** 2).sum())), 2),
    })
    return key, info


def _material_share(rgb: np.ndarray, subject: np.ndarray, model: _KeyModel, min_excess: float) -> float:
    """Share of deep-interior subject pixels (more than 6 px from non-subject) with dominance >= min_excess."""
    deep = subject & (comfyui_forge_core.distance_to(~subject, 6) > 6)
    if not deep.any():
        return 0.0
    return float((_dominance(rgb, model)[deep] >= min_excess).mean())


def key_material_share(rgb: Any, key: Any = None, *, min_excess: float = 8.0,
                       subject_distance: float = 64.0) -> float:
    """Return the share of deep-interior subject pixels dominated by the key colour.

    Subject pixels exceed subject_distance from the key; alpha input also excludes
    transparent pixels. The interior is more than six pixels from non-subject pixels.
    """
    colour, alpha = _split(rgb)
    pixels = colour.astype(np.float32)
    if key is None or (isinstance(key, str) and key.strip().lower() in DECLARED_KEYS):
        key_rgb, _ = estimate_key(rgb, "magenta" if key is None else key)
    else:
        key_rgb = _key_rgb(key)
    model = _key_model(key_rgb)
    subject = np.sqrt(((pixels - key_rgb) ** 2).sum(-1)) >= subject_distance
    if alpha is not None:
        subject &= alpha >= _OPAQUE
    return _material_share(pixels, subject, model, min_excess)


def auto_interior_despill(reference: Any = None, frames: Sequence[Any] = (), *, key: Any = None,
                          sample: int = 16) -> dict[str, Any]:
    """Enable interior despill only when the reference and sampled frames contain
    no significant key-coloured subject material. Returns the decision and diagnostics.
    """
    if reference is None and len(frames) == 0:
        raise ValueError("auto_interior_despill needs a reference still or clip frames.")
    decision: dict[str, Any] = {"rule": f"reference still and clip median key-material share <= "
                                        f"{KEY_MATERIAL_SHARE_MAX:.1%}"}
    enabled = True
    if reference is not None:
        decision["reference_share"] = key_material_share(reference, key)
        enabled &= decision["reference_share"] <= KEY_MATERIAL_SHARE_MAX
    if len(frames):
        count = min(operator.index(sample), len(frames))
        last = len(frames) - 1
        picks = sorted({int(math.floor(k * last / max(1, count - 1) + 0.5)) for k in range(count)})
        shares = [key_material_share(frames[index], key) for index in picks]
        decision.update({"clip_sample_frames": picks, "clip_median_share": float(np.median(shares)),
                         "clip_max_share": float(max(shares))})
        enabled &= decision["clip_median_share"] <= KEY_MATERIAL_SHARE_MAX
    decision["interior_despill"] = bool(enabled)
    return decision


def _subject_pixels(master: np.ndarray, alpha: np.ndarray | None) -> np.ndarray:
    """The master's subject colours: its visible pixels, or, on an opaque master with a uniform
    border colour, the pixels more than 2 px inside that backdrop (the anti-aliased rim is a mix).
    A master that is all backdrop counts as all subject.
    """
    if alpha is not None and (alpha < 255).any():
        return master[alpha >= 128]
    height, width = master.shape[:2]
    ring = _ring_mask(height, width, min(8, max(1, height // 2), max(1, width // 2)))
    samples = master[ring].astype(np.float32)
    backdrop = np.median(samples, axis=0)
    if np.mean(np.sqrt(((samples - backdrop) ** 2).sum(-1)) <= KEY_TOLERANCE) >= 0.5:
        near = np.sqrt(((master.astype(np.float32) - backdrop) ** 2).sum(-1)) <= KEY_TOLERANCE
        inside = comfyui_forge_core.distance_to(near, 2) > 2
        if inside.any():
            return master[inside]
    return master.reshape(-1, 3)


def choose_key_color(master_rgba: Any, candidates: Sequence[Any] = ("magenta", "green", "blue")) -> dict[str, Any]:
    """Choose a backdrop key that does not overlap the master's subject colours.

    Reject candidates exceeding KEY_MATERIAL_SHARE_MAX at OVERLAP_DOMINANCE.
    Returns the chosen key and per-candidate diagnostics.
    """
    colour, alpha = _split(master_rgba)
    subject = _subject_pixels(colour, alpha).astype(np.float32)
    if subject.shape[0] == 0:
        raise ValueError("The master has no visible subject pixels.")
    rows = []
    for candidate in candidates:
        model = _key_model(candidate)
        dominance = _dominance(subject, model)
        share = float(np.mean(dominance >= OVERLAP_DOMINANCE))
        rows.append({
            "key": candidate if isinstance(candidate, str) else _hex(model.rgb),
            "rgb": [int(v) for v in model.rgb],
            "overlap_share": share,
            "material_share": float(np.mean(dominance >= 8.0)),
            "max_dominance": float(dominance.max()),
            "rejected": share > KEY_MATERIAL_SHARE_MAX,
        })
    accepted = [row for row in rows if not row["rejected"]]
    best = accepted[0] if accepted else min(rows, key=lambda row: row["overlap_share"])
    name = best["key"]
    return {
        "key": name,
        "rgb": best["rgb"],
        "hex": _hex(best["rgb"]),
        "status": "ok" if accepted else "conflict",
        "candidates": rows,
        "subject_px": int(subject.shape[0]),
        "rule": (f"reject a key when more than {KEY_MATERIAL_SHARE_MAX:.1%} of subject pixels have key "
                 f"dominance >= {OVERLAP_DOMINANCE:g}; first acceptable candidate wins"),
        "prompt_background": f"perfectly uniform solid {name} ({_hex(best['rgb'])}) background"
                             if name in DECLARED_KEYS else
                             f"perfectly uniform solid {_hex(best['rgb'])} background",
    }


def legacy_hard_key(rgba: Any, threshold: float = 100, edge_threshold: float = 150) -> Image.Image:
    """Binary magenta keying with separate global and border-connected thresholds.

    Pixels within threshold are cleared globally; edge_threshold applies only to
    pixels connected to the border through key-like pixels.
    """
    pixels = _rgba(rgba)
    channels = pixels[..., :3].astype(np.int32)
    squared = (channels[..., 0] - 255) ** 2 + channels[..., 1] ** 2 + (channels[..., 2] - 255) ** 2
    distance = np.sqrt(squared.astype(np.float64))  # correctly rounded, like math.sqrt
    pixels[(pixels[..., 3] != 0) & (distance < threshold)] = 0
    edge = (pixels[..., 3] != 0) & (distance < edge_threshold)
    reached = _border_connected((pixels[..., 3] == 0) | edge, 8)
    pixels[reached & edge] = 0
    return Image.fromarray(pixels)


_LEGACY_MAGENTA = np.array([255, 0, 255], dtype=np.float32)


def legacy_border_flood_key(rgba: Any, dist: float = 55.0, despill: float = 0.0) -> Image.Image:
    """Clear border-connected magenta-like pixels and apply optional edge despill.

    Enclosed key-coloured holes remain opaque; remove_enclosed_pockets handles them.
    """
    if not math.isfinite(despill) or not 0 <= despill <= 1:
        raise ValueError("despill must be between 0 and 1")
    arr = _rgba(rgba)
    channels = arr[:, :, :3].astype(np.float32)
    distance = np.linalg.norm(channels - _LEGACY_MAGENTA, axis=2)
    red, green, blue = channels[:, :, 0], channels[:, :, 1], channels[:, :, 2]
    pinkish = (red > 160) & (blue > 160) & (green < 140) & ((red + blue) / 2 - green > 40)
    visited = _border_connected((distance <= dist) | pinkish, 4)

    out = arr.copy()
    out[visited, 3] = 0
    adjacent = np.zeros_like(visited)
    adjacent[1:] |= visited[:-1]
    adjacent[:-1] |= visited[1:]
    adjacent[:, 1:] |= visited[:, :-1]
    adjacent[:, :-1] |= visited[:, 1:]
    if despill:
        # The first visible ring only; RGB is still the input's, so its float channels are reused.
        ys, xs = np.nonzero(~visited & adjacent & (out[:, :, 3] > 0))
        near = channels[ys, xs]
        spill = np.maximum(0, np.minimum(near[:, 0], near[:, 2]) - near[:, 1])
        fringe = spill > 20
        if fringe.any():
            ys, xs = ys[fringe], xs[fringe]
            ring = out[ys, xs].astype(np.float32)
            amount = spill[fringe] * despill
            ring[:, 0] = np.clip(ring[:, 0] - amount, 0, 255)
            ring[:, 2] = np.clip(ring[:, 2] - amount, 0, 255)
            out[ys, xs] = ring.astype(np.uint8)
    out[out[:, :, 3] == 0, :3] = 0
    return Image.fromarray(out, "RGBA")


def _local_key(pixels: np.ndarray, background: np.ndarray, key: np.ndarray, radius: int) -> np.ndarray:
    """B(x): mean colour of the background pixels within ``radius`` (Chebyshev); ``key`` where there are none."""
    count = _box_sum(background.astype(np.float64), radius)  # float64 input: exact whole-frame sums
    local = np.empty(pixels.shape, np.float32)
    for channel in range(3):
        total = _box_sum(np.where(background, pixels[..., channel], 0.0).astype(np.float64), radius)
        local[..., channel] = np.where(count > 0, total / np.maximum(count, 1.0), key[channel])
    return local


def _clamp_excess(rgb: np.ndarray, limit: np.ndarray, where: np.ndarray, model: _KeyModel) -> np.ndarray:
    """Clamp key dominance to ``limit`` on ``where``, preserving BT.601 luma (v13 ``_despill``)."""
    excess = _dominance(rgb, model)
    cut = np.where(where, np.maximum(0.0, excess - limit), 0.0).astype(np.float32)
    out = rgb.copy()
    for channel in model.high:
        out[..., channel] -= cut
    out += (model.luma_gain * cut)[..., None]
    return np.clip(out, 0.0, 255.0)


def _finish(alpha: np.ndarray, colour: np.ndarray, native: np.ndarray | None) -> np.ndarray:
    alpha8 = np.round(alpha * 255.0).astype(np.uint8)
    if native is not None:
        np.minimum(alpha8, native, out=alpha8)
    rgba = np.dstack([np.round(colour).astype(np.uint8), alpha8])
    rgba[alpha8 == 0, :3] = 0
    return rgba


def soft_matte(rgb: Any, params: KeyParams = KeyParams(), key: Any = None, *,
               local_background: bool | int = False, protect: Any = None,
               return_debug: bool = False) -> np.ndarray | tuple[np.ndarray, dict[str, Any]]:
    """Known-key soft matte of a flat chroma backdrop.

    Model: each observed pixel is ``C = a*F + (1-a)*K`` of a subject colour F
    and the known key K. Decoded H.264/VP9 frames are 4:2:0 and the encoder
    smears key chroma 3-4 px into the subject, so matting runs in the weighted
    space ``S = (Y, sqrt(w)Cb, sqrt(w)Cr)`` (w = ``w_chroma``) and colours are
    cleaned over a wider band (``r_c``) than alpha is softened (``r_a``):

    1. background: ``|S(C)-S(K)| <= t_bg``, or a strongly key-leaning pixel
       still within ``t_fg`` (haze, glow and blur painted into the backdrop).
       Enclosed key holes are background too.
    2. alpha zone: non-background pixels within ``r_a`` px of background, plus
       any within ``t_fg`` of K. Alpha is the projection onto line-consistent
       candidates farther from the background (soft-min over ``radius`` px);
       without a candidate, 1 for the subject's own extremes, else 0.
    3. alpha never drops stepping inward (``monotone``).
    4. colour: candidate chroma at the un-mixed luma ``Y_K + (Y_C - Y_K)/a``.
    5. colour-clean band (``r_c`` px): key dominance is clamped to the local
       deep-interior excess + ``excess_slack``, luma preserved, so a purple
       subject keeps its purple. ``interior_despill`` clamps every visible
       pixel instead; decide it per clip with auto_interior_despill.
    6. specks: alpha > 0 survives only within ``speck_steps`` 8-steps of
       alpha >= 0.5.

    ``key``: None or a declared name estimates it from the border ring
    (estimate_key); ``#rrggbb`` or an RGB triple is used as given. With a
    ``local_background`` value (True = 12 px, or a radius), re-matte against
    B(x), the mean background colour within that radius. This adapts edge
    un-mixing to a drifting or vignetted backdrop, but not bright glow in
    narrow gaps because B(x) samples the surrounding backdrop. ``protect`` (a
    boolean mask, see protect_mask) marks design pixels that are never
    background, zone or despill pixels; they stay opaque and serve as
    candidates. Light purples within ``t_fg`` of magenta at the video weight,
    such as (180, 60, 200), are keyed out unless protected. RGBA input keeps
    its own alpha as an upper bound. Returns RGBA uint8, plus a debug dict
    with ``return_debug``.
    """
    colour, native = _split(rgb)
    p = params
    C = colour.astype(np.float32)
    h, w = C.shape[:2]
    if key is None or (isinstance(key, str) and key.strip().lower() in DECLARED_KEYS):
        K, _ = estimate_key(colour, "magenta" if key is None else key)
    else:
        K = _key_rgb(key)
    model = _key_model(K)
    guard = _mask(protect, (h, w), "protect")
    M, Minv = _matting_space(p.w_chroma)
    S = C @ M.T
    SK = K @ M.T
    D = S - SK
    dW = np.sqrt((D * D).sum(-1))
    m_C = _dominance(C, model)
    m_K = float(_dominance(K, model))
    bg = (dW <= p.t_bg) | ((m_C >= p.keylike * m_K) & (dW < p.t_fg))
    radius_lb = LOCAL_BACKGROUND_RADIUS if local_background is True else operator.index(local_background)
    if radius_lb < 0:
        raise ValueError("local_background must be False, True or a radius >= 1.")
    SKmap = None
    if radius_lb:
        if guard is not None:
            bg &= ~guard
        local = _local_key(C, bg, K, radius_lb)
        SKmap = local @ M.T
        D = S - SKmap
        dW = np.sqrt((D * D).sum(-1))
        bg = (dW <= p.t_bg) | ((m_C >= p.keylike * _dominance(local, model)) & (dW < p.t_fg))
    if guard is not None:
        bg &= ~guard
    dist = comfyui_forge_core.distance_to(bg, max(p.r_c, p.r_a + p.radius))
    zone_a = (~bg) & ((dist <= p.r_a) | (dW < p.t_fg))
    if guard is not None:
        zone_a &= ~guard
    subject_like = dW >= p.t_fg if guard is None else (dW >= p.t_fg) | guard

    alpha = (~bg).astype(np.float32)
    out = C.copy()

    ys, xs = np.nonzero(zone_a)
    n = len(ys)
    SKu = SK if SKmap is None else SKmap[ys, xs]
    Du = D[ys, xs]
    du = dW[ys, xs]
    dp = dist[ys, xs]
    wsum = np.zeros(n, np.float32)
    asum = np.zeros(n, np.float32)
    csum = np.zeros((n, 3), np.float32)
    allow = p.tau + p.kappa * du
    for dy, dx in _disk(p.radius):
        yy = np.clip(ys + dy, 0, h - 1)
        xx = np.clip(xs + dx, 0, w - 1)
        ok = (dist[yy, xx] > dp) & subject_like[yy, xx]
        if not ok.any():
            continue
        V = D[yy, xx] if SKmap is None else S[yy, xx] - SKu
        a = (Du * V).sum(-1) / np.maximum((V * V).sum(-1), 1e-3)
        R = Du - a[:, None] * V
        res = np.sqrt((R * R).sum(-1))
        ok &= (a > 0.0) & (a <= 1.0) & (res <= allow)
        wgt = np.where(ok, np.exp(-np.clip(a, 0.0, 1.0) / p.temp), 0.0).astype(np.float32)
        wsum += wgt
        asum += wgt * a
        csum += wgt[:, None] * C[yy, xx]
    have = wsum > 0
    a_nc = np.where(du >= p.t_fg, 1.0, 0.0)  # no candidate: the subject's own extreme, or smear/haze
    a = np.where(have, asum / np.maximum(wsum, 1e-30), a_nc).astype(np.float32)
    if p.snap == "ramp":
        a = np.clip((a - p.a_lo) / (p.a_hi - p.a_lo), 0.0, 1.0).astype(np.float32)
    else:
        a = np.where(a < p.a_lo, 0.0, np.where(a > p.a_hi, 1.0, a)).astype(np.float32)
    Fh = np.where(have[:, None], csum / np.maximum(wsum, 1e-30)[:, None], C[ys, xs])
    alpha[ys, xs] = a

    if p.monotone:
        for k in range(2, p.r_a + 1):
            prev = np.where(dist == k - 1, alpha, 0.0).astype(np.float32)
            lvl = zone_a & (dist == k)
            alpha[lvl] = np.maximum(alpha[lvl], _box_max(prev, 1)[lvl])
        a = alpha[ys, xs]

    if p.refine == "guided" and n:
        y0, y1 = max(0, int(ys.min()) - 8), min(h, int(ys.max()) + 9)
        x0, x1 = max(0, int(xs.min()) - 8), min(w, int(xs.max()) + 9)
        guide = (S[y0:y1, x0:x1, 0] / 255.0).astype(np.float32)
        filtered = _guided_filter(guide, alpha[y0:y1, x0:x1].astype(np.float32), p.gf_r, p.gf_eps)
        za = zone_a[y0:y1, x0:x1]
        sub = alpha[y0:y1, x0:x1]
        sub[za] = np.clip(filtered[za], 0.0, 1.0)
        alpha[y0:y1, x0:x1] = np.where(sub < p.a_lo, 0.0, np.where(sub > p.a_hi, 1.0, sub))
        a = alpha[ys, xs]

    # colour: candidate chroma, luma from the exact un-mix as alpha rises
    SF = Fh @ M.T
    Yu = (SK[0] if SKmap is None else SKu[:, 0]) + Du[:, 0] / np.maximum(a, 1e-3)
    s = np.clip((a - p.unmix_from) / max(1e-6, 1.0 - p.unmix_from), 0.0, 1.0)
    Yo = np.clip(SF[:, 0] + s * (Yu - SF[:, 0]), 0.0, 255.0)
    out[ys, xs] = np.clip(np.stack([Yo, SF[:, 1], SF[:, 2]], -1) @ Minv.T, 0.0, 255.0)

    deep = (~bg) & (dist > p.r_c)
    num = _box_sum(np.where(deep, np.maximum(m_C, 0.0), 0.0).astype(np.float32), p.ref_r)
    den = _box_sum(deep.astype(np.float32), p.ref_r)
    lim = num / np.maximum(den, 1.0) + p.excess_slack
    zone_c = (alpha > 0) & (dist <= p.r_c)
    if p.interior_despill:
        zone_c = alpha > 0
        lim = np.full_like(lim, p.excess_slack)
    if guard is not None:
        zone_c &= ~guard
    out = _clamp_excess(out, lim, zone_c, model)

    if p.speck_steps > 0:
        keep = alpha >= 0.5
        pos = alpha > 0
        for _ in range(p.speck_steps):
            keep = _grow(keep) & pos
        alpha[pos & ~keep] = 0.0

    rgba = _finish(alpha, out, native)
    if return_debug:
        return rgba, {"K": [round(float(v), 2) for v in K], "zone_a_px": int(n),
                      "no_candidate_px": int((~have).sum()), "bg_px": int(bg.sum()),
                      "local_background": int(radius_lb),
                      "protected_px": 0 if guard is None else int(guard.sum())}
    return rgba


# Region matting falls back to a whole-sheet pass when crops cannot preserve exact sums.
_REGION_TILE = 16              # px: content is found on this tile grid
_REGION_MARGIN = 32            # px of context around each group of content tiles
_REGION_MAX_GROUPS = 64        # more groups (a noisy backdrop) cost more in per-call overhead than they save
_REGION_MAX_SHARE = 0.75       # crops covering this share of the sheet: one whole-sheet call is cheaper
_FLOAT32_EXACT_SUM = 2.0 ** 24  # float32 sums of whole numbers are exact up to this total


def _soft_matte_reach(params: KeyParams) -> int:
    """Farthest pixel (Chebyshev px) whose input can change a pixel's soft_matte output.

    The capped distance to background reaches ``cap``; candidates look
    ``radius`` px further; the inward monotone pass adds ``r_a - 1``; speck
    removal adds ``speck_steps``; the colour-clean reference adds ``ref_r``
    to the distance. 17 px for both KeyParams() and STILL_KEY_PARAMS.
    """
    cap = max(params.r_c, params.r_a + params.radius)
    return cap + max(params.ref_r, params.radius + params.r_a - 1 + params.speck_steps)


def _float32_sums_exact(colour: np.ndarray, content: np.ndarray, model: _KeyModel, params: KeyParams,
                        crops: Sequence[tuple[int, int, int, int]]) -> bool:
    """True when every float32 integral image of soft_matte's colour-clean band is exact.

    The band's limit comes from box sums of float32 integral images of the
    deep subject's positive key dominance (whole numbers) and of the deep
    pixel count. While their totals stay at or below 2**24 those sums are
    exact and independent of where the image starts; above it the whole sheet
    and a crop round differently (seen: 5 px on a 1536 px sheet of pink
    subjects). Deep pixels are ``content`` (``content`` holds every
    non-background pixel), so all content bounds the sheet and every crop;
    when that bound is too loose, the deep pixels are bounded by content
    more than ``r_c`` px from non-content (sure background) on the sheet, and
    each crop by its own content.
    """
    dominance = np.maximum(_dominance(colour[content].astype(np.int16), model), 0)  # whole numbers, content only
    if int(dominance.sum(dtype=np.int64)) <= _FLOAT32_EXACT_SUM and dominance.size <= _FLOAT32_EXACT_SUM:
        return True  # a crop never holds more content than the sheet
    positive = np.zeros(content.shape, np.int16)
    positive[content] = dominance
    deep_bound = content & ~comfyui_forge_core.dilate_square(~content, params.r_c)
    if (int(positive[deep_bound].sum(dtype=np.int64)) > _FLOAT32_EXACT_SUM
            or np.count_nonzero(deep_bound) > _FLOAT32_EXACT_SUM):
        return False
    return all(int(positive[y0:y1, x0:x1].sum(dtype=np.int64)) <= _FLOAT32_EXACT_SUM
               and np.count_nonzero(content[y0:y1, x0:x1]) <= _FLOAT32_EXACT_SUM for x0, y0, x1, y1 in crops)


def soft_matte_regions(rgb: Any, params: KeyParams = KeyParams(), key: Any = None) -> np.ndarray:
    """``soft_matte(rgb, params, key)``, byte for byte, matting only the parts of a sheet that hold content.

    A pixel within ``t_bg / ||M||_F`` (RGB distance) of the key, or with
    alpha 0, always comes out (0, 0, 0, 0), and every soft-matte step is
    local (at most _soft_matte_reach, 17 px, away). So content is found on a
    16 px tile grid, each 8-connected group of content tiles is matted inside
    its box plus a 32 px margin, and only the group's own tiles are copied
    back. One whole-sheet call is made instead when that cannot be faster or
    exact: more than 64 groups (a noisy backdrop), crops covering 75% of the
    sheet, ``refine="guided"``, a reach beyond the margin, or float32 sums of
    the colour-clean band that could round (see _float32_sums_exact). On the
    2048 px 4x4 perf sheet about half the area is matted. ``key`` None or a
    declared name is estimated from the whole image's colour, as soft_matte
    does. local_background and protect are not offered; use soft_matte.
    """
    pixels = _pixels(rgb)
    colour = pixels[..., :3]
    if key is None or (isinstance(key, str) and key.strip().lower() in DECLARED_KEYS):
        K, _ = estimate_key(colour, "magenta" if key is None else key)
    else:
        K = _key_rgb(key)
    p = params
    height, width = colour.shape[:2]
    if p.refine != "none" or _soft_matte_reach(p) > _REGION_MARGIN or not height or not width:
        return soft_matte(pixels, p, K)
    M, _ = _matting_space(p.w_chroma)
    safe = 0.999 * p.t_bg / float(np.sqrt(np.square(M.astype(np.float64)).sum()))  # |M v| <= ||M||_F |v|
    squares = np.square(np.arange(256, dtype=np.float32)[:, None] - K)  # (c - K)^2 per channel value
    distance2 = squares[colour[..., 0], 0] + squares[colour[..., 1], 1] + squares[colour[..., 2], 2]
    content_rgb = distance2 > np.float32(safe * safe)  # False: within safe of the key, so surely background
    content = content_rgb if pixels.shape[2] == 3 else content_rgb & (pixels[..., 3] > 0)
    tile = _REGION_TILE
    tiles_y, tiles_x = -(-height // tile), -(-width // tile)
    padded = np.zeros((tiles_y * tile, tiles_x * tile), bool)
    padded[:height, :width] = content
    tile_mask = padded.reshape(tiles_y, tile, tiles_x, tile).any(axis=(1, 3))
    if not tile_mask.any():
        return np.zeros((height, width, 4), np.uint8)
    labels, count = comfyui_forge_core.label_components(tile_mask, 8)
    if count > _REGION_MAX_GROUPS:
        return soft_matte(pixels, p, K)
    groups = []
    for label in range(1, count + 1):
        rows, cols = np.nonzero(labels == label)
        tiles = (int(cols.min()), int(rows.min()), int(cols.max()) + 1, int(rows.max()) + 1)
        box = (max(0, tiles[0] * tile - _REGION_MARGIN), max(0, tiles[1] * tile - _REGION_MARGIN),
               min(width, tiles[2] * tile + _REGION_MARGIN), min(height, tiles[3] * tile + _REGION_MARGIN))
        groups.append((label, tiles, box))
    if sum((x1 - x0) * (y1 - y0) for _label, _tiles, (x0, y0, x1, y1) in groups) >= _REGION_MAX_SHARE * height * width:
        return soft_matte(pixels, p, K)
    if not p.interior_despill and not _float32_sums_exact(colour, content_rgb, _key_model(K), p,
                                                          [box for _label, _tiles, box in groups]):
        return soft_matte(pixels, p, K)  # interior despill replaces the band's limit by a constant: always exact
    out = np.zeros((height, width, 4), np.uint8)
    for label, (tx0, ty0, tx1, ty1), (x0, y0, x1, y1) in groups:
        keyed = soft_matte(pixels[y0:y1, x0:x1], p, K)
        own = np.repeat(np.repeat(labels[ty0:ty1, tx0:tx1] == label, tile, axis=0), tile, axis=1)
        top, left = ty0 * tile, tx0 * tile
        own = own[:height - top, :width - left]
        region = out[top:top + own.shape[0], left:left + own.shape[1]]
        source = keyed[top - y0:top - y0 + own.shape[0], left - x0:left - x0 + own.shape[1]]
        np.copyto(region, source, where=own[..., None])
    return out


def dominance_matte(rgb: Any, key: Any = "magenta", lo: float = 20.0, hi: float = 140.0, *,
                    protect: Any = None) -> np.ndarray:
    """Compute soft alpha from key-channel dominance.

    Alpha is clip((hi - dominance) / (hi - lo)); pure-key pixels are cleared.
    Optional spill repair changes visible RGB without adding coverage.
    """
    if not hi > lo:
        raise ValueError("dominance_matte needs hi > lo.")
    colour, native = _split(rgb)
    model = _key_model(key)
    a = colour.astype(np.float32)
    dom = _dominance(a, model)
    alpha = np.clip((hi - dom) / (hi - lo), 0, 1)
    pure = np.ones(dom.shape, bool)
    for channel in model.high:
        pure &= a[..., channel] > 145
    for channel in model.low:
        pure &= a[..., channel] < 30
    alpha[pure] = 0
    guard = _mask(protect, dom.shape, "protect")
    if guard is not None:
        alpha[guard] = 1
    excess = np.maximum(0, dom)
    for channel in model.high:
        a[..., channel] = np.where(alpha < .995, a[..., channel] - excess, a[..., channel])
    rgba = np.dstack((np.clip(a, 0, 255), np.rint(alpha * 255))).astype(np.uint8)
    if native is not None:
        np.minimum(rgba[..., 3], native, out=rgba[..., 3])
    rgba[rgba[..., 3] == 0, :3] = 0
    return rgba


def _key_pockets(rgba: np.ndarray, key_rgb: np.ndarray, min_area: int, max_dist: float) -> tuple[np.ndarray, int]:
    """Visible key-coloured regions: 8-connected pixels within ``2 * max_dist`` of the key that hold
    at least ``min_area`` pixels within ``max_dist`` (so codec noise inside a hole goes with it).
    """
    visible = rgba[..., 3] > 0
    distance = np.sqrt(((rgba[..., :3].astype(np.float32) - key_rgb) ** 2).sum(-1))
    loose = visible & (distance <= 2 * max_dist)
    labels, count = comfyui_forge_core.label_components(loose, 8)
    if count == 0:
        return np.zeros(visible.shape, bool), 0
    seeds = np.bincount(labels[visible & (distance <= max_dist)], minlength=count + 1)
    pocket = seeds >= max(1, min_area)
    pocket[0] = False
    return pocket[labels], int(pocket.sum())


def remove_enclosed_pockets(rgba: Any, key: Any, min_area: int = 16,
                            max_dist: float = 24.0) -> tuple[np.ndarray, int]:
    """Clear key-coloured regions a matte left visible, such as holes no border flood reached.

    A pocket is an 8-connected region of visible pixels within ``2 * max_dist``
    (RGB) of ``key`` holding at least ``min_area`` pixels within ``max_dist``;
    it becomes (0, 0, 0, 0). Pass the key the matte used (estimate_key); a
    name means the declared colour. Returns ``(rgba, pockets_removed)``.
    """
    pixels = _rgba(rgba)
    pockets, count = _key_pockets(pixels, _key_rgb(key), operator.index(min_area), float(max_dist))
    pixels[pockets] = 0
    return pixels, count


def despill(rgba: Any, mode: str = "edge", radius: int = 1, margin: int = 12, protect: Any = None, *,
            key: Any = "magenta") -> tuple[np.ndarray, dict[str, Any]]:
    """Remove key spill from visible pixels; alpha never changes.

    Where a pixel's key dominance exceeds ``margin`` it is subtracted from the
    key channels (magenta: R and B), leaving a neutral colour. ``edge`` treats
    pixels within ``radius`` px (Chebyshev; the canvas exterior is not
    transparency) of alpha 0 and is bit-identical to the sprite skill's
    ``despill_chroma_edges`` for margin 12 and radius 0-3. ``all`` treats every
    visible pixel; ``auto`` picks ``all`` when the subject owns no
    key-coloured material (deep-interior share <= 0.5%), else ``edge``;
    ``off`` copies. ``protect`` pixels are never changed. Real purple art at
    an edge cannot be told from spill without ``protect``.

    Returns ``(rgba, report)``; the report holds ``mode``, ``applied``,
    ``radius``, ``margin``, ``changed_px`` and, for auto, ``key_material_share``.
    """
    if mode not in DESPILL_MODES:
        raise ValueError(f"Unknown despill mode {mode!r}; use one of {', '.join(DESPILL_MODES)}.")
    if isinstance(radius, bool) or operator.index(radius) < 0:
        raise ValueError("Despill radius must be an integer >= 0.")
    pixels = _rgba(rgba)
    model = _key_model(key)
    alpha = pixels[..., 3]
    report: dict[str, Any] = {"mode": mode, "applied": mode, "radius": int(radius), "margin": margin,
                              "changed_px": 0}
    guard = _mask(protect, alpha.shape, "protect")
    if mode == "auto":
        subject = alpha == 255 if guard is None else (alpha == 255) & ~guard
        share = _material_share(pixels[..., :3].astype(np.float32), subject, model, 8.0)
        report["key_material_share"] = share
        report["applied"] = "all" if share <= KEY_MATERIAL_SHARE_MAX else "edge"
    applied = report["applied"]
    if applied == "off":
        return pixels, report
    if applied == "edge":
        transparent = alpha == 0
        if radius == 0 or not transparent.any():
            return pixels, report
        region = comfyui_forge_core.dilate_square(transparent, int(radius)) & (alpha > 0)
    else:
        region = alpha > 0
    channels = pixels[..., :3].astype(np.int16)
    excess = _dominance(channels, model)
    affected = region & (excess > margin)
    if guard is not None:
        affected &= ~guard
    for channel in model.high:
        pixels[..., channel][affected] = (channels[..., channel][affected] - excess[affected]).astype(np.uint8)
    report["changed_px"] = int(affected.sum())
    return pixels, report


def _parse_colours(colors: Any) -> np.ndarray:
    if isinstance(colors, str) or (len(colors) == 3 and all(
            isinstance(v, (int, float, np.integer, np.floating)) for v in colors)):
        colors = [colors]
    return np.stack([_key_rgb(colour) for colour in colors]).astype(np.float32)


def protect_mask(rgb: Any, colors: Any, tol: float = 0.03) -> np.ndarray:
    """Pixels within OKLab distance ``tol`` of any listed design colour (``#rrggbb`` or RGB).

    Pass the mask as ``protect=`` to soft_matte, dominance_matte or despill so
    a design colour near the key (for example #972fbf against magenta) is
    never keyed or despilled.
    """
    colour, _ = _split(rgb)
    palette = _to_oklab(_parse_colours(colors))
    lab = _to_oklab(colour)
    mask = np.zeros(colour.shape[:2], bool)
    for entry in palette:
        mask |= ((lab - entry) ** 2).sum(-1) <= tol * tol
    return mask


def _sphere(count: int) -> np.ndarray:
    """``count`` unit vectors spread evenly over the sphere (Fibonacci lattice), float32."""
    index = np.arange(count) + 0.5
    z = 1.0 - 2.0 * index / count
    radius = np.sqrt(1.0 - z * z)
    angle = np.pi * (3.0 - np.sqrt(5.0)) * index
    return np.stack([radius * np.cos(angle), radius * np.sin(angle), z], axis=-1).astype(np.float32)


def protect_design_colours(rgb: Any, key: Any, *, params: KeyParams = KeyParams(),
                           margin: float = 8.0) -> tuple[np.ndarray, dict[str, Any]]:
    """Move design colours the soft keyer would eat just out of its reach, with the least visible change.

    A colour is at risk when its weighted matting distance to the key (the
    soft_matte space of ``params``) is below ``t_fg + margin``: soft_matte
    would treat it as partial alpha or background, as it does with #972fbf or
    (180, 60, 200) against magenta at the video weight. Each at-risk colour
    moves to the nearest 8-bit colour, by OKLab distance, at that matting
    distance; 257 directions are searched per colour (masa_dragon_rekey
    protect, generalised). Use it on a master's subject pixels before they
    meet the key: with alpha only visible pixels change, without alpha every
    pixel counts as subject. Alpha never changes.

    Returns ``(pixels, report)``; the report lists ``changed_px`` and one row
    per colour with ``from``, ``to``, ``px`` and the OKLab ``delta_e``.
    """
    pixels = _pixels(rgb).copy()
    colour = pixels[..., :3]
    visible = pixels[..., 3] > 0 if pixels.shape[2] == 4 else np.ones(colour.shape[:2], bool)
    key_rgb = _key_rgb(key)
    M, Minv = _matting_space(params.w_chroma)
    target = float(params.t_fg + margin)
    report: dict[str, Any] = {"key": _hex(key_rgb), "target_distance": target, "changed_px": 0,
                              "colors": [], "unprotectable": []}
    if not visible.any():
        return pixels, report
    unique, inverse = np.unique(colour[visible], axis=0, return_inverse=True)
    inverse = inverse.reshape(-1)
    SK = key_rgb @ M.T
    D = unique.astype(np.float32) @ M.T - SK
    risky = np.flatnonzero(np.sqrt((D * D).sum(-1)) < target)
    if risky.size == 0:
        return pixels, report
    directions = _sphere(256)
    lab = _to_oklab(unique[risky].astype(np.float32))
    lifted = unique.astype(np.float32).copy()
    blocked = []
    for row, index in enumerate(risky):
        d = D[index]
        units = np.vstack([directions, d / max(float(np.sqrt(d @ d)), 1e-6)])
        along = units @ d
        reach = target + 0.75  # rounding to 8 bits moves at most ~0.75 in the matting space
        step = -along + np.sqrt(np.maximum(along * along - d @ d + reach * reach, 0.0))
        trial = np.floor((SK + d + step[:, None] * units) @ Minv.T + 0.5)
        inside = (trial >= 0).all(-1) & (trial <= 255).all(-1)
        offset = trial @ M.T - SK
        inside &= np.sqrt((offset * offset).sum(-1)) >= target
        if not inside.any():
            blocked.append(index)
            continue
        cost = ((_to_oklab(np.clip(trial, 0, 255)) - lab[row]) ** 2).sum(-1)
        lifted[index] = trial[np.flatnonzero(inside)[np.argmin(cost[inside])]]
    changed = np.zeros(len(unique), bool)
    changed[risky] = True
    changed[blocked] = False
    flat = colour[visible]
    moved = changed[inverse]
    flat[moved] = lifted.astype(np.uint8)[inverse][moved]
    colour[visible] = flat
    counts = np.bincount(inverse, minlength=len(unique))
    delta = np.sqrt(((_to_oklab(lifted) - _to_oklab(unique.astype(np.float32))) ** 2).sum(-1))
    for index in np.flatnonzero(changed):
        report["colors"].append({"from": _hex(unique[index]), "to": _hex(lifted[index]),
                                 "px": int(counts[index]), "delta_e": round(float(delta[index]), 4)})
    report["unprotectable"] = [_hex(unique[index]) for index in blocked]
    report["changed_px"] = int(counts[changed].sum())
    return pixels, report


def matte_qa(rgba: Any, key: Any, *, key_tolerance: float = KEY_TOLERANCE, spill_threshold: float = 20.0,
             min_pocket_area: int = 16) -> dict[str, Any]:
    """Key-residue metrics of a keyed RGBA image, for gates and matte_report.v1.

    ``opaque_key_px``: pixels with alpha >= 128 within ``key_tolerance`` (RGB)
    of the key. ``outer_ring_spill_fraction``: share of the outer visible ring
    (visible pixels with a transparent or off-canvas 4-neighbour) whose
    straight colour has key dominance above ``spill_threshold`` (legacy binary keyer:
    about 0.70; target <= 0.01). ``semitransparent_fraction``: share of visible
    pixels with 0 < alpha < 255. ``enclosed_key_pockets``: visible key-coloured
    regions of at least ``min_pocket_area`` px (remove_enclosed_pockets rule,
    ``max_dist`` = key_tolerance / 2). Also ``key_hued_px`` (alpha >= 128 and
    dominance >= 100: glow or design colour; informational), ``visible_px``,
    ``outer_ring_px`` and the thresholds. Pass the key the matte used.
    """
    pixels = _rgba(rgba)
    key_rgb = _key_rgb(key)
    model = _key_model(key_rgb)
    alpha = pixels[..., 3]
    colour = pixels[..., :3].astype(np.float32)
    visible = alpha > 0
    opaque = alpha >= 128
    distance = np.sqrt(((colour - key_rgb) ** 2).sum(-1))
    dominance = _dominance(colour, model)
    key_hue = dominance > spill_threshold
    if len(model.high) == 2:
        # Spill of a two-channel key keeps its channels balanced (magenta: R close to B). A deep
        # crimson such as (186, 12, 33) also beats G by more than the threshold, but it is a
        # design colour, not key spill.
        first, second = colour[..., model.high[0]], colour[..., model.high[1]]
        balance = np.minimum(first, second) / np.maximum(np.maximum(first, second), 1.0)
        key_hue &= balance >= SPILL_HUE_BALANCE
    padded = np.pad(visible, 1)
    inner = padded[1:-1, 1:-1] & padded[:-2, 1:-1] & padded[2:, 1:-1] & padded[1:-1, :-2] & padded[1:-1, 2:]
    ring = visible & ~inner
    _, pockets = _key_pockets(pixels, key_rgb, min_pocket_area, key_tolerance / 2.0)
    visible_px = int(visible.sum())
    return {
        "key": [round(float(v), 2) for v in key_rgb],
        "opaque_key_px": int((opaque & (distance <= key_tolerance)).sum()),
        "outer_ring_spill_fraction": float(key_hue[ring].mean()) if ring.any() else 0.0,
        "semitransparent_fraction": float(((alpha > 0) & (alpha < 255)).sum() / visible_px) if visible_px else 0.0,
        "enclosed_key_pockets": pockets,
        "key_hued_px": int((opaque & key_hue & (dominance >= 100)).sum()),
        "visible_px": visible_px,
        "outer_ring_px": int(ring.sum()),
        "thresholds": {"key_tolerance": key_tolerance, "spill_threshold": spill_threshold,
                       "min_pocket_area": min_pocket_area, "opaque_alpha": 128,
                       "spill_hue_balance": SPILL_HUE_BALANCE},
        "method": ("forge_matte.matte_qa v1: straight-colour key distance and dominance on the keyed image; "
                   "two-channel keys count spill only where the key channels are balanced"),
    }


def key_still(rgba: Any, quality: str = "auto", key: Any = "auto", resampler_hint: str = "lanczos", *,
              threshold: float = 100, edge_threshold: float = 150) -> tuple[Image.Image, dict[str, Any]]:
    """Key a generated still (sprite sheet, prop pack, master) in one call.

    ``quality``: ``hard`` is legacy_hard_key (binary alpha, the legacy sprite
    keyer; magenta-family keys only) with its #FF00FF distances ``threshold``
    and ``edge_threshold`` (keyword-only, default 100 and 150, recorded in
    ``info["thresholds"]``); ``soft`` is soft_matte with ``STILL_KEY_PARAMS``
    (w_chroma 1.0, r_c 3: stills have full-resolution chroma) and interior
    despill when the image owns no key-coloured material, computed by
    soft_matte_regions (D15: the same bytes, matting only the parts of a sheet
    that hold content); ``dominance`` is dominance_matte; ``auto`` is soft
    unless ``resampler_hint`` is ``nearest`` (pixel art keeps binary alpha).
    ``key``: ``auto`` estimates a magenta backdrop, a declared name estimates
    that key, ``#rrggbb`` or RGB is used as given. An image with real
    transparency and no key backdrop is returned unchanged (quality
    ``native_alpha``). RGBA input keeps its alpha as an upper bound.

    Returns ``(image, info)``: ``info`` holds ``quality``,
    ``requested_quality``, ``key``, ``key_estimate``, the soft-matte
    ``params``, ``interior_despill``, ``key_material_share``, ``thresholds``
    (hard only) and ``qa`` (matte_qa of the result).
    """
    if quality not in KEY_QUALITIES:
        raise ValueError(f"Unknown key quality {quality!r}; use one of {', '.join(KEY_QUALITIES)}.")
    if resampler_hint not in comfyui_forge_core.RESAMPLERS:
        raise ValueError(f"Unknown resampler {resampler_hint!r}; use one of {', '.join(comfyui_forge_core.RESAMPLERS)}.")
    pixels = _rgba(rgba)
    resolved = quality if quality != "auto" else ("hard" if resampler_hint == "nearest" else "soft")
    named = isinstance(key, str) and key.strip().lower() in (*DECLARED_KEYS, "auto")
    estimate = None
    if named:
        declared = "magenta" if key.strip().lower() == "auto" else key.strip().lower()
        key_rgb, estimate = estimate_key(pixels, declared)
    else:
        key_rgb = _key_rgb(key)
    info: dict[str, Any] = {"quality": resolved, "requested_quality": quality, "resampler_hint": resampler_hint,
                            "key": [round(float(v), 2) for v in key_rgb], "key_estimate": estimate}
    if estimate is not None and estimate["use_native_alpha"]:
        info["quality"] = "native_alpha"
        info["qa"] = matte_qa(pixels, key_rgb)
        return Image.fromarray(pixels), info
    if resolved == "hard":
        if _key_model(key_rgb).high != (0, 2):
            raise ValueError("hard keying is the legacy magenta keyer; use soft or dominance for other keys.")
        # #FF00FF distances whatever the key; QA below uses the backdrop key
        keyed = np.asarray(legacy_hard_key(pixels, threshold, edge_threshold))
        info["thresholds"] = {"threshold": threshold, "edge_threshold": edge_threshold}
    elif resolved == "dominance":
        keyed = dominance_matte(pixels, key_rgb)
    else:
        share = key_material_share(pixels, key_rgb)
        params = KeyParams(**{**STILL_KEY_PARAMS.to_dict(), "interior_despill": share <= KEY_MATERIAL_SHARE_MAX})
        keyed = soft_matte_regions(pixels, params, key_rgb)
        info.update({"params": params.to_dict(), "interior_despill": params.interior_despill,
                     "key_material_share": share})
    info["qa"] = matte_qa(keyed, key_rgb)
    return Image.fromarray(keyed), info
