"""FFmpeg/FFprobe discovery, stream inspection and RGBA decoding (API 1).

Requires FFmpeg 5.1+. Capability probes verify RGBA decoding and stream inspection.
Images use straight-alpha RGBA.
Canonical copies and skill destinations are listed in shared/VENDORED.json.
"""
from __future__ import annotations

import copy
import functools
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from fractions import Fraction
from pathlib import Path
from typing import Iterator, Mapping, Sequence

import numpy as np
from PIL import Image

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import comfyui_forge_core  # noqa: E402  (the sibling copy: shared/ or the skill's scripts/)

if str(getattr(comfyui_forge_core, "FORGE_CORE_API_VERSION", "")).split(".")[0] != "1":
    raise ImportError("forge_av needs forge_core API version 1.x next to it; run tools/comfyui_forge_vendor_sync.py --write.")

DEFAULT_TIMEOUT = 300.0
ALPHA_MODES = ("auto", "on", "off")

# The native VP8/VP9 decoders ignore WebM's alpha side channel; libvpx keeps it.
_ALPHA_DECODERS = {"vp8": "libvpx", "vp9": "libvpx-vp9"}
_ALPHA_PIX_FMT = re.compile(r"^(yuva|gbrap|ya\d|rgba|bgra|argb|abgr|ayuv|vuya|pal8)")
_FFMPEG_GLOBAL = ("-hide_banner", "-loglevel", "error", "-nostdin", "-n")


class ForgeAVError(RuntimeError):
    """ffmpeg/ffprobe is missing, failed, timed out or produced unusable output."""


def run(cmd: Sequence[str], timeout: float = DEFAULT_TIMEOUT) -> str:
    """Run ``cmd`` and return its stdout decoded as UTF-8 (errors replaced).

    stdin is closed, so ffmpeg can never wait for keyboard input. A missing
    executable, a timeout or a non-zero exit raises ForgeAVError with the tail
    of stderr.
    """
    argv = [str(part) for part in cmd]
    try:
        proc = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=_positive(timeout, "timeout"))
    except FileNotFoundError as exc:
        raise ForgeAVError(f"executable not found: {argv[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ForgeAVError(f"{Path(argv[0]).stem} timed out after {timeout:g} s") from exc
    if proc.returncode:
        raise ForgeAVError(_failure(argv, proc.returncode, proc.stderr or proc.stdout))
    return proc.stdout


class _Child:
    """A watched ffmpeg child process: killed on timeout or when left early."""

    def __init__(self, argv: list[str], *, stdin, stdout, timeout: float) -> None:
        self.argv, self.timeout = argv, _positive(timeout, "timeout")
        self.expired = threading.Event()
        self._errors = tempfile.TemporaryFile()
        try:
            self.proc = subprocess.Popen(argv, stdin=stdin, stdout=stdout, stderr=self._errors)
        except FileNotFoundError as exc:
            self._errors.close()
            raise ForgeAVError(f"executable not found: {argv[0]}") from exc
        self._timer = threading.Timer(self.timeout, self._expire)
        self._timer.daemon = True
        self._timer.start()

    def _expire(self) -> None:
        self.expired.set()
        self.proc.kill()

    def __enter__(self) -> _Child:
        return self

    def __exit__(self, *exc_info) -> None:
        self._timer.cancel()
        if self.proc.poll() is None:
            self.proc.kill()
        self.proc.wait()
        for pipe in (self.proc.stdin, self.proc.stdout):
            if pipe:
                try:
                    pipe.close()
                except OSError:
                    pass
        self._errors.close()

    def finish(self) -> None:
        """Wait for exit; raise ForgeAVError on a timeout or a non-zero status."""
        code = self.proc.wait()
        if self.expired.is_set():
            raise ForgeAVError(f"{Path(self.argv[0]).stem} timed out after {self.timeout:g} s")
        if code:
            self._errors.seek(0)
            raise ForgeAVError(_failure(self.argv, code, self._errors.read().decode("utf-8", "replace")))


def _unlink_settled(path: Path, *, attempts: int = 60, delay: float = 0.05) -> None:
    """Remove ``path`` if present. On Windows, retry for up to 3 s while another process holds it.

    A killed ffmpeg can release its output a moment after exiting, and real-time antivirus
    scans briefly lock fresh files. Without the retry, cleanup would leave a partial file behind.
    """
    for attempt in range(attempts):
        try:
            path.unlink(missing_ok=True)
            return
        except PermissionError:
            if os.name != "nt" or attempt == attempts - 1:
                raise
            time.sleep(delay)


def _stream_frames(argv: list[str], shape: tuple[int, int, int], timeout: float) -> Iterator[np.ndarray]:
    """Yield writable uint8 frames of ``shape`` from ffmpeg's rawvideo stdout."""
    size = shape[0] * shape[1] * shape[2]
    with _Child(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, timeout=timeout) as child:
        while True:
            frame = np.empty(shape, np.uint8)
            got = _read_exact(child.proc.stdout, memoryview(frame).cast("B"))
            if not got:
                break
            if got != size:
                child.finish()
                raise ForgeAVError(f"truncated frame from ffmpeg: {got} of {size} bytes")
            yield frame
        child.finish()


def _read_exact(stream, view: memoryview) -> int:
    filled = 0
    while filled < len(view):
        count = stream.readinto(view[filled:])
        if not count:
            break
        filled += count
    return filled


def _failure(argv: Sequence[str], code: int, output: str) -> str:
    tail = output.strip()[-4000:].encode("ascii", "backslashreplace").decode("ascii")
    return f"{Path(argv[0]).stem} exited with status {code}: {tail or 'no error output'}"


def _tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise ForgeAVError(f"{name} not found on PATH; install ffmpeg 5.1 or newer (it ships {name})")
    return path


def _ffprobe_json(args: Sequence[str]) -> dict:
    text = run([_tool("ffprobe"), "-v", "error", "-of", "json", *args])
    try:
        return json.loads(text or "{}")
    except json.JSONDecodeError as exc:
        raise ForgeAVError(f"ffprobe returned invalid JSON: {exc}") from exc


def ffmpeg_info() -> dict:
    """Check FFmpeg/FFprobe and verify RGBA decoding and stream inspection."""
    return copy.deepcopy(_probe_capabilities(shutil.which("ffmpeg"), shutil.which("ffprobe")))


@functools.lru_cache(maxsize=4)
def _probe_capabilities(ffmpeg: str | None, ffprobe: str | None) -> dict:
    info = {"ffmpeg": ffmpeg, "ffprobe": ffprobe, "version": None,
            "functional": {"rgba_decode": False, "stream_probe": False}, "errors": {}}
    for name, binary in (("ffmpeg", ffmpeg), ("ffprobe", ffprobe)):
        if not binary:
            info["errors"][name] = name + " not found on PATH"
    if not ffmpeg and not ffprobe:
        return info
    if ffmpeg:
        try:
            banner = run([ffmpeg, "-hide_banner", "-version"], timeout=30).split()
            info["version"] = banner[2] if banner[:2] == ["ffmpeg", "version"] and len(banner) > 2 else None
        except ForgeAVError as exc:
            info["errors"]["version"] = str(exc)
    with tempfile.TemporaryDirectory(prefix="forge-av-probe-") as tmp:
        frame = _probe_frame()
        source = Path(tmp) / "probe.png"
        Image.fromarray(frame).save(source)
        if ffmpeg:
            try:
                argv = [ffmpeg, *_FFMPEG_GLOBAL, "-i", str(source),
                        "-f", "rawvideo", "-pix_fmt", "rgba", "pipe:1"]
                decoded = list(_stream_frames(argv, frame.shape, 60))
                if len(decoded) != 1 or not np.array_equal(decoded[0], frame):
                    raise ForgeAVError("RGBA decode did not preserve the probe frame")
                info["functional"]["rgba_decode"] = True
            except ForgeAVError as exc:
                info["errors"]["rgba_decode"] = str(exc)
        if ffprobe:
            try:
                data = run([ffprobe, "-v", "error", "-show_streams", "-of", "json", str(source)], timeout=60)
                streams = json.loads(data).get("streams", [])
                if not any(s.get("codec_type") == "video" and s.get("width") == frame.shape[1]
                           and s.get("height") == frame.shape[0] for s in streams):
                    raise ForgeAVError("FFprobe did not identify the probe dimensions")
                info["functional"]["stream_probe"] = True
            except (ForgeAVError, ValueError, TypeError, AttributeError) as exc:
                info["errors"]["stream_probe"] = str(exc)
    return info


def _probe_frame(size: int = 32) -> np.ndarray:
    frame = np.zeros((size, size, 4), np.uint8)
    frame[:, size // 2:] = (224, 96, 32, 255)
    return frame


def probe(path) -> dict:
    """Describe the main video stream of ``path``; attached cover art is skipped.

    Keys: ``codec``; ``width``/``height`` (display size after container
    rotation, as used when decoding); ``pix_fmt`` as ffprobe
    reports it (VP9 alpha still shows yuv420p); ``fps_rational`` ("num/den" or
    None); ``nb_frames`` (container count, else demuxed packets, see
    ``nb_frames_source``); ``duration`` in seconds of the video stream (not
    the longer of video and audio); ``vp9_alpha``; ``alpha_mode`` (WebM
    AlphaMode, VP8 or VP9); ``has_alpha``; ``rotation``; ``stream_index``;
    ``audio_streams`` (count) with per-track ``audio`` details;
    ``attached_pics`` (cover-art streams); ``format``; ``path``.
    """
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)
    data = _ffprobe_json(["-show_streams", "-show_format", str(source)])
    streams = data.get("streams") or []
    video = _main_video_stream(streams, source)
    tags = {str(key).lower(): value for key, value in (video.get("tags") or {}).items()}
    codec, pix_fmt = video.get("codec_name"), video.get("pix_fmt")
    alpha_mode = str(tags.get("alpha_mode", "")).strip() == "1"
    rotation = _rotation(video, tags)
    width, height = int(video["width"]), int(video["height"])
    if rotation % 180 == 90:
        width, height = height, width
    index = int(video["index"])
    nb_frames, counted_by = _positive_int(video.get("nb_frames")), "container"
    if nb_frames is None:
        nb_frames, counted_by = _count_packets(source, index), "packets"
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    return {
        "path": str(source),
        "format": (data.get("format") or {}).get("format_name"),
        "stream_index": index,
        "codec": codec,
        "width": width,
        "height": height,
        "pix_fmt": pix_fmt,
        "fps_rational": _stream_fps(video),
        "nb_frames": nb_frames,
        "nb_frames_source": counted_by,
        "duration": _stream_duration(video, tags, data.get("format") or {}),
        "rotation": rotation,
        "vp9_alpha": codec == "vp9" and alpha_mode,
        "alpha_mode": alpha_mode,
        "has_alpha": alpha_mode or bool(pix_fmt and _ALPHA_PIX_FMT.match(pix_fmt)),
        "audio_streams": len(audio),
        "audio": [{"index": int(s["index"]), "codec": s.get("codec_name"),
                   "channels": s.get("channels"), "sample_rate": _positive_int(s.get("sample_rate")),
                   "duration": _seconds_or_none(s.get("duration"))} for s in audio],
        "attached_pics": sum(1 for s in streams if s.get("codec_type") == "video" and _is_attached_pic(s)),
    }


def _main_video_stream(streams: Sequence[Mapping], source: Path) -> Mapping:
    for stream in streams:
        if stream.get("codec_type") == "video" and not _is_attached_pic(stream):
            return stream
    raise ForgeAVError(f"no video stream in {source.name}")


def _is_attached_pic(stream: Mapping) -> bool:
    return bool((stream.get("disposition") or {}).get("attached_pic"))


def _rotation(stream: Mapping, tags: Mapping) -> int:
    for item in stream.get("side_data_list") or []:
        if "rotation" in item:
            return int(round(float(item["rotation"]))) % 360
    try:
        return int(round(float(tags.get("rotate", 0)))) % 360
    except (TypeError, ValueError):
        return 0


def _stream_fps(stream: Mapping) -> str | None:
    for key in ("avg_frame_rate", "r_frame_rate"):
        try:
            rate = Fraction(str(stream.get(key) or ""))
        except (ValueError, ZeroDivisionError):
            continue
        if rate > 0:
            return _rational(rate)
    return None


def _stream_duration(stream: Mapping, tags: Mapping, fmt: Mapping) -> float | None:
    seconds = _seconds_or_none(stream.get("duration"))
    if seconds is None and tags.get("duration"):
        seconds = _clock_seconds(str(tags["duration"]))  # Matroska per-track "HH:MM:SS.nnnnnnnnn"
    if seconds is None:
        seconds = _seconds_or_none(fmt.get("duration"))
    return seconds


def _clock_seconds(text: str) -> float | None:
    parts = text.strip().split(":")
    try:
        values = [float(part) for part in parts]
    except ValueError:
        return None
    if len(values) != 3 or not all(math.isfinite(v) for v in values):
        return None
    return values[0] * 3600 + values[1] * 60 + values[2]


def _count_packets(source: Path, index: int) -> int:
    data = _ffprobe_json(["-select_streams", str(index), "-count_packets",
                          "-show_entries", "stream=nb_read_packets", str(source)])
    streams = data.get("streams") or [{}]
    return _positive_int(streams[0].get("nb_read_packets")) or 0


def extract_frames(path, out_dir, *, fps=0, start=0, duration=None, alpha="auto",
                   timeout: float = DEFAULT_TIMEOUT) -> list[Path]:
    """Decode the main video stream to ``out_dir/frame_000000.png`` and onwards.

    Files are numbered by 0-based frame index (six digits). ``fps=0`` keeps
    every source frame with its own timing (passthrough); ``fps>0`` resamples
    to that constant rate (number or "num/den"). ``start``/``duration`` keep
    the frames whose timestamps fall in [start, start + duration) seconds
    (accurate seek). ``alpha``: ``auto`` keeps the source alpha when there is
    one (WebM alpha via libvpx), ``on`` requires it, ``off`` drops it. Frames
    are RGBA PNGs when alpha is kept, else RGB. ``out_dir`` may exist but must
    hold no ``frame_*.png``; on failure the frames written so far are removed.
    """
    source = Path(path)
    info = probe(source)
    decoder, keep_alpha = _alpha_plan(info, alpha)
    rate = _fraction(fps, "fps", allow_zero=True)
    trim = _trim_args(start, duration)
    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    if any(target.glob("frame_*.png")):
        raise FileExistsError(f"{target} already holds frame_*.png files; extract into a fresh directory")
    timing = ["-vf", f"fps={_rational(rate)}"] if rate else ["-fps_mode", "passthrough"]
    pattern = str(target).replace("%", "%%") + os.sep + "frame_%06d.png"  # image2 expands '%'
    argv = [_tool("ffmpeg"), *_FFMPEG_GLOBAL, *decoder, *trim, "-i", str(source),
            "-map", f"0:{info['stream_index']}", "-an", "-sn", "-dn", *timing,
            "-pix_fmt", "rgba" if keep_alpha else "rgb24", "-start_number", "0", pattern]
    try:
        run(argv, timeout=timeout)
        frames = sorted(target.glob("frame_*.png"), key=_natural_key)
        if not frames:
            raise ForgeAVError(f"no frames decoded from {source.name}; check start/duration")
    except BaseException:
        for leftover in target.glob("frame_*.png"):
            _unlink_settled(leftover)
        raise
    return frames


def iter_rgba(path, *, size=None, alpha="auto", start=0, duration=None,
              timeout: float = DEFAULT_TIMEOUT) -> Iterator[np.ndarray]:
    """Stream the main video stream as writable (H, W, 4) uint8 RGBA arrays.

    One frame is in memory at a time, so long clips can be verified without a
    pixel budget. ``size=(w, h)`` resizes inside
    ffmpeg (premultiplied when alpha is kept). Pixels are returned exactly as
    decoded: colour under alpha 0 is not zeroed. Leaving the loop early kills
    ffmpeg.
    """
    source = Path(path)
    info = probe(source)
    decoder, keep_alpha = _alpha_plan(info, alpha)
    width, height = (info["width"], info["height"]) if size is None else _size(size)
    filters = []
    if (width, height) != (info["width"], info["height"]):
        filters.append(premultiplied_scale_filter(width, height) if keep_alpha
                       else f"scale={width}:{height}:flags=lanczos")
    if not keep_alpha:
        filters.append("format=rgb24")  # discard any source alpha: the output is opaque
    argv = [_tool("ffmpeg"), *_FFMPEG_GLOBAL, *decoder, *_trim_args(start, duration), "-i", str(source),
            "-map", f"0:{info['stream_index']}", "-an", "-sn", "-dn",
            *(["-vf", ",".join(filters)] if filters else []), "-fps_mode", "passthrough",
            "-f", "rawvideo", "-pix_fmt", "rgba", "pipe:1"]
    return _stream_frames(argv, (height, width, 4), timeout)


def _alpha_plan(info: Mapping, alpha: str) -> tuple[list[str], bool]:
    """Return (decoder arguments, keep alpha) for an ``alpha`` mode."""
    if alpha not in ALPHA_MODES:
        raise ValueError(f"alpha must be one of: {', '.join(ALPHA_MODES)}")
    if alpha == "on" and not info["has_alpha"]:
        raise ValueError(f"{Path(info['path']).name} has no alpha channel "
                         f"({info['codec']}, {info['pix_fmt']}); alpha='on' needs a transparent source")
    if alpha == "off" or not info["has_alpha"]:
        return [], False
    decoder = _ALPHA_DECODERS.get(info["codec"]) if info["alpha_mode"] else None
    return (["-c:v", decoder] if decoder else []), True


def _trim_args(start, duration) -> list[str]:
    """Input-side -ss/-t: decode-accurate and selecting frames timed in [start, start + duration)."""
    begin = _seconds(start, "start", allow_zero=True)
    args = ["-ss", repr(begin)] if begin else []
    if duration is not None:
        args += ["-t", repr(_seconds(duration, "duration", allow_zero=False))]
    return args


def premultiplied_scale_filter(w: int, h: int) -> str:
    """ffmpeg filter chain that resizes straight RGBA without dark halos.

    Colour is premultiplied by alpha in 16-bit planar RGB, resized with
    lanczos, unpremultiplied and returned as straight 8-bit ``rgba``. A plain
    ``scale`` filters colour and alpha independently, so the zeroed colour of
    transparent pixels bleeds into soft edges (a red-255 disk measures about
    120 at its edge instead of 255).
    """
    width, height = _size((w, h))
    return (f"format=gbrap16le,premultiply=inplace=1:planes=7,scale={width}:{height}:flags=lanczos,"
            "unpremultiply=inplace=1:planes=7,format=rgba")


def _fraction(value, name: str, *, allow_zero: bool = False) -> Fraction:
    """Parse a positive rate given as int, float, Fraction or 'num/den' text."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Fraction, np.integer)):
        raise TypeError(f"{name} must be a number or a 'num/den' string")
    if isinstance(value, np.integer):
        value = int(value)
    try:
        rate = Fraction(str(value).strip()) if isinstance(value, (str, float)) else Fraction(value)
    except (ValueError, ZeroDivisionError):
        raise ValueError(f"{name} must be a rational like 24 or '30000/1001', got {value!r}") from None
    if rate < 0 or (rate == 0 and not allow_zero):
        raise ValueError(f"{name} must be positive, got {value!r}")
    return rate


def _rational(rate: Fraction) -> str:
    return f"{rate.numerator}/{rate.denominator}"


def _size(size) -> tuple[int, int]:
    values = tuple(size)
    if len(values) != 2 or any(isinstance(v, bool) or not isinstance(v, (int, np.integer)) or v < 1
                               for v in values):
        raise ValueError(f"size must be (width, height) in positive whole pixels, got {size!r}")
    return int(values[0]), int(values[1])


def _positive(value, name: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{name} must be positive and finite")
    return number


def _seconds(value, name: str, *, allow_zero: bool) -> float:
    number = float(value)
    if not math.isfinite(number) or number < 0 or (number == 0 and not allow_zero):
        raise ValueError(f"{name} must be {'nonnegative' if allow_zero else 'positive'} and finite seconds")
    return number


def _seconds_or_none(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _positive_int(value) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _natural_key(path: Path) -> list:
    return [int(part) if i % 2 else part for i, part in enumerate(re.split(r"(\d+)", path.name))]
