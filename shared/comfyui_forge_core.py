"""Shared image, path, publication, geometry and timing utilities (API 1.1).

Images use straight-alpha RGBA; resizing works in premultiplied space.
Canonical copies and skill destinations are listed in shared/VENDORED.json.
After editing shared modules, run tools/comfyui_forge_vendor_sync.py --write.
"""

from __future__ import annotations

import contextlib
import ctypes
import decimal
import errno
import functools
import hashlib
import io
import json
import math
import numbers
import operator
import os
import re
import secrets
import shutil
import sys
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Sequence

import numpy as np
from PIL import Image


FORGE_CORE_API_VERSION = "1.1"
FORGE_PACKAGE_VERSION = "0.4.0"
ALPHA_GEOMETRY_THRESHOLD = 16
BODY_ALPHA_THRESHOLD = 32

HYGIENE_MODES = ("none", "floor", "detached", "both")
ANCHOR_MODES = ("feet", "stance", "bbox", "centroid", "center")
RESAMPLERS = ("box", "lanczos", "nearest")
CLI_EXPECTED_ERRORS: tuple[type[BaseException], ...] = (OSError, ValueError, Image.DecompressionBombError)

_CHUNK = 1 << 20


_ASCII_MAP = str.maketrans({
    "\u2192": "->", "\u2190": "<-", "\u2194": "<->", "\u21d2": "=>",
    "\u2014": "-", "\u2013": "-", "\u2212": "-",
    "\u00d7": "x", "\u00b7": ".", "\u2026": "...",
    "\u2264": "<=", "\u2265": ">=", "\u2260": "!=", "\u2248": "~", "\u00b1": "+/-",
    "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u00a0": " ",
})


def utf8_stdio() -> None:
    """Make stdout and stderr UTF-8 with backslash escapes (F-14).

    Call it first in every CLI. A cp1252 or cp950 console can then never turn
    a finished run into a UnicodeEncodeError, and parent processes can decode
    the output as UTF-8. Console text should still be ASCII (see ascii_text).
    Streams without ``reconfigure`` (None under pythonw, test doubles) are left
    alone.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        with contextlib.suppress(ValueError, OSError):
            reconfigure(encoding="utf-8", errors="backslashreplace")


def ascii_text(text: str) -> str:
    """Return console-safe ASCII: arrows, dashes, x, middle dot and common typography
    are spelled out (``->``, ``-``, ``x``, ``.``); anything else is backslash-escaped.
    """
    return str(text).translate(_ASCII_MAP).encode("ascii", "backslashreplace").decode("ascii")


def _debugging() -> bool:
    return os.environ.get("FORGE_DEBUG", "") not in ("", "0")


def run_cli(main: Callable[..., Any], argv: Sequence[str] | None = None, *,
            expected: tuple[type[BaseException], ...] = CLI_EXPECTED_ERRORS) -> int:
    """Run a CLI ``main`` with the forge error convention and return its exit status.

    utf8_stdio() runs first. ``main()`` is called, or ``main(argv)`` when
    ``argv`` is given; its return value is the exit status (None means 0).
    SystemExit passes through untouched, so argparse usage errors keep their
    exit 2 with ``usage: ... error: ...`` and ``--help`` exits 0. An
    ``expected`` error (default CLI_EXPECTED_ERRORS: OSError, ValueError, which
    includes JSONDecodeError and UnicodeError, and Pillow's
    DecompressionBombError) prints ``error: <message>`` and returns 1. Any
    other exception prints ``error: internal error (<Type>: <message>)`` and
    returns 1, and so does any other BaseException, such as the
    pyo3_runtime.PanicException a Rust extension raises when it panics; Ctrl+C
    prints ``error: interrupted`` and returns 130. Messages go to stderr as
    ASCII, and tracebacks never reach the user unless ``FORGE_DEBUG=1``, which
    re-raises for developers. A CLI whose published report has status ``fail``
    returns 1 from ``main`` itself.

    Use: ``if __name__ == "__main__": raise SystemExit(forge_core.run_cli(main))``.
    """
    utf8_stdio()
    try:
        status = main() if argv is None else main(argv)
        return 0 if status is None else int(status)
    except SystemExit:
        raise
    except KeyboardInterrupt:
        if _debugging():
            raise
        print("error: interrupted", file=sys.stderr)
        return 130
    except BaseException as error:  # noqa: BLE001
        if _debugging():
            raise
        if isinstance(error, expected):
            message = str(error) or type(error).__name__
        else:
            message = f"internal error ({type(error).__name__}: {error})"
        print(ascii_text(f"error: {message}"), file=sys.stderr)
        return 1


def utc_timestamp(moment: datetime | None = None) -> str:
    """RFC 3339 UTC time with milliseconds, such as ``2026-10-05T12:00:00.000Z`` (common timestamp).

    ``moment`` defaults to now. An aware datetime is converted to UTC; a naive
    one is taken to be UTC already.
    """
    if moment is None:
        moment = datetime.now(timezone.utc)
    elif moment.utcoffset() is not None:
        moment = moment.astimezone(timezone.utc)
    return (f"{moment.year:04d}-{moment.month:02d}-{moment.day:02d}T{moment.hour:02d}:{moment.minute:02d}:"
            f"{moment.second:02d}.{moment.microsecond // 1000:03d}Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | os.PathLike) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(_CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def portable_path(path: str | os.PathLike, base: str | os.PathLike) -> str:
    """Return ``path`` as a POSIX path relative to the directory ``base``.

    Pass the directory that holds the manifest, not the manifest file. Inside
    staged_output() the stage and the final directory share a parent, so either
    gives the same answer. Without a relative route (another Windows drive) the
    absolute POSIX path is returned.
    """
    target = Path(path).resolve()
    try:
        return Path(os.path.relpath(target, Path(base).resolve())).as_posix()
    except ValueError:
        return target.as_posix()


# common.schema.json relPath: no leading slash, no drive letter or URL scheme, no backslash.
_REL_PATH = re.compile(r"^(?!/)(?![A-Za-z][A-Za-z0-9+.-]*:)[^\\]+$")
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


def manifest_path(path: str | os.PathLike, base: str | os.PathLike) -> str:
    """Return a manifest-relative POSIX path, or the filename across drives.

    The caller binds the filename to its content with a SHA-256 digest.
    Results must match common.schema.json's relPath format; invalid names raise ValueError.
    """
    relative = portable_path(path, base)
    if _REL_PATH.match(relative):
        return relative
    name = Path(path).name
    if name in ("", ".", ".."):
        name = Path(path).resolve().name
    if name in ("", ".", "..") or not _REL_PATH.match(name):
        raise ValueError(f"{Path(path).as_posix()} has no relative route from {Path(base).as_posix()} and its "
                         "name cannot be stored as a manifest-relative path; rename or move the file.")
    return name


def file_ref(path: str | os.PathLike, base: str | os.PathLike, *, sha256: str | None = None,
             size: int | None = None) -> dict[str, Any]:
    """A common fileRef ``{"path", "sha256", "bytes"}`` of ``path`` for a manifest in the directory ``base``.

    ``path`` follows manifest_path(). ``sha256`` and ``size`` default to the
    file's own; pass the values you already hold (for example of bytes you
    just read or wrote) to bind the reference to exactly that content. A
    passed digest is lower-cased and must be 64 hex digits.
    """
    path = Path(path)
    if sha256:
        digest = str(sha256).lower()
        if not _SHA256_HEX.match(digest):
            raise ValueError(f"sha256 must be 64 hexadecimal digits; got {sha256!r}.")
    else:
        digest = sha256_file(path)
    if size is None:
        length = path.stat().st_size
    else:
        length = operator.index(size)
        if length < 0:
            raise ValueError(f"size must be >= 0; got {size!r}.")
    return {"path": manifest_path(path, base), "sha256": digest, "bytes": length}


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate key {key!r}")
        result[key] = value
    return result


def _no_constant(name: str) -> Any:
    raise ValueError(f"{name} is not valid JSON")


def _finite_float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise ValueError(f"{text} is not a finite JSON number")
    return value


def parse_json(data: bytes | bytearray | memoryview | str, *, strict: bool = False) -> Any:
    """Parse a JSON document; bytes are UTF-8 with or without a BOM (``utf-8-sig``).

    A str may also start with a BOM (U+FEFF). ``strict`` additionally refuses
    what JSON forbids but Python's json module accepts: duplicate object keys,
    ``NaN``/``Infinity``/``-Infinity`` and number literals that overflow to
    infinity (``1e999``), so a strict document always survives write_json.
    Errors are ValueError (json.JSONDecodeError and UnicodeDecodeError are
    subclasses) without the file name; the caller adds it.
    """
    if isinstance(data, (bytes, bytearray, memoryview)):
        text = bytes(data).decode("utf-8-sig")
    elif isinstance(data, str):
        text = data[1:] if data.startswith("﻿") else data
    else:
        raise TypeError(f"parse_json needs bytes or str; got {type(data).__name__}.")
    if not strict:
        return json.loads(text)
    return json.loads(text, object_pairs_hook=_unique_pairs, parse_constant=_no_constant,
                      parse_float=_finite_float)


def read_json(path: str | os.PathLike, *, strict: bool = False) -> Any:
    """Read a JSON file as UTF-8 with an optional BOM; see parse_json.

    OSError (a missing or unreadable file) propagates unchanged; decoding and
    syntax problems raise ValueError without the file name.
    """
    return parse_json(Path(path).read_bytes(), strict=strict)


def _json_default(value: Any) -> Any:
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    hint = "; store paths with portable_path()" if isinstance(value, os.PathLike) else ""
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable{hint}")


def write_json(path: str | os.PathLike, data: Any, *, no_clobber: bool = True) -> None:
    """Write UTF-8 JSON (indent 2, ``ensure_ascii=False``, trailing newline).

    numpy scalars and arrays are converted; NaN and infinity are refused so the
    file stays valid for strict JSON readers such as browsers. With
    ``no_clobber`` an existing file raises FileExistsError; otherwise the file
    is replaced atomically.
    """
    payload = (json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False, default=_json_default)
               + "\n").encode("utf-8")
    path = Path(path)
    if no_clobber:
        with open(path, "xb") as stream:
            try:
                stream.write(payload)
            except BaseException:
                stream.close()
                path.unlink(missing_ok=True)
                raise
        return
    temporary = _create_unique(path.parent, f".{path.name}.", ".tmp")
    try:
        temporary.write_bytes(payload)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


_AT_FDCWD = -100
_RENAME_NOREPLACE = 1  # linux/fs.h
_RENAME_EXCL = 4  # macOS stdio.h, for renamex_np
_NO_ATOMIC_RENAME = frozenset(
    code for code in (errno.EINVAL, errno.ENOSYS, getattr(errno, "ENOTSUP", None),
                      getattr(errno, "EOPNOTSUPP", None))
    if code is not None
)


def _create_unique(parent: Path, prefix: str, suffix: str = "", *, directory: bool = False) -> Path:
    """Create an empty file or directory with a random unused name, honouring the umask."""
    for _ in range(100):
        candidate = parent / f"{prefix}{secrets.token_hex(4)}{suffix}"
        try:
            if directory:
                os.mkdir(candidate)
            else:
                os.close(os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0),
                                 0o666))
        except FileExistsError:
            continue
        return candidate
    raise FileExistsError(errno.EEXIST, "Could not create a unique staging name", str(parent))


@functools.lru_cache(maxsize=1)
def _libc() -> ctypes.CDLL:
    return ctypes.CDLL(None, use_errno=True)


def _rename_noreplace(source: Path, target: Path) -> None:
    """Rename atomically, refusing any existing ``target``; failures raise OSError with errno set."""
    if os.name == "nt":
        os.rename(source, target)  # MoveFileEx without REPLACE_EXISTING refuses even an empty directory
        return
    try:
        libc = _libc()
    except OSError as error:
        raise OSError(errno.ENOSYS, f"libc unavailable: {error}", str(target)) from error
    if sys.platform.startswith("linux"):
        rename = getattr(libc, "renameat2", None)
        argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        arguments = (_AT_FDCWD, os.fsencode(source), _AT_FDCWD, os.fsencode(target), _RENAME_NOREPLACE)
    elif sys.platform == "darwin":
        rename = getattr(libc, "renamex_np", None)
        argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        arguments = (os.fsencode(source), os.fsencode(target), _RENAME_EXCL)
    else:
        rename = None
    if rename is None:
        raise OSError(errno.ENOSYS, "No atomic no-replace rename on this platform", str(target))
    rename.argtypes = argtypes
    rename.restype = ctypes.c_int
    if rename(*arguments) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), str(target))


def _publish_by_exclusive_mkdir(stage: Path, final: Path) -> None:
    """Fallback publish: exclusive mkdir, move the children, remove the stage.

    The mkdir refuses anything that already exists. Until the last child has
    moved, other processes can see ``final`` partially populated, and a process
    that writes into the brand-new ``final`` in that window can collide with a
    child. On failure the moved children are returned to ``stage``.
    """
    os.mkdir(final)
    moved: list[tuple[Path, Path]] = []
    try:
        for child in sorted(stage.iterdir()):
            target = final / child.name
            os.rename(child, target)
            moved.append((target, child))
        os.rmdir(stage)
    except BaseException:
        for target, child in reversed(moved):
            with contextlib.suppress(OSError):
                os.rename(target, child)
        with contextlib.suppress(OSError):
            os.rmdir(final)
        raise


def publish_directory_no_replace(stage: str | os.PathLike, final: str | os.PathLike) -> None:
    """Publish the finished directory ``stage`` as ``final`` without replacing anything (F-03).

    ``stage`` must sit on the same filesystem as ``final``; staged_output()
    creates it beside ``final``. The rename is atomic where the OS has a
    no-replace rename: os.rename on Windows, renameat2(RENAME_NOREPLACE) on
    Linux, renamex_np(RENAME_EXCL) on macOS. When that primitive fails with
    EINVAL, ENOTSUP or ENOSYS (WSL drvfs mounts such as /mnt/c, some network
    filesystems, old kernels) the publish falls back to an exclusive mkdir and
    moving the children, which is not atomic: see _publish_by_exclusive_mkdir.
    An existing ``final``, even an empty directory created by a racing process,
    always raises FileExistsError and leaves ``stage`` untouched.
    """
    stage, final = Path(stage), Path(final)
    if os.path.lexists(final):
        raise FileExistsError(errno.EEXIST, "Refusing to replace existing output", str(final))
    try:
        _rename_noreplace(stage, final)
    except OSError as error:
        if error.errno not in _NO_ATOMIC_RENAME:
            raise
        _publish_by_exclusive_mkdir(stage, final)


def _copy_exclusive(source: Path, destination: Path) -> None:
    """Copy into a file that must not exist yet (open 'xb'), fsync, remove our partial copy on failure."""
    with open(source, "rb") as input_file:
        output_file = open(destination, "xb")
        try:
            with output_file:
                shutil.copyfileobj(input_file, output_file, _CHUNK)
                output_file.flush()
                os.fsync(output_file.fileno())
        except BaseException:
            destination.unlink(missing_ok=True)
            raise


def publish_file_no_replace(src: str | os.PathLike, dst: str | os.PathLike) -> None:
    """Publish a complete copy of ``src`` as ``dst``, never replacing ``dst``.

    The copy is written and fsynced beside ``dst`` and then hard-linked into
    place, so readers see either nothing or the whole file. Where hard links
    are unavailable (FAT/exFAT, some network or WSL mounts) it falls back to
    an exclusive ``open('xb')`` + fsync, which still never replaces but may be
    observed half-written. ``src`` is left in place. Callers publishing several
    sidecars roll back the ones already published when a later step fails.
    """
    src, dst = Path(src), Path(dst)
    if os.path.lexists(dst):
        raise FileExistsError(errno.EEXIST, "Refusing to replace existing file", str(dst))
    dst.parent.mkdir(parents=True, exist_ok=True)
    temporary = _create_unique(dst.parent, f".{dst.name}.", ".staged")
    try:
        with open(src, "rb") as input_file, open(temporary, "wb") as output_file:
            shutil.copyfileobj(input_file, output_file, _CHUNK)
            output_file.flush()
            os.fsync(output_file.fileno())
        try:
            os.link(temporary, dst)
        except FileExistsError:
            raise
        except (OSError, AttributeError, NotImplementedError):
            _copy_exclusive(temporary, dst)
    finally:
        temporary.unlink(missing_ok=True)


@contextlib.contextmanager
def staged_output(final: str | os.PathLike, prefix: str = "") -> Iterator[Path]:
    """Yield a new stage directory beside ``final``; publish it as ``final`` on a clean exit.

    ``final`` must not exist. Work and QA happen inside the stage. On any
    exception, including a failed publish, the stage is deleted and ``final``
    is never created, so a failed run leaves nothing behind. The stage shares
    ``final``'s parent, so relative paths computed inside it stay valid.
    """
    final = Path(final)
    if final.name in ("", ".", ".."):
        raise ValueError(f"Output directory needs a name: {final}")
    final = final.parent.resolve() / final.name
    if os.path.lexists(final):
        raise FileExistsError(errno.EEXIST, "Refusing to replace existing output", str(final))
    final.parent.mkdir(parents=True, exist_ok=True)
    stage = _create_unique(final.parent, f".{prefix}{final.name}.stage-", directory=True)
    try:
        yield stage
        publish_directory_no_replace(stage, final)
    finally:
        if os.path.lexists(stage):
            shutil.rmtree(stage, ignore_errors=True)


_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_SIXTEEN_BIT_GREY = ("I;16", "I;16B", "I;16L", "I;16N")
_MODE_BITS = {"1": 1, "I;16": 16, "I;16B": 16, "I;16L": 16, "I;16N": 16, "I": 32, "F": 32}


def _png_bit_depth(raw: bytes) -> int | None:
    if len(raw) >= 26 and raw[:8] == _PNG_SIGNATURE and raw[12:16] == b"IHDR":
        return raw[24]
    return None


def _to_rgba8(image: Image.Image, bit_depth: int) -> tuple[Image.Image, str]:
    """Convert a loaded frame to 8-bit RGBA and describe the conversion."""
    mode = image.mode
    transparency = image.info.get("transparency")
    if mode in _SIXTEEN_BIT_GREY or (mode == "I" and bit_depth == 16):
        values = np.asarray(image).astype(np.int64)
        grey = (values >> 8).astype(np.uint8)
        alpha = np.full(grey.shape, 255, np.uint8)
        note = f"{mode} 16-bit grey -> RGBA (>> 8)"
        if isinstance(transparency, int):
            alpha[values == transparency] = 0
            note += " + tRNS"
        return Image.fromarray(np.dstack([grey, grey, grey, alpha])), note
    if mode in ("I", "F"):
        raise ValueError(f"Unsupported {bit_depth}-bit {mode} image; export an 8- or 16-bit PNG.")
    decoder_shift = " (16-bit samples >> 8 by the decoder)" if bit_depth == 16 else ""
    if mode == "RGBA":
        return image.copy(), ("none" if not decoder_shift else "RGBA" + decoder_shift)
    note = mode if bit_depth >= 8 or mode == "1" else f"{mode} ({bit_depth}-bit)"
    if transparency is not None:
        note += "+tRNS"
    if mode == "CMYK":
        return image.convert("RGB").convert("RGBA"), "CMYK -> RGB (naive, ICC ignored) -> RGBA"
    return image.convert("RGBA"), f"{note} -> RGBA{decoder_shift}"


def load_rgba(path: str | os.PathLike, *, allow_animated: bool = False) -> tuple[Image.Image, dict[str, Any]]:
    """Load a still image as 8-bit straight-alpha RGBA, with provenance.

    Accepts RGB(A), palette PNGs with tRNS (including 1/2/4-bit), P/PA, L/LA,
    1-bit, 16-bit grey (high byte, ``>> 8``), 16-bit RGB(A) (high byte, taken
    by Pillow's decoder) and CMYK (naive conversion). Animated inputs raise
    ValueError unless ``allow_animated``, which loads frame 0. RGB hidden under
    alpha 0 is kept as stored; EXIF orientation and ICC profiles are ignored.

    The provenance dict holds ``path``, ``sha256``, ``bytes``, ``format``,
    ``source_mode``, ``bit_depth``, ``size``, ``frames`` and ``conversion``.
    """
    path = Path(path)
    raw = path.read_bytes()
    with Image.open(io.BytesIO(raw)) as source:
        frames = int(getattr(source, "n_frames", 1))
        if frames > 1 and not allow_animated:
            raise ValueError(f"Input is animated ({frames} frames); export a single still frame: {path}")
        source.load()
        bit_depth = _png_bit_depth(raw) or _MODE_BITS.get(source.mode, 8)
        image, conversion = _to_rgba8(source, bit_depth)
        info = {
            "path": path.resolve().as_posix(),
            "sha256": sha256_bytes(raw),
            "bytes": len(raw),
            "format": source.format,
            "source_mode": source.mode,
            "bit_depth": int(bit_depth),
            "size": list(image.size),
            "frames": frames,
            "conversion": conversion if frames == 1 else f"{conversion}; frame 0 of {frames}",
        }
    return image, info


def save_png(img: Image.Image | np.ndarray, path: str | os.PathLike, *, zero_transparent_rgb: bool = True) -> None:
    """Write an 8-bit RGBA, RGB, LA or L PNG deterministically, without metadata chunks.

    Only IHDR, IDAT and IEND are written (no text, time, ICC or EXIF carried
    over from the source). RGB under alpha 0 is zeroed unless
    ``zero_transparent_rgb`` is False. Indexed PNG is not written here.
    """
    image = img if isinstance(img, Image.Image) else Image.fromarray(np.asarray(img))
    if image.mode not in ("RGBA", "RGB", "LA", "L"):
        raise ValueError(f"save_png writes 8-bit RGBA, RGB, LA or L images; got mode {image.mode}.")
    if zero_transparent_rgb and image.mode in ("RGBA", "LA"):
        pixels = np.array(image)
        pixels[pixels[..., -1] == 0] = 0
        clean = Image.fromarray(pixels)
    else:
        clean = Image.frombytes(image.mode, image.size, image.tobytes())
    buffer = io.BytesIO()
    clean.save(buffer, format="PNG", optimize=False, compress_level=6)
    Path(path).write_bytes(buffer.getvalue())


def _scipy_ndimage() -> Any:
    """scipy.ndimage, or None when scipy is missing or FORGE_CORE_NO_SCIPY forces the numpy fallback."""
    if os.environ.get("FORGE_CORE_NO_SCIPY", "") not in ("", "0"):
        return None
    try:
        from scipy import ndimage
    except ImportError:
        return None
    return ndimage


def _alpha_plane(source: Any) -> np.ndarray:
    """2-D alpha (or mask) plane of an Image or array; images without alpha count as opaque."""
    if isinstance(source, Image.Image):
        if source.mode in ("L", "1"):
            return np.asarray(source)
        if "A" not in source.getbands():
            source = source.convert("RGBA")
        return np.asarray(source.getchannel("A"))
    array = np.asarray(source)
    if array.ndim == 2:
        return array
    if array.ndim == 3 and array.shape[2] in (2, 4):
        return array[..., -1]
    if array.ndim == 3 and array.shape[2] == 3:
        return np.full(array.shape[:2], 255, np.uint8)
    raise ValueError(f"Expected an alpha plane, a mask or an RGBA image; got shape {array.shape}.")


def _as_mask(mask: Any) -> np.ndarray:
    plane = _alpha_plane(mask)
    return plane if plane.dtype == bool else plane > 0


def _mask_bbox(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    rows = np.flatnonzero(mask.any(axis=1))
    if rows.size == 0:
        return None
    columns = np.flatnonzero(mask.any(axis=0))
    return int(columns[0]), int(rows[0]), int(columns[-1]) + 1, int(rows[-1]) + 1


def subject_mask(alpha: Any, threshold: int = ALPHA_GEOMETRY_THRESHOLD) -> np.ndarray:
    """Pixels that count for geometry: ``alpha > threshold``. Boolean input is returned as is."""
    plane = _alpha_plane(alpha)
    return plane.copy() if plane.dtype == bool else plane > threshold


def subject_bbox(alpha: Any, threshold: int = ALPHA_GEOMETRY_THRESHOLD) -> tuple[int, int, int, int] | None:
    """``(x0, y0, x1, y1)`` of subject_mask(alpha, threshold), or None when it is empty."""
    return _mask_bbox(subject_mask(alpha, threshold))


def _hook_and_compress(count: int, first: np.ndarray, second: np.ndarray) -> np.ndarray:
    """Union-find over ``count`` nodes and edges first[i]-second[i], fully vectorised.

    Each round hooks every root to the smallest root it touches, then
    pointer-jumps until each node points at its root. A root never moves to a
    larger index, so every component ends rooted at its smallest node.
    """
    parent = np.arange(count, dtype=np.int64)
    while first.size:
        root_a, root_b = parent[first], parent[second]
        active = root_a != root_b
        if not active.any():
            break
        first, second = first[active], second[active]
        low = np.minimum(root_a[active], root_b[active])
        high = np.maximum(root_a[active], root_b[active])
        np.minimum.at(parent, high, low)
        while True:
            jumped = parent[parent]
            if np.array_equal(jumped, parent):
                break
            parent = jumped
    return parent


def _label_runs(mask: np.ndarray, connectivity: int) -> tuple[np.ndarray, int]:
    """Numpy run-length union-find labelling; labels follow raster order like scipy.ndimage.label."""
    height, width = mask.shape
    labels = np.zeros((height, width), np.int32)
    stride = width + 2
    padded = np.zeros((height, stride), np.int8)
    padded[:, 1:-1] = mask
    delta = np.diff(padded.ravel())
    starts = np.flatnonzero(delta == 1) + 1
    if starts.size == 0:
        return labels, 0
    ends = np.flatnonzero(delta == -1) + 1
    rows = starts // stride
    run_start = starts - rows * stride - 1
    run_end = ends - rows * stride - 1  # exclusive
    # Keys are monotonic over all runs, so one searchsorted finds the touching runs of the previous row.
    key_start, key_end = rows * stride + run_start, rows * stride + run_end
    previous = (rows - 1) * stride
    if connectivity == 8:  # touching includes diagonal contact
        low = np.searchsorted(key_end, previous + run_start, side="left")
        high = np.searchsorted(key_start, previous + run_end, side="right")
    else:
        low = np.searchsorted(key_end, previous + run_start, side="right")
        high = np.searchsorted(key_start, previous + run_end, side="left")
    counts = np.maximum(high - low, 0)
    total = int(counts.sum())
    run_count = starts.size
    if total:
        source = np.repeat(np.arange(run_count), counts)
        offsets = np.arange(total) - np.repeat(np.cumsum(counts) - counts, counts)
        parent = _hook_and_compress(run_count, source, np.repeat(low, counts) + offsets)
    else:
        parent = np.arange(run_count)
    rank = np.cumsum(parent == np.arange(run_count))
    labels.reshape(-1)[np.flatnonzero(mask)] = np.repeat(rank[parent].astype(np.int32), run_end - run_start)
    return labels, int(rank[-1])


def label_components(mask: Any, connectivity: int = 8) -> tuple[np.ndarray, int]:
    """Label connected True pixels: ``(labels int32, count)`` with labels 1..count in raster order.

    8-connectivity is the default so 1-px diagonal strokes stay whole. Uses scipy.ndimage when available; otherwise, or with
    ``FORGE_CORE_NO_SCIPY=1``, an equivalent numpy run-length union-find.
    """
    if connectivity not in (4, 8):
        raise ValueError(f"connectivity must be 4 or 8; got {connectivity!r}.")
    mask = np.asarray(mask, dtype=bool)
    if mask.ndim != 2:
        raise ValueError(f"label_components needs a 2-D mask; got shape {mask.shape}.")
    if mask.size == 0:
        return np.zeros(mask.shape, np.int32), 0
    ndimage = _scipy_ndimage()
    if ndimage is None:
        return _label_runs(mask, connectivity)
    structure = np.ones((3, 3), bool) if connectivity == 8 else ndimage.generate_binary_structure(2, 1)
    labels, count = ndimage.label(mask, structure=structure)
    return labels.astype(np.int32, copy=False), int(count)


def connected_components(alpha_or_rgba: Any, *, threshold: int = 0, min_area: int = 1, connectivity: int = 8,
                         with_masks: bool = False) -> list[dict[str, Any]]:
    """Components of ``alpha > threshold``, largest first (ties keep raster order).

    Accepts an alpha plane, a boolean mask (threshold ignored), an RGBA array
    or an Image. Each dict holds ``label`` (as in label_components), ``area``,
    ``bbox`` ``(x0, y0, x1, y1)`` and ``touches_edge``; with ``with_masks`` it
    also holds ``mask``, a boolean array cropped to ``bbox``. Components
    smaller than ``min_area`` are omitted.
    """
    plane = _alpha_plane(alpha_or_rgba)
    mask = plane if plane.dtype == bool else plane > threshold
    labels, count = label_components(mask, connectivity)
    if count == 0:
        return []
    height, width = mask.shape
    areas = np.bincount(labels.ravel(), minlength=count + 1)
    ys, xs = np.nonzero(labels)
    ids = labels[ys, xs]
    x0 = np.full(count + 1, width, np.int64)
    y0 = np.full(count + 1, height, np.int64)
    x1 = np.zeros(count + 1, np.int64)
    y1 = np.zeros(count + 1, np.int64)
    np.minimum.at(x0, ids, xs)
    np.minimum.at(y0, ids, ys)
    np.maximum.at(x1, ids, xs + 1)
    np.maximum.at(y1, ids, ys + 1)
    kept = np.flatnonzero(areas[1:] >= min_area) + 1
    components = []
    for label in kept[np.argsort(-areas[kept], kind="stable")].tolist():
        box = (int(x0[label]), int(y0[label]), int(x1[label]), int(y1[label]))
        item: dict[str, Any] = {
            "label": label,
            "area": int(areas[label]),
            "bbox": box,
            "touches_edge": box[0] == 0 or box[1] == 0 or box[2] == width or box[3] == height,
        }
        if with_masks:
            item["mask"] = labels[box[1]:box[3], box[0]:box[2]] == label
        components.append(item)
    return components


def _mask2d(mask: Any, name: str) -> np.ndarray:
    array = np.asarray(mask, dtype=bool)
    if array.ndim != 2:
        raise ValueError(f"{name} needs a 2-D mask; got shape {array.shape}.")
    return array


def dilate_square(mask: Any, radius: int) -> np.ndarray:
    """Chebyshev (square) dilation of a mask by ``radius`` px, from a summed-area table.

    A pixel is True when a True pixel lies within ``radius`` px in x and in y.
    Windows are clipped at the canvas, so the exterior never counts: on a mask
    this equals Pillow's MaxFilter(2 * radius + 1). ``radius`` <= 0 returns a
    copy. One pass for any radius; a radius beyond the image is clamped, which
    changes nothing. Non-boolean masks mean ``!= 0``.
    """
    mask = _mask2d(mask, "dilate_square")
    radius = min(operator.index(radius), max(mask.shape, default=0))
    if radius <= 0 or mask.size == 0:
        return mask.copy()
    size = 2 * radius + 1
    accumulator = np.int32 if mask.size < 2 ** 31 else np.int64  # the table never exceeds the True count
    table = np.pad(np.pad(mask, radius).astype(accumulator).cumsum(0).cumsum(1), ((1, 0), (1, 0)))
    window = table[size:, size:] - table[:-size, size:] - table[size:, :-size] + table[:-size, :-size]
    return window > 0


_dilate_square = dilate_square  # Compatibility alias used by alpha_hygiene.


def _grow8(mask: np.ndarray) -> np.ndarray:
    """One 3 x 3 (8-neighbour) dilation step; the canvas exterior never counts."""
    grown = mask.copy()
    grown[:, 1:] |= mask[:, :-1]
    grown[:, :-1] |= mask[:, 1:]
    result = grown.copy()
    result[1:] |= grown[:-1]
    result[:-1] |= grown[1:]
    return result


def distance_to(mask: Any, cap: int) -> np.ndarray:
    """Chebyshev (8-neighbour) distance from every pixel to the nearest True pixel of ``mask``, capped.

    Pixels farther than ``cap``, and every pixel of an empty mask, get
    ``cap + 1``; the canvas exterior is not part of the mask. The dtype is
    uint8 while ``cap + 1`` fits (cap <= 254), then uint16, then int32. For
    every ``r <= cap``, ``distance_to(mask, cap) <= r`` equals
    ``dilate_square(mask, r)``. Ring by ring, so the cost grows with ``cap``
    (it stops early once nothing new is reached): meant for small caps such as
    forge_matte's alpha and colour bands.
    """
    mask = _mask2d(mask, "distance_to")
    cap = operator.index(cap)
    if cap < 0:
        raise ValueError(f"cap must be >= 0; got {cap}.")
    dtype = np.uint8 if cap < 255 else (np.uint16 if cap < 65535 else np.int32)
    distance = np.full(mask.shape, cap + 1, dtype)
    distance[mask] = 0
    reached = mask.copy()
    for step in range(1, cap + 1):
        grown = _grow8(reached)
        new = grown & ~reached
        if not new.any():
            break  # nothing left to reach (all reached, or an empty mask): the rest keep cap + 1
        distance[new] = step
        reached = grown
    return distance


def _rgba_array(source: Any) -> np.ndarray:
    """8-bit straight-alpha RGBA array view of an Image or array; premultiplied modes are refused."""
    if isinstance(source, Image.Image):
        if source.mode in ("RGBa", "La"):
            raise ValueError(f"Expected straight alpha; got premultiplied mode {source.mode}.")
        return np.asarray(source if source.mode == "RGBA" else source.convert("RGBA"))
    array = np.asarray(source)
    if array.dtype != np.uint8 or array.ndim != 3 or array.shape[2] not in (3, 4):
        raise ValueError(f"Expected an 8-bit RGB or RGBA array; got {array.dtype} {array.shape}.")
    if array.shape[2] == 3:
        return np.dstack([array, np.full(array.shape[:2], 255, np.uint8)])
    return array


def alpha_hygiene(rgba: Any, mode: str = "both", floor: int = 4, solid_min: int = 32,
                  attach_radius: int = 2) -> tuple[Image.Image, dict[str, Any]]:
    """Remove generator alpha noise without touching visible art.

    ``floor`` zeroes pixels with ``0 < alpha <= floor``. ``detached`` removes
    8-connected ``alpha > 0`` islands with no pixel within ``attach_radius``
    (Chebyshev) of a solid pixel (``alpha >= solid_min``), so faint glow that
    hugs the art survives. ``both`` applies floor, then detached. Removed
    pixels become (0, 0, 0, 0); every other pixel is unchanged. The report
    holds ``floor_px``, ``detached_px``, ``detached_components`` and
    ``max_removed_alpha`` with the settings used.
    """
    if mode not in HYGIENE_MODES:
        raise ValueError(f"Unknown hygiene mode {mode!r}; use one of {', '.join(HYGIENE_MODES)}.")
    if not 0 <= floor <= 255 or not 1 <= solid_min <= 255 or attach_radius < 0:
        raise ValueError("Hygiene needs 0 <= floor <= 255, 1 <= solid_min <= 255 and attach_radius >= 0.")
    pixels = _rgba_array(rgba).copy()
    alpha = pixels[..., 3]
    removed = np.zeros(alpha.shape, bool)
    report: dict[str, Any] = {
        "mode": mode, "floor": floor, "solid_min": solid_min, "attach_radius": attach_radius,
        "connectivity": 8, "floor_px": 0, "detached_px": 0, "detached_components": 0, "max_removed_alpha": 0,
    }
    if mode in ("floor", "both"):
        removed = (alpha > 0) & (alpha <= floor)
        report["floor_px"] = int(removed.sum())
    if mode in ("detached", "both"):
        visible = (alpha > 0) & ~removed
        labels, count = label_components(visible, 8)
        if count:
            anchored = np.zeros(count + 1, bool)
            anchored[labels[_dilate_square(visible & (alpha >= solid_min), attach_radius)]] = True
            anchored[0] = True
            detached = ~anchored[labels]
            report["detached_px"] = int(detached.sum())
            report["detached_components"] = int(count + 1 - anchored.sum())
            removed |= detached
    if removed.any():
        report["max_removed_alpha"] = int(alpha[removed].max())
        pixels[removed] = 0
    return Image.fromarray(pixels), report


_HALF = Fraction(1, 2)
_DECIMAL_HALF = decimal.Decimal("0.5")
_ASPECT = re.compile(r"\s*([0-9]*\.?[0-9]+)\s*(?:[:/]\s*([0-9]*\.?[0-9]+))?\s*")


def round_half_up(value: Any) -> int:
    """Nearest integer with halves rounded up, ``floor(value + 1/2)``: 2.5 -> 3, -2.5 -> -2.

    Never banker's rounding. Integers come back unchanged; Fractions (any
    exact rational) and Decimals round exactly. Floats, numpy floats
    included, compute ``floor(value + 0.5)`` in floating point exactly as the
    private copies did, so the one float below a half that the addition
    rounds up (0.49999999999999994) gives 1; pass a Fraction for exact
    rational timing. NaN raises ValueError and infinity OverflowError.
    """
    if isinstance(value, numbers.Integral):
        return int(value)
    if isinstance(value, numbers.Rational):
        return int(math.floor(value + _HALF))
    if isinstance(value, decimal.Decimal):
        return int(math.floor(value + _DECIMAL_HALF))
    return int(math.floor(value + 0.5))


_round_half_up = round_half_up  # Compatibility alias.


def ground_row(mask: Any, *, min_run: int = 1) -> int:
    """Ground line: bottom edge of the lowest stable row, i.e. that row's index + 1.

    A row is stable when it holds at least ``min_run`` mask pixels; raise
    ``min_run`` to ignore thin tips or specks below the feet.
    """
    rows = np.flatnonzero(_as_mask(mask).sum(axis=1) >= max(1, min_run))
    if rows.size == 0:
        raise ValueError("ground_row needs a mask with at least one stable row.")
    return int(rows[-1]) + 1


def anchor_from_mask(mask: Any, mode: str = "feet", band_rows: int = 12,
                     subject_bbox: Sequence[int] | None = None, *, min_run: int = 1) -> tuple[float, float]:
    """Registration anchor ``(x, y)`` of a subject mask, in continuous pixel coordinates.

    ``feet``: median column of the support band, on the ground line.
    ``stance``: midpoint of the support band's horizontal extent, on the
    ground line; it mirrors exactly, so a turn does not slide the feet.
    ``bbox``: horizontal centre and bottom edge of the bounding box.
    ``centroid``: mean pixel centre. ``center``: centre of the bounding box.
    The support band is the ``band_rows`` rows above ground_row(); scale it
    with the subject height. ``subject_bbox`` restricts every mode to that box
    (the selected component's), so a weapon outside it cannot move the
    anchor.
    """
    if mode not in ANCHOR_MODES:
        raise ValueError(f"Unknown anchor mode {mode!r}; use one of {', '.join(ANCHOR_MODES)}.")
    if band_rows < 1:
        raise ValueError("band_rows must be at least 1.")
    mask = _as_mask(mask)
    if subject_bbox is not None:
        left, top, right, bottom = (max(0, int(value)) for value in subject_bbox)
        restricted = np.zeros_like(mask)
        restricted[top:bottom, left:right] = mask[top:bottom, left:right]
        mask = restricted
    box = _mask_bbox(mask)
    if box is None:
        raise ValueError("anchor_from_mask needs a non-empty mask.")
    x0, y0, x1, y1 = box
    if mode == "center":
        return (x0 + x1) / 2, (y0 + y1) / 2
    if mode == "bbox":
        return (x0 + x1) / 2, float(y1)
    if mode == "centroid":
        ys, xs = np.nonzero(mask)
        return float(xs.mean()) + 0.5, float(ys.mean()) + 0.5
    ground = ground_row(mask, min_run=min_run)
    band = mask[max(0, ground - band_rows):ground]
    if mode == "stance":
        columns = np.flatnonzero(band.any(axis=0))
        return (int(columns[0]) + int(columns[-1]) + 1) / 2, float(ground)
    return float(np.median(np.nonzero(band)[1])) + 0.5, float(ground)


def integer_scale(scale: float, tol: float = 1e-6) -> int:
    """Return ``scale`` as a positive integer; raise ValueError for fractional scales."""
    value = float(scale)
    nearest = round(value) if math.isfinite(value) else 0
    if nearest < 1 or abs(value - nearest) > tol:
        raise ValueError(f"Nearest resampling needs an integer scale (1, 2, 3, ...); got {scale!r}.")
    return int(nearest)


_FILTERS = {"box": (Image.Resampling.BOX, 0.5), "lanczos": (Image.Resampling.LANCZOS, 3.0)}


def _filter_for(resampler: str, scale: float) -> tuple[Image.Resampling, float]:
    """Pillow filter and support; reductions of 2x or more always use the box (area) filter."""
    return _FILTERS["box" if resampler == "box" or scale <= 0.5 else resampler]


def _unpremultiply(planes: list[np.ndarray]) -> Image.Image:
    """Back to straight 8-bit RGBA. Colour is divided by the unclipped alpha, so filter
    overshoot (alpha above 1 next to an edge) cannot brighten it.
    """
    alpha = planes[3]
    alpha8 = np.floor(np.clip(alpha, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
    premultiplied = np.clip(np.stack(planes[:3], axis=-1), 0.0, None)
    rgb = np.floor(premultiplied / np.maximum(alpha, 1e-6)[..., None] + 0.5)
    rgb = np.clip(rgb, 0, 255).astype(np.uint8)
    rgb[alpha8 == 0] = 0
    return Image.fromarray(np.dstack([rgb, alpha8]))


def _resample_nearest(pixels: np.ndarray, scale: float, anchor_src: tuple[float, float] | None,
                      anchor_dst: tuple[float, float], out_size: tuple[int, int]) -> Image.Image:
    upscale = scale >= 1
    factor = integer_scale(scale if upscale else 1.0 / scale)
    height, width = pixels.shape[:2]
    if anchor_src is None:
        if not upscale and (width % factor or height % factor):
            raise ValueError(f"Nearest reduction by {factor} needs dimensions divisible by {factor}; got "
                             f"{width}x{height}. Pass anchor_src to place the logical grid.")
        expected = (width * factor, height * factor) if upscale else (width // factor, height // factor)
        if out_size != expected:
            raise ValueError(f"Nearest resampling of {width}x{height} by {scale:g} gives {expected}, "
                             f"not {out_size}; pass anchors to crop or pad.")
        anchor_src = (0.0, 0.0)

    def sample(count: int, anchor: float, target: float, limit: int) -> tuple[np.ndarray, np.ndarray]:
        """Source index under each output pixel centre, split at the anchor's integer pixel."""
        base = math.floor(anchor)
        centres = np.arange(count) + 0.5 - target
        steps = centres / factor if upscale else centres * factor
        index = base + np.floor(steps + (anchor - base)).astype(np.int64)
        return np.clip(index, 0, limit - 1), (index >= 0) & (index < limit)

    columns, valid_x = sample(out_size[0], anchor_src[0], anchor_dst[0], width)
    rows, valid_y = sample(out_size[1], anchor_src[1], anchor_dst[1], height)
    result = pixels[np.ix_(rows, columns)]
    result[~(valid_y[:, None] & valid_x[None, :])] = 0
    result[result[..., 3] == 0] = 0
    return Image.fromarray(result)


def resample_rgba(img: Any, scale: float, resampler: str = "lanczos", *,
                  anchor_src: Sequence[float] | None = None, anchor_dst: Sequence[float] | None = None,
                  out_size: Sequence[int] | None = None) -> Image.Image:
    """Resample straight-alpha RGBA on premultiplied float channels.

    Every channel is premultiplied and resized as its own float image, so
    Pillow never premultiplies a second time; premultiplied input modes
    (``RGBa``, ``La``) are refused. ``box`` averages areas; ``lanczos`` also
    switches to the box filter for reductions of 2x or more; ``nearest``
    accepts only integer scales ``N`` or ``1/N`` (reductions sample the centre
    of each logical pixel) and raises ValueError otherwise.

    Without anchors the whole image is mapped onto ``out_size`` (default
    ``round(size * scale)``), with Pillow's edge handling for opaque art. With
    ``anchor_src`` the grid is pinned: source point ``anchor_src`` lands
    exactly on ``anchor_dst`` (default ``anchor_src * scale``), the scale is
    exact, and everything outside the source is transparent. A pinned result
    depends only on the pixels around the anchor: the same frame cropped or
    placed differently (image and ``anchor_src`` shifted by whole pixels, same
    ``anchor_dst``) gives byte-identical output, so a rest pose shared by two
    clips stays identical.

    Caveat: ``lanczos`` rings just outside an edge, and dividing that
    tiny premultiplied ringing by an alpha of 1-4 (out of 255) invents
    saturated colours there, often key-leaning ones such as (255, 222, 247).
    They are invisible (under 2% opacity) but fool colour-based QA: B06's
    registered frames carried 1.2-5.9% outer-ring "spill" from them, and a
    clean frame resampled to 0.9x showed 6.5% (``box`` showed none). Run
    ``alpha_hygiene(result, mode="floor")`` (floor 4) on resampled frames
    that will be published or gated, or measure colour QA on a copy with
    alpha <= ALPHA_GEOMETRY_THRESHOLD zeroed, as the residue gate does.
    """
    if resampler not in RESAMPLERS:
        raise ValueError(f"Unknown resampler {resampler!r}; use one of {', '.join(RESAMPLERS)}.")
    scale = float(scale)
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError(f"Scale must be positive and finite; got {scale!r}.")
    if anchor_dst is not None and anchor_src is None:
        raise ValueError("anchor_dst needs anchor_src.")
    pixels = _rgba_array(img)
    height, width = pixels.shape[:2]
    if out_size is None:
        size = (max(1, _round_half_up(width * scale)), max(1, _round_half_up(height * scale)))
    else:
        size = (int(out_size[0]), int(out_size[1]))
        if min(size) < 1:
            raise ValueError(f"out_size must be positive; got {tuple(out_size)}.")
    source_anchor = None if anchor_src is None else (float(anchor_src[0]), float(anchor_src[1]))
    target_anchor = (0.0, 0.0) if source_anchor is None else (
        (source_anchor[0] * scale, source_anchor[1] * scale) if anchor_dst is None
        else (float(anchor_dst[0]), float(anchor_dst[1])))
    if resampler == "nearest":
        return _resample_nearest(pixels, scale, source_anchor, target_anchor, size)

    alpha = pixels[..., 3].astype(np.float32) / 255.0
    if source_anchor is None:
        resample_filter, _support = _filter_for(resampler, max(size[0] / width, size[1] / height))
        planes = [pixels[..., channel].astype(np.float32) * alpha for channel in range(3)] + [alpha]
        resized = [np.asarray(Image.fromarray(plane).resize(size, resample_filter)) for plane in planes]
        return _unpremultiply(resized)

    resample_filter, support = _filter_for(resampler, scale)
    # The canvas covers every filter window of every output pixel, so Pillow never clips a window
    # (clipping renormalises weights and would make the result depend on the crop).
    pad = math.ceil(support * max(1.0, 1.0 / scale)) + 2
    # Work relative to the anchor's integer pixel so integer shifts of the input give identical floats.
    base_x, base_y = math.floor(source_anchor[0]), math.floor(source_anchor[1])
    left = source_anchor[0] - base_x - target_anchor[0] / scale
    top = source_anchor[1] - base_y - target_anchor[1] / scale
    span_x, span_y = size[0] / scale, size[1] / scale
    col0, row0 = math.floor(left) - pad, math.floor(top) - pad
    col1, row1 = math.ceil(left + span_x) + pad, math.ceil(top + span_y) + pad
    canvas = np.zeros((row1 - row0, col1 - col0, 4), np.float32)
    src_x0, src_x1 = max(0, base_x + col0), min(width, base_x + col1)
    src_y0, src_y1 = max(0, base_y + row0), min(height, base_y + row1)
    if src_x0 < src_x1 and src_y0 < src_y1:
        region = pixels[src_y0:src_y1, src_x0:src_x1].astype(np.float32)
        region_alpha = region[..., 3:] / 255.0
        cy, cx = src_y0 - (base_y + row0), src_x0 - (base_x + col0)
        canvas[cy:cy + region.shape[0], cx:cx + region.shape[1], :3] = region[..., :3] * region_alpha
        canvas[cy:cy + region.shape[0], cx:cx + region.shape[1], 3] = region_alpha[..., 0]
    box = (left - col0, top - row0, left - col0 + span_x, top - row0 + span_y)
    resized = [np.asarray(Image.fromarray(np.ascontiguousarray(canvas[..., channel])).resize(
        size, resample_filter, box=box)) for channel in range(4)]
    return _unpremultiply(resized)


_SEAM_EPSILON = 1e-6


def frame_durations(total_ms: int, n: int) -> list[int]:
    """Split ``total_ms`` into ``n`` integer frame durations that sum exactly.

    Frame ``i`` ends at ``round_half_up((i + 1) * total_ms / n)``, so the
    playhead never drifts more than 0.5 ms and durations differ by at most
    1 ms. Each frame needs at least 1 ms.
    """
    total_ms, n = operator.index(total_ms), operator.index(n)
    if n < 1:
        raise ValueError("Frame count must be at least 1.")
    if total_ms < n:
        raise ValueError(f"{total_ms} ms cannot hold {n} frames of at least 1 ms.")
    edges = [(2 * index * total_ms + n) // (2 * n) for index in range(n + 1)]
    return [end - start for start, end in zip(edges, edges[1:])]


def rational_fps(n: int, total_ms: int) -> str:
    """Exact frame rate of ``n`` frames in ``total_ms`` as a reduced ``"num/den"`` (ffmpeg syntax)."""
    n, total_ms = operator.index(n), operator.index(total_ms)
    if n < 1 or total_ms < 1:
        raise ValueError("Frame count and duration must be positive.")
    rate = Fraction(1000 * n, total_ms)
    return f"{rate.numerator}/{rate.denominator}"


def _premultiplied(frame: Any) -> np.ndarray:
    pixels = _rgba_array(frame).astype(np.float64)
    pixels[..., :3] *= pixels[..., 3:] / 255.0
    return pixels


def _weights(mask: Any, shape: tuple[int, int]) -> np.ndarray | None:
    if mask is None:
        return None
    plane = _alpha_plane(mask)
    weights = plane.astype(np.float64) if plane.dtype == bool else plane.astype(np.float64) / 255.0
    if weights.shape != shape:
        raise ValueError(f"Mask shape {weights.shape} does not match frames {shape}.")
    if weights.sum() <= 0:
        raise ValueError("Mask selects no pixels.")
    return weights


def _mean_difference(a: np.ndarray, b: np.ndarray, weights: np.ndarray | None) -> float:
    if a.shape != b.shape:
        raise ValueError(f"Frames differ in size: {a.shape[:2]} vs {b.shape[:2]}.")
    per_pixel = np.abs(a - b).mean(axis=-1)
    if weights is None:
        return float(per_pixel.mean())
    return float((per_pixel * weights).sum() / weights.sum())


def seam_report(frames: Iterable[Any], *, mask: Any = None) -> dict[str, Any]:
    """Loop seam normalised by the clip's own motion.

    ``seam`` is transition_mae(last, first); the adjacent steps are the
    transitions between neighbours. ``seam_over_median`` and ``seam_over_p95``
    near 1 mean a seamless loop, well above 1 a pop at the wrap, near 0 a held
    duplicate frame. Denominators are floored at 1e-6. Measure the decoded
    runtime file, inside the motion mask, for video loops.
    """
    iterator = iter(frames)
    try:
        first = previous = _premultiplied(next(iterator))
    except StopIteration:
        raise ValueError("seam_report needs at least two frames.") from None
    weights = _weights(mask, first.shape[:2])
    steps = []
    for frame in iterator:
        current = _premultiplied(frame)
        steps.append(_mean_difference(previous, current, weights))
        previous = current
    if not steps:
        raise ValueError("seam_report needs at least two frames.")
    seam = _mean_difference(previous, first, weights)
    adjacent = np.asarray(steps)
    median, p95 = float(np.median(adjacent)), float(np.percentile(adjacent, 95))
    return {
        "frames": len(steps) + 1,
        "seam": seam,
        "adjacent_median": median,
        "adjacent_p95": p95,
        "adjacent_max": float(adjacent.max()),
        "seam_over_median": seam / max(median, _SEAM_EPSILON),
        "seam_over_p95": seam / max(p95, _SEAM_EPSILON),
        "method": "premultiplied RGBA mean absolute difference (0-255); seam = last -> first",
    }
