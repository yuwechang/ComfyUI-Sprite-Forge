"""Local ComfyUI image-to-video bridge. Configuration is explicit; no model is assumed."""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
import secrets
from pathlib import Path
import time
import tempfile
from urllib import parse, request
from urllib.error import HTTPError
import uuid
from comfyui_forge_frame_rules import from_config as source_frame_count, validate_config, validate_canvas, diagnostic_canvas


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
    validate_config(config)
    config["fps"] = 24
    for key, default in (("poll_interval", 1), ("request_timeout", 30)):
        value = config.get(key, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 or (key == "request_timeout" and value == 0):
            raise ComfyError(f"invalid {key}")
    base = parse.urlsplit(config.get("url", "http://127.0.0.1:8188"))
    if base.scheme != "http" or base.hostname not in ("127.0.0.1", "localhost", "::1") or base.query or base.fragment or base.username is not None or base.password is not None or base.path not in ("", "/"):
        raise ComfyError("ComfyUI URL must be a local HTTP address without credentials")
    if base.port is not None and base.port < 1:
        raise ComfyError("invalid ComfyUI port")
    config["url"] = base.geturl().rstrip("/")
    config["workflow"] = str((config_path.parent / config["workflow"]).resolve())
    return config


def load_graph(config):
    if not isinstance(config.get('bindings'),dict):raise ComfyError('config bindings must be an object')
    if not isinstance(config.get('workflow'),str) or not isinstance(config.get('output_node'),str):raise ComfyError('workflow and output_node must be strings')
    for key in ('image','prompt','width','height','length',*(key for key in ('fps','last_image','seed') if key in config['bindings'])):
        bound=config['bindings'].get(key)
        if not isinstance(bound,(list,tuple)) or len(bound)!=2 or any(not isinstance(v,str) or not v for v in bound):raise ComfyError('binding '+key+' must be [node_id, input_name]')
    if 'last_image' in config['bindings']:
        bound=config.get('last_frame_input')
        if not isinstance(bound,(list,tuple)) or len(bound)!=2 or any(not isinstance(v,str) or not v for v in bound):raise ComfyError('last_frame_input must identify its consumer socket')
    graph = json.loads(Path(config["workflow"]).read_text(encoding="utf-8-sig"))
    if not isinstance(graph, dict) or "nodes" in graph or not graph or any(
        not isinstance(node, dict) or "class_type" not in node or not isinstance(node.get("inputs"), dict)
        for node in graph.values()
    ):
        raise ComfyError("workflow must be Export (API) format")
    required = ("image", "prompt", "width", "height", "length")
    for key in (*required, *(key for key in ("last_image", "fps", "seed") if key in config["bindings"])):
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
    validate_canvas(config,width,height)
    graph = copy.deepcopy(graph)
    fps = 24
    try:
        frames = source_frame_count(config, duration)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ComfyError(str(exc)) from exc
    values = dict(image=first, prompt=prompt, width=width, height=height, length=frames)
    if 'fps' in config['bindings']:values['fps']=fps
    if last and 'last_image' in config['bindings']:values['last_image']=last
    assignments={}
    for key,value in values.items():
        bound=tuple(config['bindings'][key])
        if bound in assignments and assignments[bound]!=value:raise ComfyError('conflicting values are bound to the same workflow socket')
        assignments[bound]=value
    for key, value in values.items():
        node, field = config["bindings"][key]
        graph[node]["inputs"][field] = value
    if 'last_image' in config['bindings'] and not last:
        consumer,socket=config['last_frame_input']
        if (consumer,socket) in assignments:raise ComfyError('optional tail socket conflicts with an active binding')
        graph[consumer]['inputs'].pop(socket,None)
    elif last and 'last_image' not in config['bindings']:
        raise ComfyError('workflow does not bind a last frame')
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
    for key in (*values,):
        if config['bindings'][key][0] not in needed:raise ComfyError('binding '+key+' does not reach the selected output')
    return {node: graph[node] for node in graph if node in needed}, frames / fps


def seed_targets(config, graph):
    """Bind explicitly, or locate standard seed sockets on executable nodes.

    Assigning the sampler socket also supports a seed fed by a primitive or helper
    node. Original workflow files remain untouched.
    """
    bound=config.get('bindings',{}).get('seed')
    if bound is not None:
        if not isinstance(bound,(list,tuple)) or len(bound)!=2 or any(not isinstance(v,str) for v in bound):
            raise ComfyError('bindings.seed must be [node_id, input_name]')
        if any(list(bound)==list(value) for key,value in config['bindings'].items() if key!='seed'):
            raise ComfyError('seed binding overlaps another workflow binding')
        targets=[tuple(bound)]
    else:
        targets=[(node,field) for node,data in graph.items() for field in data['inputs'] if field in ('seed','noise_seed')]
    occupied={tuple(value) for key,value in config.get('bindings',{}).items() if key!='seed'}
    if any(target in occupied for target in targets):raise ComfyError('seed target overlaps another workflow binding')
    for node,field in targets:
        if node not in graph or field not in graph[node]['inputs']:
            raise ComfyError('seed binding is missing from the executable output graph')
        value=graph[node]['inputs'][field]
        linked=isinstance(value,list) and len(value)==2 and isinstance(value[0],str) and value[0] in graph and type(value[1]) is int
        if type(value) is not int and not linked:
            raise ComfyError('seed target must be an integer socket or an upstream node connection')
    return targets


def seed_bounds(graph,targets,info):
    if not isinstance(info,dict):raise ComfyError('ComfyUI object_info must be a JSON object')
    lower,upper=0,2**53-1
    for node,field in targets:
        schema=info.get(graph[node]['class_type'],{}).get('input',{})
        definition={**schema.get('required',{}),**schema.get('optional',{})}.get(field)
        if definition is None:continue
        if not isinstance(definition,(list,tuple)) or not definition or definition[0]!='INT':raise ComfyError('seed socket must be an integer in the server schema')
        options=definition[1] if len(definition)>1 and isinstance(definition[1],dict) else {}
        lo,hi=options.get('min',0),options.get('max',2**53-1)
        if type(lo) is not int or type(hi) is not int:raise ComfyError('seed limits must be integers')
        lower,upper=max(lower,lo),min(upper,hi)
    if lower>upper:raise ComfyError('seed sockets have no compatible nonnegative integer range')
    return lower,upper


def randomize_seed(config,graph,bounds=(0,2**53-1)):
    """One new nonnegative, JSON-exact integer per newly created submission."""
    targets=seed_targets(config,graph)
    if not targets:return copy.deepcopy(graph),None,[]
    previous={graph[node]['inputs'][field] for node,field in targets if type(graph[node]['inputs'][field]) is int}
    lower,upper=bounds;span=upper-lower+1
    seed=lower+secrets.randbelow(span)
    excluded={value for value in previous if lower<=value<=upper}
    if len(excluded)<span:
        while seed in excluded:seed=lower+secrets.randbelow(span)
    graph=copy.deepcopy(graph)
    for node,field in targets:graph[node]['inputs'][field]=seed
    # Overriding an upstream seed link can disconnect helpers; retain only ancestors.
    needed=set()
    def visit(node):
        if node in needed:return
        needed.add(node)
        for value in graph[node]['inputs'].values():
            if isinstance(value,list) and len(value)==2 and isinstance(value[0],str) and value[0] in graph:visit(value[0])
    visit(config['output_node'])
    return {node:data for node,data in graph.items() if node in needed},seed,[list(t) for t in targets]


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
        attempts = 3 if method == "GET" else 1
        for attempt in range(attempts):
            try:
                with self.opener.open(req, timeout=self.timeout) as response:
                    data = response.read()
                return data if raw else json.loads(data)
            except OSError as exc:
                retryable = not isinstance(exc, HTTPError) or exc.code in (408, 429, 500, 502, 503, 504)
                if attempt + 1 == attempts or not retryable:
                    raise
                time.sleep(0.25 * 2 ** attempt)

    def upload(self, path):
        path = Path(path)
        boundary = "forge" + uuid.uuid4().hex
        name = "forge-" + uuid.uuid4().hex + path.suffix.lower()
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="{name}"\r\n'
                'Content-Type: application/octet-stream\r\n\r\n').encode() + path.read_bytes()
        body += f"\r\n--{boundary}--\r\n".encode()
        result = self.call("POST", "/upload/image", body, f"multipart/form-data; boundary={boundary}")
        return "/".join(part for part in (result.get("subfolder", ""), result["name"]) if part)


def validate_mp4(data):
    from comfyui_forge_media_mp4 import scan, Mp4Error
    if len(data) < 12 or data[4:8] != b"ftyp":
        raise ComfyError("download is not an MP4 container")
    try:
        if "vide" not in scan(data)["tracks"]:
            raise ComfyError("download contains no MP4 video track")
    except Mp4Error as exc:
        raise ComfyError("invalid MP4 container: " + str(exc)) from exc


def digest(data):
    return hashlib.sha256(data).hexdigest()


def graph_digest(graph):
    return digest(json.dumps(graph, sort_keys=True, separators=(",", ":")).encode())


def result_summary(folder, job):
    return {"artifact": job["artifact"], "sha256": job["sha256"],
            "job": str((folder / "job.json").resolve()), "durationUsed": job.get("durationUsed"),
            "durationRequested": job.get("durationRequested"), "frameCount": job.get("frameCount"),
            "lastFrameUsed": job.get("lastFrameUsed", False), "fps": 24, "seed":job.get("seed")}


def validate_timeout(timeout):
    if isinstance(timeout, bool) or not math.isfinite(timeout) or timeout <= 0:
        raise ComfyError("timeout must be finite and positive")


def save_job(folder, job):
    job["updatedAt"] = datetime.now(timezone.utc).isoformat()
    fd,name=tempfile.mkstemp(prefix='.job-',suffix='.tmp',dir=folder)
    temp=Path(name)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as stream:json.dump(job,stream,indent=2)
        temp.replace(folder/'job.json')
    finally:temp.unlink(missing_ok=True)


def wait_result(config, client, folder, job, timeout):
    validate_timeout(timeout)
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
        validate_mp4(data)
        target = folder / "generated.mp4"
        temporary = folder / "generated.mp4.part"
        temporary.write_bytes(data)
        temporary.replace(target)
        job.update(status="done", artifact=str(target.resolve()), sha256=hashlib.sha256(data).hexdigest())
        save_job(folder, job)
        return result_summary(folder, job)
    raise ComfyError("ComfyUI is still pending; resume this output folder, do not submit again")


def execute(args, client=None):
    from PIL import Image

    config = load_config()
    graph = load_graph(config)
    validate_timeout(args.timeout)
    preparation = getattr(args, "preparation", None)
    if preparation:
        preparation = Path(preparation)
        receipt = json.loads(preparation.read_text(encoding="utf-8"))
        for role, path in (("input", args.reference), ("prompt", args.prompt_file)):
            expected = receipt[role]
            bound = (preparation.parent / expected["path"]).resolve()
            if bound != Path(path).resolve() or digest(Path(path).read_bytes()) != expected["sha256"]:
                raise ComfyError(f"prepared {role} differs from submission; prepare the final prompt/input together")
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
    targets=seed_targets(config,graph)
    if args.dry_run:
        return {"seedPolicy":"random-per-new-job" if targets else "workflow-default", "seedTargets":[list(t) for t in targets], "durationRequested": args.duration, "durationUsed": duration,
                "frameCount": source_frame_count(config, args.duration), "fps": 24,
                "canvas": [width, height], "url": config["url"], "workflow": config["workflow"]}
    folder=Path(args.out_dir)
    if folder.exists():raise ComfyError('output folder already exists; inspect or resume this job rather than resubmitting')
    client=client or Client(config['url'],config.get('request_timeout',30))
    bounds=seed_bounds(graph,targets,client.call('GET','/object_info')) if targets else None
    graph,seed,targets=randomize_seed(config,graph,bounds or (0,2**53-1))
    folder.mkdir(parents=True,exist_ok=False)
    job = {"schemaVersion": 1, "provider": "comfyui", "client_id": uuid.uuid4().hex,
           "createdAt": datetime.now(timezone.utc).isoformat(), "fps": 24, "seed":seed, "seedBounds":list(bounds) if bounds else None, "seedTargets":targets, "seedPolicy":"random-per-new-job" if targets else "workflow-default",
           "durationRequested": args.duration, "frameCount": source_frame_count(config, args.duration),
           "fingerprints": {"reference": digest(Path(args.reference).read_bytes()),
                            "prompt": digest(Path(args.prompt_file).read_bytes()),
                            "config": graph_digest(config),
                            "workflow": digest(Path(config["workflow"]).read_bytes())}, "status": "preparing", "output_node": config["output_node"],
           "durationUsed": duration, "lastFrameUsed": bool(args.last_frame), "url": config["url"]}
    if preparation:
        job["fingerprints"]["preparation"] = digest(preparation.read_bytes())
    save_job(folder, job)
    try:
        first = client.upload(args.reference)
        last = client.upload(args.last_frame) if args.last_frame else None
    except (OSError, ValueError, KeyError, ComfyError) as exc:
        job.update(status="failed", errors=str(exc), submission="not_sent")
        save_job(folder, job)
        raise
    if args.last_frame:
        job["fingerprints"]["last_frame"] = digest(Path(args.last_frame).read_bytes())
    image_node, image_field = config["bindings"]["image"]
    graph[image_node]["inputs"][image_field] = first
    if last:
        node, field = config["bindings"]["last_image"]
        graph[node]["inputs"][field] = last
    (folder / "submitted-workflow.json").write_text(json.dumps(graph, indent=2), encoding="utf-8")
    job["fingerprints"]["submitted_workflow"] = graph_digest(graph)
    # Persist ambiguity before POST. A transport failure may occur after the server accepts the job.
    job["status"] = "unknown"
    save_job(folder, job)
    try:
        reply = client.call("POST", "/prompt", json.dumps({"prompt": graph, "client_id": job["client_id"]}).encode())
    except HTTPError as exc:
        # A validation rejection is definitive. Other HTTP failures may leave a running task.
        if exc.code == 400:
            job.update(status="failed", errors=exc.read().decode("utf-8", "replace"))
            save_job(folder, job)
            raise ComfyError("ComfyUI rejected workflow; see job.json") from None
        raise
    if isinstance(reply, dict) and (reply.get("error") or reply.get("node_errors")):
        job.update(status="failed", errors=reply)
        save_job(folder, job)
        raise ComfyError("ComfyUI rejected workflow; see job.json")
    if not isinstance(reply, dict) or not reply.get("prompt_id"):
        raise ComfyError("submission outcome is unknown; inspect this job before resuming")
    job.update(status="pending", prompt_id=reply["prompt_id"])
    save_job(folder, job)
    return wait_result(config, client, folder, job, args.timeout)


def inspect_job(folder, client=None):
    """Read queue/history only. Never submits, updates or cancels a server task."""
    folder = Path(folder)
    job = json.loads((folder / "job.json").read_text(encoding="utf-8"))
    config = load_config()
    if config["url"] != job["url"] or config["output_node"] != job["output_node"]:
        raise ComfyError("inspection configuration differs from submitted job")
    client = client or Client(config["url"], config.get("request_timeout", 30))
    queue = client.call("GET", "/queue")
    history = client.call("GET", "/history")
    if not isinstance(queue, dict) or not isinstance(history, dict):
        raise ComfyError("invalid queue/history response; inspect manually without resubmitting")
    matches = {}
    expected = job.get("fingerprints", {}).get("submitted_workflow")
    client_id = job.get("client_id")

    def consider(prompt, location):
        if not isinstance(prompt, (list, tuple)) or len(prompt) < 4:
            return
        prompt_id, graph, extra = prompt[1], prompt[2], prompt[3]
        if client_id and expected and isinstance(graph, dict) and isinstance(extra, dict) and extra.get("client_id") == client_id and graph_digest(graph) == expected:
            matches[str(prompt_id)] = {"prompt_id": str(prompt_id), "location": location}

    for key in ("queue_running", "queue_pending"):
        for prompt in queue.get(key, []) or []:
            consider(prompt, key)
    for record in history.values():
        if isinstance(record, dict):
            consider(record.get("prompt"), "history")
    return {"status": job["status"], "matches": list(matches.values()),
            "prompt_id": job.get("prompt_id"), "client_id": client_id,
            "action": "resume" if len(matches) == 1 else "inspect manually; do not resubmit"}


def resume(folder, timeout=1800, client=None):
    validate_timeout(timeout)
    folder = Path(folder)
    job = json.loads((folder / "job.json").read_text(encoding="utf-8"))
    if job.get("provider") != "comfyui":
        raise ComfyError("not a ComfyUI job receipt")
    if job["status"] == "done":
        data = Path(job["artifact"]).read_bytes()
        if digest(data) != job["sha256"]:
            raise ComfyError("completed artifact checksum changed")
        return result_summary(folder, job)
    submitted = folder / "submitted-workflow.json"
    expected = job.get("fingerprints", {}).get("submitted_workflow")
    if expected and graph_digest(json.loads(submitted.read_text(encoding="utf-8"))) != expected:
        raise ComfyError("submitted workflow checksum changed")
    if job["status"] == "unknown":
        report = inspect_job(folder, client)
        if len(report["matches"]) != 1:
            raise ComfyError("job outcome is unknown; inspect the ComfyUI queue/history; do not resubmit")
        job.update(status="pending", prompt_id=report["matches"][0]["prompt_id"])
        save_job(folder, job)
    if job["status"] != "pending" or not job.get("prompt_id"):
        raise ComfyError("job cannot be resumed automatically; inspect the ComfyUI queue and job.json")
    config = load_config()
    if config["url"] != job["url"] or config["output_node"] != job["output_node"]:
        raise ComfyError("resume configuration differs from submitted job")
    # Read the frozen submitted job; changes to the source workflow do not change a running task.
    return wait_result(config, client or Client(config["url"], config.get("request_timeout", 30)), folder, job, timeout)


def check(client=None):
    """Read-only server/node/model discovery; never enqueue generation."""
    config = load_config()
    width,height=diagnostic_canvas(config)
    graph, _ = prepare(config, load_graph(config), prompt="", first="input.png",
                       last="last.png" if "last_image" in config["bindings"] else None,
                       width=width, height=height, duration=3)
    targets=seed_targets(config,graph)
    client = client or Client(config["url"], config.get("request_timeout", 30))
    info = client.call("GET", "/object_info")
    bounds=seed_bounds(graph,targets,info) if targets else None
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
            "missingNodes": missing, "unavailableModels": unavailable, "seedPolicy":"random-per-new-job" if targets else "workflow-default", "seedTargets":[list(t) for t in targets], "seedBounds":list(bounds) if bounds else None}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Resume an existing ComfyUI job without resubmitting")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--resume", metavar="OUT_DIR")
    mode.add_argument("--inspect", metavar="OUT_DIR", help="read queue/history to identify an unknown submission; no writes")
    mode.add_argument("--check", action="store_true", help="read server node and model availability, without generation")
    parser.add_argument("--timeout", type=float, default=1800)
    args = parser.parse_args()
    try:
        result = check() if args.check else inspect_job(args.inspect) if args.inspect else resume(args.resume, args.timeout)
        print(json.dumps(result))
        if result.get("status") == "incompatible":
            raise SystemExit(1)
    except (ComfyError, OSError, ValueError, KeyError, TypeError, OverflowError) as exc:
        parser.exit(1, f"error: {exc}\n")
