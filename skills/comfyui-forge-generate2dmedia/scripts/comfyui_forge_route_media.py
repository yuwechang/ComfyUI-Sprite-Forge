#!/usr/bin/env python3
"""ComfyUI-only generation router. No credentials, cloud providers, CLI delegation or fallback."""
from __future__ import annotations
import argparse
from dataclasses import dataclass, field
import json
import math
from pathlib import Path
import sys
import comfyui_forge_media

NO_ROUTE_EXIT = 3

class RouteError(Exception):
    pass

@dataclass
class Wanted:
    last_frame: object = None
    duration: float = 3

@dataclass
class Candidate:
    route: str = "local:comfyui"
    pin: bool = False
    duration: float = 3

@dataclass
class Resolution:
    candidates: list = field(default_factory=list)

def requested_routes(kind, route="auto", **kwargs):
    if route not in ("auto", "comfyui", "local:comfyui"):
        raise RouteError("Only local ComfyUI is available; other routes were removed")
    return ["local:comfyui"] if kind == "video" else []

def resolve(kind, route="auto", wanted=None):
    if not requested_routes(kind, route):
        return Resolution()
    wanted = wanted or Wanted()
    cfg = comfyui_forge_media.load_config()
    width,height=comfyui_forge_media.diagnostic_canvas(cfg)
    _, duration = comfyui_forge_media.prepare(cfg, comfyui_forge_media.load_graph(cfg), prompt="", first="input.png",
        last="last.png" if wanted.last_frame else None, width=width, height=height, duration=wanted.duration)
    return Resolution([Candidate(pin=bool(wanted.last_frame), duration=duration)])

def build_parser():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("image", "video", "resolve"):
        s = sub.add_parser(name)
        s.add_argument("--route", choices=("auto", "comfyui", "local:comfyui"), default="comfyui")
        s.add_argument("--duration", type=float, default=3)
        if name == "resolve":
            s.add_argument("--kind", choices=("image", "video"), required=True)
        else:
            s.add_argument("--preparation", help="registration_job.json binding the prepared input and final prompt")
            s.add_argument("--reference", required=name == "video")
            s.add_argument("--last-frame")
            s.add_argument("--prompt-file", required=True)
            s.add_argument("--out-dir", required=True)
            s.add_argument("--timeout", type=float, default=1800)
            s.add_argument("--dry-run", action="store_true")
    return p

def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        kind = args.kind if args.command == "resolve" else args.command
        if not math.isfinite(args.duration) or args.duration <= 0:
            raise RouteError("duration must be finite and positive")
        if kind != "video":
            print(json.dumps({"status":"unsupported", "route":None,
                "reason":"This installation has only a local ComfyUI image-to-video workflow. Supply an existing image. No fallback is available."}))
            return NO_ROUTE_EXIT
        if args.command == "resolve":
            result = resolve(kind, args.route, wanted=Wanted(duration=args.duration))
            print(json.dumps({"status":"ok","route":"local:comfyui","available":["local:comfyui"],
                "durationUsed":result.candidates[0].duration}))
            return 0
        for file in (args.reference, args.prompt_file, args.last_frame):
            if file and not Path(file).is_file():
                raise RouteError(f"Input file does not exist: {file}")
        result = comfyui_forge_media.execute(args)
        print(json.dumps({"status":"dry-run" if args.dry_run else "ok", "kind":"video",
            "route":"local:comfyui", "durationRequested":args.duration,"durationUsed":result["durationUsed"],
            "lastFrameUsed":bool(args.last_frame), **result}))
        return 0
    except (RouteError, comfyui_forge_media.ComfyError, OSError, ValueError, KeyError, TypeError) as exc:
        print(f"error: ComfyUI: {exc}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
