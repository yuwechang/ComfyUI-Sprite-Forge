import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/comfyui-forge-generate2dmedia/scripts"))
import comfyui_forge_media as comfy
import comfyui_forge_route_media as route

GRAPH = {
    "1": {"class_type": "LoadImage", "inputs": {"image": "old.png"}},
    "2": {"class_type": "LoadImage", "inputs": {"image": "last.png"}},
    "3": {"class_type": "Text", "inputs": {"text": "old prompt"}},
    "4": {"class_type": "I2V", "inputs": {"first_frame": ["1", 0], "last_frame": ["2", 0],
        "prompt": ["3", 0], "width": 64, "height": 64, "length": 5, "seed": 123}},
    "5": {"class_type": "SaveVideo", "inputs": {"images": ["4", 0], "fps": 24}},
    "99": {"class_type": "UIOnly", "inputs": {}},
}
CONFIG = {"url": "http://127.0.0.1:8188", "workflow": "workflow.json", "output_node": "5",
    "fps": 24, "frame_multiple": 17, "frame_offset": 5, "poll_interval": 0,
    "bindings": {"image": ["1", "image"], "last_image": ["2", "image"],
        "prompt": ["3", "text"], "width": ["4", "width"], "height": ["4", "height"],
        "length": ["4", "length"], "fps": ["5", "fps"]}, "last_frame_input": ["4", "last_frame"]}
def box(kind, body):
    return (len(body) + 8).to_bytes(4, "big") + kind + body

MP4 = box(b"ftyp", b"isom" + b"\0" * 4) + box(b"moov", box(b"trak", box(b"mdia", box(b"hdlr", b"\0" * 8 + b"vide" + b"\0" * 12)))) + box(b"mdat", b"test-payload")


class FakeClient:
    def __init__(self):
        self.calls, self.uploads = [], []
        self.fail = False

    def upload(self, path):
        self.uploads.append(path)
        return "uploaded/" + Path(path).name

    def call(self, method, path, body=None, content_type=None, raw=False):
        self.calls.append((method, path, body))
        if path == '/object_info':
            return {'I2V':{'input':{'required':{'seed':['INT',{'min':0,'max':2**53-1}]}}}}
        if path == "/prompt":
            return {"prompt_id": "test-id"}
        if path.startswith("/history/"):
            return {"test-id": {"status": {"completed": True, "status_str": "error" if self.fail else "success"},
                "outputs": {"5": {"gifs": [{"filename": "clip.mp4", "subfolder": "video", "type": "output"}]}}}}
        if path.startswith("/view?"):
            return MP4
        raise AssertionError(path)


class ComfyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "workflow.json").write_text(json.dumps(GRAPH))
        (self.root / "config.json").write_text(json.dumps(CONFIG))
        self.env = patch.dict("os.environ", {"COMFYUI_FORGE_CONFIG": str(self.root / "config.json")})
        self.env.start()
        Image.new("RGB", (96, 64), "magenta").save(self.root / "input.png")
        (self.root / "prompt.txt").write_text("one knight, fixed camera")
        self.args = SimpleNamespace(reference=str(self.root / "input.png"), last_frame=None,
            prompt_file=str(self.root / "prompt.txt"), duration=2, dry_run=False,
            out_dir=str(self.root / "result"), timeout=1)

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_binding_pruning_and_frame_cadence(self):
        graph, duration = comfy.prepare(CONFIG, GRAPH, prompt="new", first="uploaded.png", last=None,
                                        width=96, height=64, duration=2)
        self.assertNotIn("99", graph)
        self.assertNotIn("2", graph)
        self.assertNotIn("last_frame", graph["4"]["inputs"])
        self.assertEqual(graph["1"]["inputs"]["image"], "uploaded.png")
        self.assertEqual(graph["3"]["inputs"]["text"], "new")
        self.assertEqual(graph["4"]["inputs"]["length"], 56)
        self.assertEqual(duration, 56 / 24)
        self.assertEqual(GRAPH["1"]["inputs"]["image"], "old.png")

    def test_lifecycle_and_resume_never_submits_again(self):
        client = FakeClient()
        result = comfy.execute(self.args, client)
        self.assertEqual(Path(result["artifact"]).read_bytes(), MP4)
        self.assertEqual(len(client.uploads), 1)
        submitted = json.loads(next(body for method, path, body in client.calls if path == "/prompt"))["prompt"]
        self.assertEqual(submitted["4"]["inputs"]["width"], 96)
        job = json.loads((Path(self.args.out_dir) / "job.json").read_text())
        job["status"] = "pending"
        comfy.save_job(Path(self.args.out_dir), job)
        fresh = FakeClient()
        comfy.resume(self.args.out_dir, client=fresh)
        self.assertFalse(any(path == "/prompt" for _, path, _ in fresh.calls))

    def test_execution_failure_is_recorded(self):
        client = FakeClient()
        client.fail = True
        with self.assertRaises(comfy.ComfyError):
            comfy.execute(self.args, client)
        job = json.loads((Path(self.args.out_dir) / "job.json").read_text())
        self.assertEqual(job["status"], "failed")
        self.assertFalse((Path(self.args.out_dir) / "generated.mp4").exists())

    def test_dry_run_writes_nothing(self):
        self.args.dry_run = True
        client = FakeClient()
        comfy.execute(self.args, client)
        self.assertFalse(Path(self.args.out_dir).exists())
        self.assertEqual(client.calls, [])

    def test_ui_workflow_refused(self):
        (self.root / "workflow.json").write_text('{"nodes": []}')
        with self.assertRaises(comfy.ComfyError):
            comfy.load_graph(comfy.load_config())

    def test_route_is_explicit_and_reports_pin_duration(self):
        self.assertEqual(["local:comfyui"], route.requested_routes("video", "auto"))
        wanted = route.Wanted(last_frame=self.root / "tail.png", duration=2)
        result = route.resolve("video", "comfyui", wanted=wanted)
        self.assertTrue(result.candidates[0].pin)
        self.assertEqual(result.candidates[0].duration, 56 / 24)

    def test_pending_timeout_retains_id(self):
        self.args.timeout = 0.0001
        client = FakeClient()
        original = client.call
        client.call = lambda method, path, *a, **kw: {} if path.startswith('/history/') else original(method, path, *a, **kw)
        with self.assertRaises(comfy.ComfyError):
            comfy.execute(self.args, client)
        job = json.loads((Path(self.args.out_dir) / "job.json").read_text())
        self.assertEqual(job["prompt_id"], "test-id")
        self.assertEqual(job["status"], "pending")

    def test_local_url_required(self):
        config = dict(CONFIG, url="http://example.com")
        (self.root / "config.json").write_text(json.dumps(config))
        with self.assertRaises(comfy.ComfyError):
            comfy.load_config()

    def test_route_result_is_usable_by_sprite_set(self):
        client = FakeClient()
        command = ["video", "--route", "comfyui", "--prompt-file", self.args.prompt_file,
                   "--reference", self.args.reference, "--duration", "2", "--out-dir", self.args.out_dir]
        stream = io.StringIO()
        execute = comfy.execute
        with patch.object(comfy, "execute", side_effect=lambda args: execute(args, client)), patch("sys.stdout", stream):
            self.assertEqual(route.main(command), 0)
        result = json.loads(stream.getvalue())
        self.assertEqual(result["route"], "local:comfyui")
        self.assertTrue(Path(result["artifact"]).is_file())
        self.assertEqual(result["durationUsed"], 56 / 24)
        self.assertFalse(result["lastFrameUsed"])

    def test_sprite_set_does_not_replace_pending_folder(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/comfyui-forge-video2dsprite/scripts"))
        import comfyui_forge_sprite_set
        folder = self.root / "take" / "media"
        folder.mkdir(parents=True)
        for status in ("pending", "unknown"):
            (folder / "job.json").write_text(json.dumps({"provider": "comfyui", "status": status}))
            runner = SimpleNamespace(root=self.root)
            result = comfyui_forge_sprite_set.SetRunner.generate(runner, "idle", {"dir": "take"}, 1)
            self.assertEqual(result["status"], "error")
            self.assertTrue((folder / "job.json").is_file())

    def test_last_frame_upload_is_used(self):
        self.args.last_frame = self.args.reference
        client = FakeClient()
        comfy.execute(self.args, client)
        self.assertEqual(len(client.uploads), 2)
        body = json.loads(next(body for _, path, body in client.calls if path == "/prompt"))["prompt"]
        self.assertEqual(body["2"]["inputs"]["image"], "uploaded/input.png")

    def test_read_only_check_reports_missing_nodes(self):
        client = FakeClient()
        client.call = lambda *a, **kw: {}
        result = comfy.check(client)
        self.assertEqual(result["status"], "incompatible")
        self.assertNotIn("UIOnly", result["missingNodes"])


if __name__ == "__main__":
    unittest.main()
