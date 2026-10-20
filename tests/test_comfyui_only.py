"""Behavioral guardrails for the local-only fork; no GPU or external network."""
import contextlib
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/comfyui-forge-generate2dmedia/scripts'))
import comfyui_forge_route_media as route
import comfyui_forge_media as comfy

class LocalOnlyTests(unittest.TestCase):
    def test_cloud_and_cli_routes_rejected(self):
        for name in ('api','openai','gemini','xai','byteplus','fal','codex-cli','grok-cli','grok-acp','local'):
            with self.subTest(name=name),self.assertRaises(SystemExit) as raised,contextlib.redirect_stderr(io.StringIO()):
                route.main(['resolve','--kind','video','--route',name])
            self.assertEqual(raised.exception.code,2)

    def test_environment_cannot_restore_another_provider(self):
        with patch.dict('os.environ',{'COMFYUI_FORGE_VIDEO_ROUTE':'api:xai','COMFYUI_FORGE_MEDIA_DELEGATE_DISABLED':'must-not-run.py'}):
            self.assertEqual(route.requested_routes('video','auto'),['local:comfyui'])

    def test_image_generation_stops_without_fallback(self):
        output=io.StringIO()
        with contextlib.redirect_stdout(output),patch.object(comfy,'load_config',side_effect=AssertionError('must not load a provider')):
            self.assertEqual(route.main(['resolve','--kind','image']),3)
        self.assertNotIn('comfyui-forge-codeart2d',output.getvalue())

    def test_redirects_cannot_leave_loopback(self):
        with self.assertRaises(comfy.ComfyError):
            comfy.NoRedirect().redirect_request(None,None,302,'redirect',{},'https://example.com')

    def test_removed_provider_modules_are_absent(self):
        scripts=Path(route.__file__).parent
        for name in ('generate_media','cli_media','media_config','media_providers','media_ledger'):
            self.assertFalse((scripts/(name+'.py')).exists())

    def test_default_duration_is_three_seconds(self):
        args=route.build_parser().parse_args(['video','--reference','input.png','--prompt-file','prompt.txt','--out-dir','new'])
        self.assertEqual(args.duration,3)

if __name__=='__main__':unittest.main()
