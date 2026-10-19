"""Local ComfyUI image-to-video bridge. Configuration is explicit; no model is assumed."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import time
from urllib import parse, request
from urllib.error import HTTPError
import uuid
from frame_rules import from_config as source_frame_count


class ComfyError(Exception):
    pass


def find_config():
    """Explicit environment, installed manifest, then a repository-local configuration."""
    explicit = os.environ.get("COMFYUI_FORGE_CONFIG")
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if not path.is_file():
            raise ComfyError(f"COMFYUI_FORGE_CONFIG does not exist: {path}")
        return path
    manifest = Path(__file__).resolve().parents[2] / ".comfyui-sprite-forge.install.json"
    if manifest.is_file():
        data = json.loads(manifest.read_text(encoding="utf-8-sig"))
        if data.get("comfyuiConfig"):
            path = Path(data["comfyuiConfig"])
            if path.is_file():
                return path.resolve()
            raise ComfyError(f"Installed config was moved or removed: {path}; reinstall with --config")
    local = Path(__file__).resolve().parents[3] / "local-comfyui" / "config.local.json"
    if local.is_file():
        return local.resolve()
    raise ComfyError("No local workflow configured. Create local-comfyui/config.local.json and reinstall with --config PATH; see INSTALL.md")


def load_config():
    config_path = find_config()
    config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    base = parse.urlsplit(config.get("url", "http://127.0.0.1:8188"))
    if base.scheme != "http" or base.hostname not in ("127.0.0.1", "localhost", "::1") or base.query or base.fragment or base.username:
        raise ComfyError("ComfyUI URL must be a local HTTP address without credentials")
    config["url"] = base.geturl().rstrip("/")
    config["workflow"] = str((config_path.parent / config["workflow"]).resolve())
    return config


def load_graph(config):
    graph = json.loads(Path(config["workflow"]).read_text(encoding="utf-8-sig"))
    if not isinstance(graph, dict) or "nodes" in graph or not graph or any(
        not isinstance(node, dict) or "class_type" not in node or not isinstance(node.get("inputs"), dict)
        for node in graph.values()
    ):
        raise ComfyError("workflow must be Export (API) format")
    required = ("image", "prompt", "width", "height", "length")
    for key in (*required, *(key for key in ("last_image", "fps") if key in config["bindings"])):
        node, field = config["bindings"][key]
        if node not in graph or field not in graph[node]["inputs"]:
            raise ComfyError(f"invalid binding: {key}")
    if config["output_node"] not in graph:
        raise ComfyError("output_node is missing from workflow")
    if "last_image" in config["bindings"]:
        node, field = config["last_frame_input"]
        if node not in graph or field not in graph[node]["inputs"]:
            raise ComfyError("invalid last_frame_input binding")
    return graph


def prepare(config, graph, *, prompt, first, last, width, height, duration):
    graph = copy.deepcopy(graph)
    fps = float(config["fps"])
    try:
        frames = source_frame_count(config, duration)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ComfyError(str(exc)) from exc
    values = dict(image=first, prompt=prompt, width=width, height=height, length=frames)
    for key, value in values.items():
        node, field = config["bindings"][key]
        graph[node]["inputs"][field] = value
    if "last_image" in config["bindings"]:
        node, field = config["bindings"]["last_image"]
        if last:
            graph[node]["inputs"][field] = last
        else:
            consumer, socket = config["last_frame_input"]
            graph[consumer]["inputs"].pop(socket, None)
    elif last:
        raise ComfyError("workflow does not bind a last frame")
    if "fps" in config["bindings"]:
        node, field = config["bindings"]["fps"]
        graph[node]["inputs"][field] = fps
    # Submit only ancestors of the selected output: disconnected UI helper nodes are not executable.
    needed = set()

    def visit(node_id):
        if node_id in needed:
            return
        needed.add(node_id)
        for value in graph[node_id]["inputs"].values():
            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str) and value[0] in graph:
                visit(value[0])

    visit(config["output_node"])
    return {node: graph[node] for node in graph if node in needed}, frames / fps


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ComfyError("HTTP redirects are disabled; only the configured local ComfyUI endpoint is allowed")


class Client:
    def __init__(self, url, timeout=30):
        self.url, self.timeout = url, timeout
        self.opener = request.build_opener(request.ProxyHandler({}), NoRedirect())

    def call(self, method, path, body=None, content_type="application/json", raw=False):
        req = request.Request(self.url + path, data=body, method=method)
        if body is not None:
            req.add_header("Content-Type", content_type)
        with self.opener.open(req, timeout=self.timeout) as response:
            data = response.read()
        return data if raw else json.loads(data)

    def upload(self, path):
        path = Path(path)
        boundary = "forge" + uuid.uuid4().hex
        name = "forge-" + uuid.uuid4().hex + path.suffix.lower()
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="{name}"\r\n'
                'Content-Type: application/octet-stream\r\n\r\n').encode() + path.read_bytes()
        body += f"\r\n--{boundary}--\r\n".encode()
        result = self.call("POST", "/upload/image", body, f"multipart/form-data; boundary={boundary}")
        return "/".join(part for part in (result.get("subfolder", ""), result["name"]) if part)


def save_job(folder, job):
    temp = folder / "job.json.tmp"
    temp.write_text(json.dumps(job, indent=2), encoding="utf-8")
    temp.replace(folder / "job.json")


def wait_result(config, client, folder, job, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        history = client.call("GET", "/history/" + parse.quote(job["prompt_id"], safe=""))
        result = history.get(job["prompt_id"])
        if not result:
            time.sleep(config.get("poll_interval", 1))
            continue
        status = result.get("status", {})
        if status.get("status_str") == "error":
            job["status"] = "failed"
            job["errors"] = status.get("messages", [])
            save_job(folder, job)
            raise ComfyError("ComfyUI execution failed; see job.json")
        output = result.get("outputs", {}).get(config["output_node"], {})
        files = [item for key in ("gifs", "videos", "images") for item in output.get(key, [])
                 if str(item.get("filename", "")).lower().endswith(".mp4")]
        if not status.get("completed"):
            time.sleep(config.get("poll_interval", 1))
            continue
        if not files:
            job["status"] = "failed"
            save_job(folder, job)
            raise ComfyError("selected output node returned no MP4")
        item = files[0]
        query = parse.urlencode({key: item.get(key, "output" if key == "type" else "")
                                 for key in ("filename", "subfolder", "type")})
        data = client.call("GET", "/view?" + query, raw=True)
        if len(data) < 12 or data[4:8] != b"ftyp":
            raise ComfyError("download is not an MP4 container")
        target = folder / "generated.mp4"
        temporary = folder / "generated.mp4.part"
        temporary.write_bytes(data)
        temporary.replace(target)
        job.update(status="done", artifact=str(target.resolve()), sha256=hashlib.sha256(data).hexdigest())
        save_job(folder, job)
        return {"artifact": job["artifact"], "sha256": job["sha256"], "job": str((folder / "job.json").resolve()),
                "estimateUsd": 0.0, "notes": ["Local GPU generation; electricity cost is not estimated."]}
    raise ComfyError("ComfyUI is still pending; resume this output folder, do not submit again")


def execute(args, client=None):
    from PIL import Image

    config = load_config()
    graph = load_graph(config)
    with Image.open(args.reference) as image:
        width, height = image.size
    if width % 32 or height % 32:
        raise ComfyError("reference width and height must both be multiples of 32; prepare a compatible canvas without stretching")
    if not math.isfinite(args.duration) or args.duration <= 0:
        raise ComfyError("duration must be finite and positive")
    # Preserve the prepared registration canvas and its aspect ratio exactly.
    graph, duration = prepare(config, graph, prompt=Path(args.prompt_file).read_text(encoding="utf-8-sig"),
                              first="pending-upload", last="pending-last" if args.last_frame else None,
                              width=width, height=height, duration=args.duration)
    if args.dry_run:
        return {"estimateUsd": 0.0, "estimate": "local GPU; electricity excluded", "warnings": [],
                "notes": [f"Workflow canvas: {width}x{height}; actual duration: {duration:g}s"],
                "command": ["ComfyUI", config["url"], config["workflow"]]}
    folder = Path(args.out_dir)
    folder.mkdir(parents=True, exist_ok=False)
    client = client or Client(config["url"])
    job = {"provider": "comfyui", "status": "preparing", "output_node": config["output_node"],
           "durationUsed": duration, "lastFrameUsed": bool(args.last_frame), "url": config["url"]}
    save_job(folder, job)
    first = client.upload(args.reference)
    last = client.upload(args.last_frame) if args.last_frame else None
    image_node, image_field = config["bindings"]["image"]
    graph[image_node]["inputs"][image_field] = first
    if last:
        node, field = config["bindings"]["last_image"]
        graph[node]["inputs"][field] = last
    (folder / "submitted-workflow.json").write_text(json.dumps(graph, indent=2), encoding="utf-8")
    # Persist ambiguity before POST. A transport failure may occur after the server accepts the job.
    job["status"] = "unknown"
    save_job(folder, job)
    try:
        reply = client.call("POST", "/prompt", json.dumps({"prompt": graph, "client_id": uuid.uuid4().hex}).encode())
    except HTTPError as exc:
        # A validation rejection is definitive. Other HTTP failures may leave a running task.
        if exc.code == 400:
            job.update(status="failed", errors=exc.read().decode("utf-8", "replace"))
            save_job(folder, job)
            raise ComfyError("ComfyUI rejected workflow; see job.json") from None
        raise
    if reply.get("error") or reply.get("node_errors") or not reply.get("prompt_id"):
        job.update(status="failed", errors=reply)
        save_job(folder, job)
        raise ComfyError("ComfyUI rejected workflow; see job.json")
    job.update(status="pending", prompt_id=reply["prompt_id"])
    save_job(folder, job)
    return wait_result(config, client, folder, job, args.timeout or 1800)


def resume(folder, timeout=1800, client=None):
    folder = Path(folder)
    job = json.loads((folder / "job.json").read_text(encoding="utf-8"))
    if job["status"] == "done":
        data = Path(job["artifact"]).read_bytes()
        if hashlib.sha256(data).hexdigest() != job["sha256"]:
            raise ComfyError("completed artifact checksum changed")
        return job
    if job["status"] != "pending" or not job.get("prompt_id"):
        raise ComfyError("job cannot be resumed automatically; inspect the ComfyUI queue and job.json")
    config = load_config()
    if config["url"] != job["url"] or config["output_node"] != job["output_node"]:
        raise ComfyError("resume configuration differs from submitted job")
    return wait_result(config, client or Client(config["url"]), folder, job, timeout)


def check(client=None):
    """Read-only server/node/model discovery; never enqueue generation."""
    config = load_config()
    graph, _ = prepare(config, load_graph(config), prompt="", first="input.png",
                       last="last.png" if "last_image" in config["bindings"] else None,
                       width=1280, height=736, duration=3)
    client = client or Client(config["url"])
    info = client.call("GET", "/object_info")
    missing = sorted({node["class_type"] for node in graph.values()} - set(info))
    unavailable = []
    for node in graph.values():
        schema = info.get(node["class_type"], {}).get("input", {})
        fields = {**schema.get("required", {}), **schema.get("optional", {})}
        for name in ("unet_name", "clip_name", "vae_name", "upscaler_model"):
            value, choices = node["inputs"].get(name), fields.get(name)
            if isinstance(value, str) and choices and isinstance(choices[0], list) and value not in choices[0]:
                unavailable.append(value)
    return {"status": "ok" if not missing and not unavailable else "incompatible", "url": config["url"],
            "missingNodes": missing, "unavailableModels": unavailable}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Resume an existing ComfyUI job without resubmitting")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--resume", metavar="OUT_DIR")
    mode.add_argument("--check", action="store_true", help="read server node and model availability, without generation")
    parser.add_argument("--timeout", type=float, default=1800)
    args = parser.parse_args()
    try:
        result = check() if args.check else resume(args.resume, args.timeout)
        print(json.dumps(result))
        if result.get("status") == "incompatible":
            raise SystemExit(1)
    except (ComfyError, OSError, ValueError, KeyError) as exc:
        parser.exit(1, f"error: {exc}\n")
