"""OKLab palette construction and animation quantization.

Images use 8-bit straight-alpha RGBA. Index maps use uint8 with a reserved
transparent index. Distances are Euclidean OKLab; ties use the lowest index.
Canonical copies and skill destinations are listed in shared/VENDORED.json.
"""

from __future__ import annotations

import dataclasses
import functools
import io
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from PIL import Image

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import comfyui_forge_core  # noqa: E402  (the sibling copy: shared/ or the skill's scripts/)

_CORE_API = str(getattr(comfyui_forge_core, "FORGE_CORE_API_VERSION", "")).split(".")
if _CORE_API[0] != "1" or len(_CORE_API) < 2 or not _CORE_API[1].isdigit() or int(_CORE_API[1]) < 1:
    raise ImportError("forge_palette needs forge_core API version 1.1 or a later 1.x next to it; "
                      "run tools/comfyui_forge_vendor_sync.py --write.")


PALETTE_SCHEMA = "generate2dsprite.palette.v1"
PALETTE_LOCK_SCHEMA = "generate2dsprite.palette_lock.v1"
PALETTE_LUTS_SCHEMA = "generate2dsprite.palette_luts.v1"

DEFAULT_TRANSPARENT_INDEX = 255
HYSTERESIS_MARGIN = 4e-4        # Squared OKLab distance for a change below one visible step.
ALPHA_BAND = (0.4, 0.6)         # ambiguous coverage: a pixel keeps last frame's opacity in here
COVER_DELTA_E = 0.03            # a sample this close to a reserved colour is already served
STILL_DELTA_E = 0.02            # flip_stats: a source pixel that moved less than this is still

PALETTE_FORMATS = ("json", "gpl", "hex", "pal")

_CHUNK_PAIRS = 1 << 21                  # colour x palette distances per block
_KMEANS_BIN_SHIFT = 3                   # 5 bits per channel when the unique colours exceed max_samples


class PaletteError(ValueError):
    """A bad palette, palette file, lock or index map. Messages are ASCII and user-facing."""


def to_oklab(rgb: Any) -> np.ndarray:
    """sRGB 0..255 (any shape ``... x 3``) to OKLab (Ottosson 2020), float32.

    Operation for operation the same as forge_matte's private ``_to_oklab``.
    """
    c = np.asarray(rgb, np.float32) / np.float32(255.0)
    linear = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4).astype(np.float32)
    lms = linear @ np.array([[0.4122214708, 0.5363325363, 0.0514459929],
                             [0.2119034982, 0.6806995451, 0.1073969566],
                             [0.0883024619, 0.2817188376, 0.6299787005]], np.float32).T
    return np.cbrt(lms) @ np.array([[0.2104542553, 0.7936177850, -0.0040720468],
                                    [1.9779984951, -2.4285922050, 0.4505937099],
                                    [0.0259040371, 0.7827717662, -0.8086757660]], np.float32).T


def from_oklab(lab: Any) -> np.ndarray:
    """OKLab (any shape ``... x 3``) to 8-bit sRGB, uint8.

    Out-of-gamut colours are clipped in linear RGB; channels round half-up, so
    ``from_oklab(to_oklab(c)) == c`` for every 8-bit colour.
    """
    lab = np.asarray(lab, np.float64)
    big_l, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    l_ = (big_l + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m_ = (big_l - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s_ = (big_l - 0.0894841775 * a - 1.2914855480 * b) ** 3
    linear = np.stack([4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_,
                       -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_,
                       -0.0041960863 * l_ - 0.7034186147 * m_ + 1.7076147010 * s_], axis=-1)
    linear = np.clip(linear, 0.0, 1.0)
    srgb = np.where(linear <= 0.0031308, linear * 12.92, 1.055 * np.power(linear, 1.0 / 2.4) - 0.055)
    return np.floor(np.clip(srgb, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)


_HEX_COLOUR = re.compile(r"#?([0-9A-Fa-f]{3}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})")


def parse_color(value: Any) -> tuple[int, int, int]:
    """Read ``#rrggbb``, ``rrggbb``, ``#rgb``, opaque ``#rrggbbff`` or an ``[r, g, b]`` triple.

    Palette colours are opaque: any other alpha raises PaletteError.
    """
    if isinstance(value, str):
        match = _HEX_COLOUR.fullmatch(value.strip())
        if not match:
            raise PaletteError(f"bad colour {value!r}; use #rrggbb")
        digits = match.group(1)
        if len(digits) == 3:
            digits = "".join(ch * 2 for ch in digits)
        if len(digits) == 8:
            if digits[6:].lower() != "ff":
                raise PaletteError(f"palette colour {value!r} is translucent; palette colours are opaque #rrggbb")
            digits = digits[:6]
        return int(digits[0:2], 16), int(digits[2:4], 16), int(digits[4:6], 16)
    if isinstance(value, (tuple, list, np.ndarray)) and len(value) == 3:
        items = list(value)
        if all(isinstance(v, (int, np.integer)) and not isinstance(v, bool) and 0 <= v <= 255 for v in items):
            return int(items[0]), int(items[1]), int(items[2])
    raise PaletteError(f"bad colour {value!r}; use #rrggbb or [r, g, b] with 0..255 integers")


def hex_color(rgb: Sequence[int]) -> str:
    r, g, b = (int(v) for v in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


@dataclasses.dataclass(frozen=True)
class Palette:
    """An ordered palette: colour ``i`` is index ``i`` of indexed exports (palette.v1).

    ``transparent_index`` is the index transparent pixels use in index maps and
    indexed PNGs: a free slot past the colours (255 by default), or one of the
    colour slots, whose colour is then a placeholder that opaque pixels never
    use (the classic "index 0 is transparent" convention). None means the
    palette cannot express transparency in indexed form. ``reserved`` colours
    were fixed, not learned, when the palette was built; ``locked`` palettes are
    never re-learned.
    """

    colors: tuple[tuple[int, int, int], ...]
    names: tuple[str | None, ...] = ()
    reserved: tuple[bool, ...] = ()
    transparent_index: int | None = DEFAULT_TRANSPARENT_INDEX
    locked: bool = False
    source: str = "forge_palette"
    name: str | None = None

    def __post_init__(self) -> None:
        colors = tuple(parse_color(colour) for colour in self.colors)
        count = len(colors)
        if not 1 <= count <= 256:
            raise PaletteError(f"a palette has 1 to 256 colours, got {count}")
        names = tuple(self.names) or (None,) * count
        reserved = tuple(self.reserved) or (False,) * count
        if len(names) != count or len(reserved) != count:
            raise PaletteError("names and reserved need one entry per palette colour")
        slot = self.transparent_index
        if slot is not None:
            if isinstance(slot, bool) or not isinstance(slot, (int, np.integer)) or not 0 <= slot <= 255:
                raise PaletteError(f"transparent_index must be null or an integer 0..255, got {slot!r}")
            slot = int(slot)
        object.__setattr__(self, "colors", colors)
        object.__setattr__(self, "names", tuple(None if n in (None, "") else str(n) for n in names))
        object.__setattr__(self, "reserved", tuple(bool(flag) for flag in reserved))
        object.__setattr__(self, "transparent_index", slot)
        object.__setattr__(self, "locked", bool(self.locked))
        object.__setattr__(self, "source", str(self.source or "forge_palette"))
        object.__setattr__(self, "name", None if self.name in (None, "") else str(self.name))

    def __len__(self) -> int:
        return len(self.colors)

    @functools.cached_property
    def rgb(self) -> np.ndarray:
        """``(n, 3)`` uint8 colours (read-only)."""
        array = np.array(self.colors, np.uint8).reshape(-1, 3)
        array.flags.writeable = False
        return array

    @functools.cached_property
    def lab(self) -> np.ndarray:
        """``(n, 3)`` float32 OKLab colours (read-only)."""
        array = to_oklab(self.rgb)
        array.flags.writeable = False
        return array

    @property
    def hex_colors(self) -> tuple[str, ...]:
        return tuple(hex_color(colour) for colour in self.colors)

    @functools.cached_property
    def usable(self) -> np.ndarray:
        """Indices opaque pixels may use: every colour slot except a transparent one."""
        indices = np.arange(len(self.colors), dtype=np.int64)
        if self.transparent_index is not None and self.transparent_index < len(self.colors):
            indices = indices[indices != self.transparent_index]
        if indices.size == 0:
            raise PaletteError("the palette's only colour slot is its transparent slot")
        indices.flags.writeable = False
        return indices

    def replace(self, **changes: Any) -> "Palette":
        return dataclasses.replace(self, **changes)

    def to_json(self) -> dict[str, Any]:
        colours = []
        for colour, name, reserved in zip(self.colors, self.names, self.reserved):
            entry: dict[str, Any] = {"hex": hex_color(colour)}
            if name:
                entry["name"] = name
            if reserved:
                entry["reserved"] = True
            colours.append(entry)
        document: dict[str, Any] = {"schema": PALETTE_SCHEMA}
        if self.name:
            document["name"] = self.name
        document.update({"colors": colours, "transparent_index": self.transparent_index,
                         "locked": self.locked, "source": self.source})
        return document


def _default_slot(count: int) -> int | None:
    return DEFAULT_TRANSPARENT_INDEX if count <= DEFAULT_TRANSPARENT_INDEX else None


def _palette_from_entries(entries: Any, **fields: Any) -> Palette:
    colours, names, reserved = [], [], []
    if isinstance(entries, Mapping):
        items = [(str(key), value, False) for key, value in entries.items()]
    elif isinstance(entries, (list, tuple)):
        items = []
        for position, entry in enumerate(entries):
            if isinstance(entry, Mapping):
                if "hex" not in entry:
                    raise PaletteError(f"palette entry {position} needs a 'hex' colour")
                items.append((entry.get("name"), entry["hex"], bool(entry.get("reserved", False))))
            else:
                items.append((None, entry, False))
    else:
        raise PaletteError("palette colours must be a list or a {name: colour} mapping")
    for name, value, flag in items:
        colours.append(parse_color(value))
        names.append(name)
        reserved.append(flag)
    if not colours:
        raise PaletteError("the palette has no colours")
    fields.setdefault("transparent_index", _default_slot(len(colours)))
    return Palette(tuple(colours), names=tuple(names), reserved=tuple(reserved), **fields)


def _palette_from_mapping(document: Mapping[str, Any]) -> Palette:
    """palette.v1, ``{"colors": [...] | {...}}``, ``{"palette": {...}}`` (PixelSpec) or ``{name: colour}``."""
    if "colors" in document or "palette" in document:
        entries = document["colors"] if "colors" in document else document["palette"]
        fields: dict[str, Any] = {"locked": bool(document.get("locked", False)),
                                  "source": document.get("source") or "imported palette",
                                  "name": document.get("name")}
        if "transparent_index" in document:
            fields["transparent_index"] = document["transparent_index"]
        return _palette_from_entries(entries, **fields)
    return _palette_from_entries(document, source="imported palette")


def as_palette(value: Any) -> Palette:
    """Coerce a Palette, palette file path, palette.v1 (or similar) mapping, or a colour list."""
    if isinstance(value, Palette):
        return value
    if isinstance(value, (str, os.PathLike)):
        return read_palette(value)
    if isinstance(value, Mapping):
        return _palette_from_mapping(value)
    if isinstance(value, np.ndarray):
        if value.ndim != 2 or value.shape[1] not in (3, 4):
            raise PaletteError(f"a palette array is (n, 3), got {value.shape}")
        return _palette_from_entries([tuple(int(v) for v in row[:3]) for row in value], source="array")
    if isinstance(value, (list, tuple)):
        return _palette_from_entries(list(value), source="colour list")
    raise PaletteError(f"cannot read a palette from {type(value).__name__}")


def _text_lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8-sig").splitlines()
    except UnicodeDecodeError:
        raise PaletteError(f"{path.name} is not UTF-8 text") from None


def _read_gpl(path: Path) -> Palette:
    lines = _text_lines(path)
    if not lines or not lines[0].strip().startswith("GIMP Palette"):
        raise PaletteError(f"{path.name} is not a GIMP palette (first line must be 'GIMP Palette')")
    colours, names, title = [], [], None
    for number, line in enumerate(lines[1:], start=2):
        text = line.strip()
        if text.startswith("Name:"):
            title = text[5:].strip() or None
            continue
        if not text or text.startswith("#") or not text[0].isdigit():
            continue
        parts = text.split(None, 3)
        values = parts[:3]
        if len(values) < 3 or not all(part.isdigit() and int(part) <= 255 for part in values):
            raise PaletteError(f"{path.name} line {number}: expected 'R G B [name]' with 0..255 values")
        colour = tuple(int(part) for part in values)
        label = parts[3].strip() if len(parts) == 4 else None
        colours.append(colour)
        names.append(None if label and label.lower() == hex_color(colour) else label)
    if not colours:
        raise PaletteError(f"{path.name} has no colours")
    return Palette(tuple(colours), names=tuple(names), transparent_index=_default_slot(len(colours)),
                   source=f"imported from {path.name}", name=title)


def _read_hex(path: Path) -> Palette:
    colours = []
    for number, line in enumerate(_text_lines(path), start=1):
        text = line.strip()
        if not text or text.startswith(";"):
            continue
        if not re.fullmatch(r"#?[0-9A-Fa-f]{6}", text):
            raise PaletteError(f"{path.name} line {number}: expected one rrggbb colour per line")
        colours.append(parse_color(text))
    if not colours:
        raise PaletteError(f"{path.name} has no colours")
    return Palette(tuple(colours), transparent_index=_default_slot(len(colours)), source=f"imported from {path.name}")


def _read_jasc(path: Path) -> Palette:
    lines = [line.strip() for line in _text_lines(path)]
    if len(lines) < 3 or lines[0] != "JASC-PAL" or not lines[2].isdigit():
        raise PaletteError(f"{path.name} is not a JASC-PAL palette")
    count = int(lines[2])
    rows = [line for line in lines[3:] if line][:count]
    colours = []
    for row in rows:
        parts = row.split()
        if len(parts) < 3 or not all(part.isdigit() and int(part) <= 255 for part in parts[:3]):
            raise PaletteError(f"{path.name}: bad colour row {row!r}")
        colours.append(tuple(int(part) for part in parts[:3]))
    if len(colours) != count or not colours:
        raise PaletteError(f"{path.name} declares {count} colours but lists {len(colours)}")
    return Palette(tuple(colours), transparent_index=_default_slot(len(colours)), source=f"imported from {path.name}")


def _read_swatch_png(path: Path) -> Palette:
    pixels = comfyui_forge_core.load_rgba(path)[0]
    rgba = np.asarray(pixels)
    opaque = rgba[..., :3][rgba[..., 3] == 255]
    if opaque.size == 0:
        raise PaletteError(f"{path.name} has no opaque pixels to read colours from")
    keys = _pack(opaque)
    _, first = np.unique(keys, return_index=True)
    colours = opaque[np.sort(first)]
    if len(colours) > 256:
        raise PaletteError(f"{path.name} has {len(colours)} colours; a palette has at most 256")
    return Palette(tuple(map(tuple, colours.tolist())), transparent_index=_default_slot(len(colours)),
                   source=f"imported from {path.name}")


def read_palette(path: str | os.PathLike) -> Palette:
    """Read a palette file: palette.v1 ``.json`` (or another colour JSON), GIMP ``.gpl``,
    Lospec ``.hex``, JASC ``.pal``, or a swatch ``.png`` (its opaque colours in raster
    order, so an indexed sprite yields only the colours it uses).
    """
    path = Path(path)
    if not path.is_file():
        raise PaletteError(f"palette file not found: {path}")
    suffix = path.suffix.lower()
    if suffix == ".json":
        try:
            document = json.loads(path.read_text(encoding="utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise PaletteError(f"{path.name} is not valid JSON: {error}") from None
        schema = document.get("schema") if isinstance(document, Mapping) else None
        if schema in (PALETTE_LOCK_SCHEMA, PALETTE_LUTS_SCHEMA) or (
                schema not in (None, PALETTE_SCHEMA) and "colors" not in document and "palette" not in document):
            raise PaletteError(f"{path.name} is a {schema} document, not a palette")
        return as_palette(document)
    if suffix == ".gpl":
        return _read_gpl(path)
    if suffix == ".hex":
        return _read_hex(path)
    if suffix == ".pal":
        return _read_jasc(path)
    if suffix == ".png":
        return _read_swatch_png(path)
    raise PaletteError(f"unsupported palette file {path.name}; use .json, .gpl, .hex, .pal or a swatch .png")


def palette_text(palette: Any, fmt: str) -> str:
    pal = as_palette(palette)
    if fmt == "json":
        return json.dumps(pal.to_json(), indent=2, ensure_ascii=False) + "\n"
    if fmt == "gpl":
        lines = ["GIMP Palette", f"Name: {pal.name or 'Agent Sprite Forge palette'}",
                 f"Columns: {min(16, len(pal))}", "#"]
        for colour, name in zip(pal.colors, pal.names):
            label = re.sub(r"\s+", " ", name).strip() if name else hex_color(colour)
            lines.append(f"{colour[0]:3d} {colour[1]:3d} {colour[2]:3d}\t{label or hex_color(colour)}")
        return "\n".join(lines) + "\n"
    if fmt == "hex":
        return "".join(hex_color(colour)[1:] + "\n" for colour in pal.colors)
    if fmt == "pal":
        rows = ["JASC-PAL", "0100", str(len(pal))] + [f"{r} {g} {b}" for r, g, b in pal.colors]
        return "\r\n".join(rows) + "\r\n"
    raise PaletteError(f"unknown palette format {fmt!r}; use one of {', '.join(PALETTE_FORMATS)}")


def write_palette(palette: Any, path: str | os.PathLike, fmt: str | None = None) -> None:
    """Write a palette file, never replacing an existing one (FileExistsError).

    ``fmt`` is json (palette.v1, the only format that keeps transparent_index,
    reserved, locked and source), gpl, hex or pal; by default the suffix decides.
    """
    path = Path(path)
    fmt = (fmt or path.suffix.lstrip(".")).lower()
    if fmt == "json":
        comfyui_forge_core.write_json(path, as_palette(palette).to_json(), no_clobber=True)
        return
    payload = palette_text(palette, fmt).encode("utf-8")
    with open(path, "xb") as stream:
        try:
            stream.write(payload)
        except BaseException:
            stream.close()
            path.unlink(missing_ok=True)
            raise


def _pack(rgb: np.ndarray) -> np.ndarray:
    channels = np.asarray(rgb).astype(np.uint32)
    return (channels[..., 0] << 16) | (channels[..., 1] << 8) | channels[..., 2]


def _unpack(keys: np.ndarray) -> np.ndarray:
    keys = np.asarray(keys, np.uint32)
    return np.stack([(keys >> 16) & 255, (keys >> 8) & 255, keys & 255], axis=-1).astype(np.uint8)


def _rgba(image: Any) -> np.ndarray:
    """A fresh ``(H, W, 4)`` uint8 RGBA copy of an array, Pillow image or image path."""
    if isinstance(image, (str, os.PathLike)):
        image = comfyui_forge_core.load_rgba(image)[0]
    if isinstance(image, Image.Image):
        return np.array(image if image.mode == "RGBA" else image.convert("RGBA"), dtype=np.uint8)
    array = np.asarray(image)
    if array.dtype != np.uint8 or array.ndim != 3 or array.shape[2] not in (3, 4):
        raise PaletteError(f"expected an (H, W, 3|4) uint8 image, got {array.dtype} {array.shape}")
    if array.shape[2] == 3:
        return np.concatenate([array, np.full(array.shape[:2] + (1,), 255, np.uint8)], axis=2)
    return np.array(array, dtype=np.uint8, copy=True)


def _colours(rgb: Any) -> np.ndarray:
    """``(..., 3)`` uint8 colours of an image, image path or colour array (alpha dropped)."""
    if isinstance(rgb, (str, os.PathLike, Image.Image)):
        return _rgba(rgb)[..., :3]
    array = np.asarray(rgb)
    if array.dtype != np.uint8:
        if not np.issubdtype(array.dtype, np.integer) or array.size and (array.min() < 0 or array.max() > 255):
            raise PaletteError(f"expected uint8 colours, got {array.dtype}")
        array = array.astype(np.uint8)
    if array.ndim < 1 or array.shape[-1] not in (3, 4):
        raise PaletteError(f"expected colours shaped (..., 3) or (..., 4), got {array.shape}")
    return array[..., :3]


def _nearest_colours(colours: np.ndarray, pal: Palette, lab: np.ndarray | None = None
                     ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Nearest usable palette index, squared OKLab distance and exact-match flag of ``(m, 3)`` colours.

    An exact palette colour maps to its (lowest) index with distance 0, without
    floating point; other colours take the OKLab nearest, ties to the lowest index.
    """
    count = len(colours)
    index = np.zeros(count, np.int64)
    distance = np.zeros(count, np.float64)
    if count == 0:
        return index, distance, np.zeros(0, bool)
    usable = pal.usable
    keys = _pack(colours)
    palette_keys, first = np.unique(_pack(pal.rgb[usable]), return_index=True)
    position = np.minimum(np.searchsorted(palette_keys, keys), len(palette_keys) - 1)
    exact = palette_keys[position] == keys
    index[exact] = usable[first[position[exact]]]
    rest = np.flatnonzero(~exact)
    if rest.size:
        points = (to_oklab(colours[rest]) if lab is None else lab[rest]).astype(np.float64)
        centres = pal.lab[usable].astype(np.float64)
        step = max(1, _CHUNK_PAIRS // len(centres))
        for start in range(0, rest.size, step):
            block = points[start:start + step]
            squared = ((block[:, None, :] - centres[None, :, :]) ** 2).sum(-1)
            best = squared.argmin(1)
            index[rest[start:start + step]] = usable[best]
            distance[rest[start:start + step]] = squared[np.arange(len(block)), best]
    return index, distance, exact


def _lookup(rgb: np.ndarray, pal: Palette, *, with_lab: bool = False
            ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray | None]:
    """Per pixel of ``(..., 3)`` uint8: nearest index, squared distance, exact flag and (optionally) OKLab."""
    shape = rgb.shape[:-1]
    keys, inverse = np.unique(_pack(rgb.reshape(-1, 3)), return_inverse=True)
    inverse = inverse.reshape(-1)
    unique = _unpack(keys)
    lab = to_oklab(unique).astype(np.float64) if with_lab else None
    index, distance, exact = _nearest_colours(unique, pal, lab)
    pixel_lab = None if lab is None else lab[inverse].reshape(shape + (3,))
    return index[inverse].reshape(shape), distance[inverse].reshape(shape), exact[inverse].reshape(shape), pixel_lab


def nearest_index(rgb: Any, palette: Any) -> np.ndarray:
    """Index of the OKLab-nearest palette colour for every colour of ``rgb``, uint8.

    ``rgb`` is an ``(..., 3)`` or ``(..., 4)`` uint8 array (alpha is ignored), a
    Pillow image or an image path. A palette's transparent slot is never chosen.
    """
    pal = as_palette(palette)
    return _lookup(_colours(rgb), pal)[0].astype(np.uint8)


def _sample_items(samples: Any) -> list[Any] | None:
    """The items of a list of images (arrays, Pillow images or paths), or None for one colour array."""
    if isinstance(samples, (list, tuple)) and samples and all(
            isinstance(item, (Image.Image, str, os.PathLike)) or (isinstance(item, np.ndarray) and item.ndim >= 2)
            for item in samples):
        return list(samples)
    return None


def _item_samples(item: Any, alpha_threshold: int) -> tuple[np.ndarray, np.ndarray | None]:
    """``(colours, mask)``: the item's ``(..., 3)`` colours and, for RGBA input, the pixels sampled."""
    if isinstance(item, (str, os.PathLike, Image.Image)):
        item = _rgba(item)
    array = np.asarray(item)
    colours = _colours(array)
    if array.shape[-1] == 4:
        return colours, np.asarray(array[..., 3]) >= alpha_threshold
    return colours, None


def _gather_samples(samples: Any, weights: Any, alpha_threshold: int) -> tuple[np.ndarray, np.ndarray]:
    """All sampled ``(N, 3)`` uint8 colours with their float64 weights."""
    if isinstance(samples, (Image.Image, str, os.PathLike)):
        samples = [samples]
    items = _sample_items(samples)
    colour_parts, weight_parts = [], []
    if items is not None:
        item_weights = [1.0] * len(items) if weights is None else [float(w) for w in np.asarray(weights).reshape(-1)]
        if len(item_weights) != len(items):
            raise PaletteError(f"weights: one per sample image ({len(items)}), got {len(item_weights)}")
        for item, weight in zip(items, item_weights):
            colours, mask = _item_samples(item, alpha_threshold)
            chosen = colours.reshape(-1, 3) if mask is None else colours[mask]
            colour_parts.append(chosen.reshape(-1, 3))
            weight_parts.append(np.full(len(chosen), weight, np.float64))
    else:
        array = np.asarray(samples)
        colours, mask = _item_samples(array, alpha_threshold)
        per_sample = (np.ones(colours.shape[:-1], np.float64) if weights is None
                      else np.broadcast_to(np.asarray(weights, np.float64), colours.shape[:-1]))
        if mask is None:
            colour_parts.append(colours.reshape(-1, 3))
            weight_parts.append(per_sample.reshape(-1))
        else:
            colour_parts.append(colours[mask].reshape(-1, 3))
            weight_parts.append(per_sample[mask].reshape(-1))
    colours = np.concatenate(colour_parts) if colour_parts else np.zeros((0, 3), np.uint8)
    sample_weights = np.concatenate(weight_parts) if weight_parts else np.zeros(0, np.float64)
    if (sample_weights < 0).any() or not np.isfinite(sample_weights).all():
        raise PaletteError("sample weights must be finite and >= 0")
    keep = sample_weights > 0
    return colours[keep], sample_weights[keep]


def _squared_distances(points: np.ndarray, centres: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Nearest centre and squared distance of every point (float64, blockwise)."""
    nearest = np.zeros(len(points), np.int64)
    distance = np.zeros(len(points), np.float64)
    centre_norms = (centres ** 2).sum(1)
    step = max(1, _CHUNK_PAIRS // max(1, len(centres)))
    for start in range(0, len(points), step):
        block = points[start:start + step]
        squared = (block ** 2).sum(1)[:, None] - 2.0 * (block @ centres.T) + centre_norms[None, :]
        np.maximum(squared, 0.0, out=squared)
        best = squared.argmin(1)
        nearest[start:start + step] = best
        distance[start:start + step] = squared[np.arange(len(block)), best]
    return nearest, distance


def _kmeans(points: np.ndarray, weights: np.ndarray, count: int, fixed: np.ndarray,
            rng: np.random.Generator, max_iter: int) -> np.ndarray:
    """Weighted k-means++ in OKLab: ``count`` learned centres beside the ``fixed`` ones."""
    if len(fixed):
        distance = _squared_distances(points, fixed)[1]
    else:
        distance = np.full(len(points), np.inf)
    centres: list[np.ndarray] = []
    for _ in range(count):
        if not len(fixed) and not centres:
            score = weights
        else:
            score = weights * distance
        total = float(score.sum())
        if not total > 0.0:
            break
        chosen = int(rng.choice(len(points), p=score / total))
        centres.append(points[chosen].copy())
        distance = np.minimum(distance, ((points - points[chosen]) ** 2).sum(1))
    learned = np.array(centres, np.float64).reshape(-1, 3)
    if not len(learned):
        return learned
    offset = len(fixed)
    previous = None
    for _ in range(max_iter):
        assignment, distance = _squared_distances(points, np.concatenate([fixed, learned]))
        if previous is not None and np.array_equal(assignment, previous):
            break
        previous = assignment
        member = assignment >= offset
        cluster = assignment[member] - offset
        mass = np.bincount(cluster, weights=weights[member], minlength=len(learned))
        sums = np.stack([np.bincount(cluster, weights=weights[member] * points[member, axis],
                                     minlength=len(learned)) for axis in range(3)], axis=1)
        filled = mass > 0
        learned[filled] = sums[filled] / mass[filled, None]
        spread = weights * distance
        for empty in np.flatnonzero(~filled):  # re-seed a dead centre on the worst-served sample
            far = int(spread.argmax())
            if not spread[far] > 0.0:
                break
            learned[empty] = points[far]
            spread[far] = 0.0
    return learned


def _bin_colours(lab: np.ndarray, weights: np.ndarray, colours: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Merge colours into 5-bit RGB bins: weighted mean OKLab and total weight per bin."""
    bins = _pack(colours >> _KMEANS_BIN_SHIFT)
    _, member = np.unique(bins, return_inverse=True)
    member = member.reshape(-1)
    mass = np.bincount(member, weights=weights)
    means = np.stack([np.bincount(member, weights=weights * lab[:, axis]) for axis in range(3)], axis=1)
    return means / mass[:, None], mass


def _sort_by_lightness(colours: np.ndarray) -> np.ndarray:
    if len(colours) < 2:
        return colours
    lab = to_oklab(colours).astype(np.float64)
    hue = np.arctan2(lab[:, 2], lab[:, 1])
    return colours[np.lexsort((hue, lab[:, 0]))]


def build_palette(samples: Any, k: int, *, reserved: Any = None, weights: Any = None, seed: int = 0,
                  cover: float = COVER_DELTA_E, alpha_threshold: int = 128, max_iter: int = 30,
                  max_samples: int = 32768) -> Palette:
    """Learn a ``k``-colour palette (reserved colours included) with weighted k-means++ in OKLab.

    ``samples``: an RGB(A) uint8 array, a Pillow image, an image path or a list
    of those; RGBA pixels below ``alpha_threshold`` are not sampled. ``weights``:
    one per sample image (list input) or per pixel (array input). ``reserved``:
    colours (or a Palette, such as a locked one being extended) kept unchanged as
    indices ``0..r-1``; the palette's transparent_index and names carry over.
    Samples within ``cover`` (dE) of a reserved colour are skipped, so learned
    colours go where the reserved ones do not reach. Art with at most ``k - r``
    remaining colours gets exactly those colours. Clustering runs on the unique
    colours (weighted by count), merged into 5-bit bins beyond ``max_samples``;
    the result depends only on the multiset of samples and ``seed``. Learned
    colours follow the reserved ones, darkest first; exact duplicates are dropped.
    """
    if isinstance(k, bool) or not isinstance(k, (int, np.integer)) or not 1 <= k <= 256:
        raise PaletteError(f"k must be an integer 1..256, got {k!r}")
    base = as_palette(reserved) if isinstance(reserved, (Palette, str, os.PathLike, Mapping)) else None
    title = None
    if base is not None:
        reserved_rgb = base.rgb.copy()
        names, slot, title = list(base.names), base.transparent_index, base.name
    else:
        reserved_rgb = (np.array([parse_color(colour) for colour in reserved], np.uint8).reshape(-1, 3)
                        if reserved is not None and len(reserved) else np.zeros((0, 3), np.uint8))
        _, first = np.unique(_pack(reserved_rgb), return_index=True)
        reserved_rgb = reserved_rgb[np.sort(first)]
        names, slot = [None] * len(reserved_rgb), None
    if len(reserved_rgb) > k:
        raise PaletteError(f"{len(reserved_rgb)} reserved colours do not fit in k={k}")
    if not cover >= 0.0:
        raise PaletteError("cover must be >= 0")
    colours, sample_weights = _gather_samples(samples, weights, alpha_threshold)
    keys, inverse = np.unique(_pack(colours), return_inverse=True)
    unique = _unpack(keys)
    unique_weights = np.bincount(inverse.reshape(-1), weights=sample_weights, minlength=len(keys))
    room = k - len(reserved_rgb)
    learned = np.zeros((0, 3), np.uint8)
    if room > 0 and len(unique):
        lab = to_oklab(unique).astype(np.float64)
        anchors = reserved_rgb
        if base is not None and slot is not None and slot < len(base):
            anchors = np.delete(reserved_rgb, slot, axis=0)  # a transparent slot's placeholder serves nothing
        if len(anchors):
            served = _squared_distances(lab, to_oklab(anchors).astype(np.float64))[1] <= cover * cover
            served |= np.isin(keys, _pack(anchors))
            unique, lab, unique_weights = unique[~served], lab[~served], unique_weights[~served]
        if len(unique) <= room:
            learned = unique
        else:
            points, point_weights = lab, unique_weights
            if len(points) > max_samples:
                points, point_weights = _bin_colours(lab, unique_weights, unique)
            fixed = to_oklab(anchors).astype(np.float64) if len(anchors) else np.zeros((0, 3))
            centres = _kmeans(points, point_weights, room, fixed, np.random.default_rng(seed), max_iter)
            learned = from_oklab(centres).reshape(-1, 3)
        kept = np.unique(_pack(learned), return_index=True)[1]
        learned = learned[np.sort(kept)]
        learned = learned[~np.isin(_pack(learned), _pack(reserved_rgb))]
        learned = _sort_by_lightness(learned)
    colours_out = np.concatenate([reserved_rgb, learned]).astype(np.uint8)
    if not len(colours_out):
        raise PaletteError("no samples: every pixel is transparent or below the alpha threshold")
    if base is None:
        slot = _default_slot(len(colours_out))
    elif slot is not None and len(base) <= slot < len(colours_out):
        raise PaletteError(f"the palette would grow over its transparent index {slot}; "
                           f"use at most {slot} colours or move transparent_index")
    flags = [True] * len(reserved_rgb) + [False] * len(learned)
    return Palette(tuple(map(tuple, colours_out.tolist())), names=tuple(names) + (None,) * len(learned),
                   reserved=tuple(flags), transparent_index=slot, name=title,
                   source=f"forge_palette.build_palette: OKLab k-means++, k={k}, seed {seed}")


def _transparent_slot(pal: Palette) -> int:
    if pal.transparent_index is None:
        raise PaletteError("the palette has no transparent_index, so transparent pixels cannot be indexed; "
                           "set transparent_index in the palette (255, or a free slot)")
    return pal.transparent_index


def render_indices(idx: Any, palette: Any) -> np.ndarray:
    """RGBA of an index map: palette colours, and ``(0, 0, 0, 0)`` at the transparent index."""
    pal = as_palette(palette)
    data = np.asarray(idx)
    if data.ndim != 2 or not np.issubdtype(data.dtype, np.integer):
        raise PaletteError(f"an index map is a 2-D integer array, got {data.dtype} {data.shape}")
    slot = pal.transparent_index
    valid = (data >= 0) & (data < len(pal))
    if slot is not None:
        valid |= data == slot
    if not valid.all():
        raise PaletteError(f"index {int(data[~valid].flat[0])} is not a palette colour (0..{len(pal) - 1})"
                           f" or the transparent index {slot}")
    table = np.zeros((256, 4), np.uint8)
    table[:len(pal), :3] = pal.rgb
    table[:len(pal), 3] = 255
    if slot is not None:
        table[slot] = 0
    return table[data.astype(np.uint8)]


def cleanup_orphans(idx: Any, passes: int = 1, *, transparent_index: int | None = DEFAULT_TRANSPARENT_INDEX
                    ) -> np.ndarray:
    """Replace isolated pixels (no 4-neighbour of their own index) by the neighbours' majority index.

    transparent pixels are never changed and
    never spread; a pixel without a majority (at least two equal neighbours) stays.
    """
    data = np.array(idx, copy=True)
    height, width = data.shape
    slot = -1 if transparent_index is None else transparent_index
    for _ in range(int(passes)):
        padded = np.pad(data, 1, mode="edge")
        up, down = padded[0:height, 1:width + 1], padded[2:height + 2, 1:width + 1]
        left, right = padded[1:height + 1, 0:width], padded[1:height + 1, 2:width + 2]
        lonely = (up != data) & (down != data) & (left != data) & (right != data)
        majority = np.where((up == down) | (up == left) | (up == right), up,
                            np.where((down == left) | (down == right), down,
                                     np.where(left == right, left, data)))
        fix = lonely & (majority != data) & (majority != slot) & (data != slot)
        data = np.where(fix, majority, data)
    return data


def _cleanup_alpha_one(idx: np.ndarray, slot: int) -> np.ndarray:
    opaque = idx != slot
    padded = np.pad(opaque, 1)
    neighbours = (padded[:-2, 1:-1].astype(np.int8) + padded[2:, 1:-1] + padded[1:-1, :-2] + padded[1:-1, 2:])
    cleaned = np.where(opaque & (neighbours <= 1), slot, idx).astype(idx.dtype)
    hole = ~opaque & (neighbours == 4)
    if hole.any():
        above = np.pad(cleaned, 1, constant_values=slot)[:-2, 1:-1]
        cleaned = np.where(hole, above, cleaned).astype(idx.dtype)
    return cleaned


def _quantize_frame(pixels: np.ndarray, pal: Palette, previous: np.ndarray | None, margin: float,
                    band: tuple[float, float], threshold: float, orphans: int, despeckle: bool,
                    slot: int) -> tuple[np.ndarray, dict[str, int]]:
    alpha = pixels[..., 3].astype(np.float32) / np.float32(255.0)
    index, distance, _, lab = _lookup(pixels[..., :3], pal, with_lab=previous is not None)
    opaque = alpha >= threshold
    held_index = held_alpha = 0
    if previous is not None:
        was_opaque = previous != slot
        candidate = np.where(was_opaque, previous, index).astype(np.int64)
        palette_lab = pal.lab.astype(np.float64)
        keep_distance = ((lab - palette_lab[candidate]) ** 2).sum(-1)
        keep = was_opaque & (candidate != index) & (keep_distance <= distance + margin)
        held_index = int((keep & opaque).sum())
        index = np.where(keep, candidate, index)
        ambiguous = (alpha > band[0]) & (alpha < band[1])
        held_alpha = int((ambiguous & (was_opaque != opaque)).sum())
        opaque = np.where(ambiguous, was_opaque, opaque)
    result = index.astype(np.uint8)
    result[~opaque] = slot
    before = result
    if orphans:
        result = cleanup_orphans(result, orphans, transparent_index=slot)
    orphans_fixed = int((result != before).sum())
    before = result
    if despeckle:
        result = _cleanup_alpha_one(result, slot)
    stats = {"held_index_px": held_index, "held_alpha_px": held_alpha, "orphans_fixed_px": orphans_fixed,
             "despeckled_px": int((result != before).sum())}
    return result, stats


def quantize_sequence(frames: Sequence[Any], palette: Any, *, margin: float = HYSTERESIS_MARGIN,
                      alpha_band: tuple[float, float] = ALPHA_BAND, loop: bool = True, pingpong: bool = False,
                      alpha_threshold: float = 0.5, orphans: int = 1, despeckle: bool = True,
                      return_stats: bool = False) -> Any:
    """Quantize a clip with temporal hysteresis.

    Each frame is quantized to the OKLab-nearest palette colours; then a pixel
    that was opaque in the previous output keeps that index while its colour is
    within ``margin`` (squared OKLab distance; 4e-4 is dE 0.02) of the best match,
    and a pixel whose alpha (0..1) lies inside ``alpha_band`` keeps the previous
    opacity. Real changes switch at once; compression noise stops flipping
    indices and outline pixels. Each frame then gets ``orphans`` cleanup_orphans
    passes and, with ``despeckle``, alpha cleanup, before it seeds the next one.

    ``loop``: frame 0 continues from the last frame (a warm-up pass seeds it).
    ``pingpong``: the clip plays 0..n-1..1, so frame 0 is seeded from frame 1 and
    the returned list is the whole cycle ``q + q[-2:0:-1]``: the way back reuses
    the forward frames, an exact mirror. Neither: a one-shot clip, unseeded.
    ``alpha_threshold`` is a fraction of full alpha (0..1) here, like
    ``alpha_band``; fit_report takes 0..255, so a value above
    1 is refused rather than silently making every pixel transparent.
    Returns uint8 index maps (transparent pixels at the palette's
    transparent_index), plus per-frame hysteresis stats with ``return_stats``.
    """
    pal = as_palette(palette)
    low, high = float(alpha_band[0]), float(alpha_band[1])
    if not 0.0 <= low <= high <= 1.0:
        raise PaletteError("alpha_band needs 0 <= low <= high <= 1")
    if not 0.0 <= float(alpha_threshold) <= 1.0:
        raise PaletteError(f"quantize_sequence alpha_threshold is a fraction 0..1 (got {alpha_threshold!r}); "
                           "fit_report takes 0..255")
    if not margin >= 0.0:
        raise PaletteError("margin must be >= 0")
    pixels = [_rgba(frame) for frame in frames]
    if not pixels:
        return ([], []) if return_stats else []
    if any(frame.shape != pixels[0].shape for frame in pixels):
        raise PaletteError("all frames of a sequence must have the same size")
    slot = _transparent_slot(pal)

    def run(seed: np.ndarray | None) -> tuple[list[np.ndarray], list[dict[str, int]]]:
        outputs, stats, previous = [], [], seed
        for frame in pixels:
            previous, frame_stats = _quantize_frame(frame, pal, previous, margin, (low, high),
                                                    float(alpha_threshold), int(orphans), bool(despeckle), slot)
            outputs.append(previous)
            stats.append(frame_stats)
        return outputs, stats

    seed = None
    if len(pixels) > 1 and (loop or pingpong):
        warm = run(None)[0]
        seed = warm[1] if pingpong else warm[-1]
    outputs, stats = run(seed)
    if pingpong:
        outputs = outputs + outputs[-2:0:-1]
    return (outputs, stats) if return_stats else outputs


def save_indexed_png(idx: Any, palette: Any, path: str | os.PathLike,
                     transparent_index: int | None = DEFAULT_TRANSPARENT_INDEX) -> None:
    """Write an index map as an indexed PNG: PLTE holds the palette, tRNS one transparent index.

    ``transparent_index`` is the index that marks transparent pixels in ``idx``;
    it must be the palette's own transparent_index when the palette names one
    (None writes no tRNS; then every index must be a colour). PLTE is padded with
    black up to a transparent index past the colours. The bit depth follows the
    PLTE length (1, 2, 4 or 8 bits), the file has no metadata chunks, and decoding
    gives back ``idx`` exactly. Indexed PNGs are an engine export, never builder input.
    """
    pal = as_palette(palette)
    slot = transparent_index
    if slot is not None and (isinstance(slot, bool) or not isinstance(slot, (int, np.integer)) or not 0 <= slot <= 255):
        raise PaletteError(f"transparent_index must be None or 0..255, got {slot!r}")
    if pal.transparent_index is not None and slot != pal.transparent_index:
        raise PaletteError(f"the palette's transparent index is {pal.transparent_index}; "
                           f"pass transparent_index={pal.transparent_index}")
    if pal.transparent_index is None and slot is not None and slot < len(pal):
        raise PaletteError(f"transparent_index {slot} would hide palette colour {slot}")
    data = np.asarray(idx)
    if data.ndim != 2 or not np.issubdtype(data.dtype, np.integer):
        raise PaletteError(f"an index map is a 2-D integer array, got {data.dtype} {data.shape}")
    valid = (data >= 0) & (data < len(pal))
    if slot is not None:
        valid |= data == slot
    if not valid.all():
        raise PaletteError(f"index {int(data[~valid].flat[0])} is neither a palette colour (0..{len(pal) - 1})"
                           f" nor the transparent index {slot}")
    entries = len(pal) if slot is None else max(len(pal), slot + 1)
    table = np.zeros((entries, 3), np.uint8)
    table[:len(pal)] = pal.rgb
    if slot is not None and slot >= len(pal):
        table[slot] = 0
    image = Image.fromarray(data.astype(np.uint8))
    image.putpalette(table.tobytes())
    options: dict[str, Any] = {"optimize": False, "compress_level": 9}
    if slot is not None:
        options["transparency"] = bytes([255] * slot + [0])
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", **options)
    Path(path).write_bytes(buffer.getvalue())


def _round(value: float) -> float:
    return round(float(value), 6)


def fit_report(asset: Any, palette: Any, *, alpha_threshold: int = 1) -> dict[str, Any]:
    """How well an image fits a palette, over its pixels with alpha >= ``alpha_threshold``.

    ``mean_delta_e``, ``p95_delta_e`` and ``max_delta_e`` are pixel-weighted OKLab
    distances to the nearest palette colour; ``off_palette_px`` counts pixels whose
    RGB is not exactly a palette colour; ``partial_alpha_px`` counts 0 < alpha < 255
    over the whole image; ``colors`` is the number of distinct measured colours and
    ``palette_colors_used`` the number of palette entries they map to.
    """
    pixels = _rgba(asset)
    pal = as_palette(palette)
    alpha = pixels[..., 3]
    measured = pixels[..., :3][alpha >= alpha_threshold]
    report: dict[str, Any] = {"measured_px": int(len(measured)), "alpha_threshold": int(alpha_threshold),
                              "off_palette_px": 0,
                              "partial_alpha_px": int(((alpha > 0) & (alpha < 255)).sum()),
                              "colors": 0, "palette_colors_used": 0,
                              "mean_delta_e": 0.0, "p95_delta_e": 0.0, "max_delta_e": 0.0}
    if not len(measured):
        return report
    keys, counts = np.unique(_pack(measured), return_counts=True)
    index, distance, exact = _nearest_colours(_unpack(keys), pal)
    delta = np.sqrt(distance)
    order = np.argsort(delta, kind="stable")
    cumulative = np.cumsum(counts[order])
    p95 = delta[order][min(len(order) - 1, int(np.searchsorted(cumulative, 0.95 * cumulative[-1])))]
    report.update({"off_palette_px": int(counts[~exact].sum()), "colors": int(len(keys)),
                   "palette_colors_used": int(len(np.unique(index))),
                   "mean_delta_e": _round((delta * counts).sum() / counts.sum()),
                   "p95_delta_e": _round(p95), "max_delta_e": _round(delta.max())})
    return report
