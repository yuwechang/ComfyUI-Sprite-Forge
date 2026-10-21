import contextlib
import io
import json
from pathlib import Path
import shutil
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills/comfyui-forge-video2dsprite/scripts'))
import comfyui_forge_av as av
import comfyui_forge_video2dsprite as video


class MediaDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        av._probe_capabilities.cache_clear()

    def tearDown(self):
        av._probe_capabilities.cache_clear()

    def test_missing_tools_are_reported_without_starting_processes(self):
        with patch.object(av.shutil, 'which', return_value=None), patch.object(av, 'run') as run:
            result = av.ffmpeg_info()
        run.assert_not_called()
        self.assertEqual(set(result['errors']), {'ffmpeg', 'ffprobe'})
        self.assertFalse(any(result['functional'].values()))

    def test_failed_decode_and_invalid_probe_output_are_not_reported_ready(self):
        with patch.object(av.shutil, 'which', side_effect=lambda name: name), \
             patch.object(av, 'run', side_effect=['ffmpeg version test', 'invalid JSON']), \
             patch.object(av, '_stream_frames', side_effect=av.ForgeAVError('decode failed')):
            result = av.ffmpeg_info()
        self.assertFalse(any(result['functional'].values()))
        self.assertIn('rgba_decode', result['errors'])
        self.assertIn('stream_probe', result['errors'])

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg and FFprobe required')
    def test_doctor_decodes_alpha_and_probes_dimensions_with_real_tools(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(video.cmd_doctor(None), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result['errors'], {})
        self.assertTrue(result['functional']['rgba_decode'])
        self.assertTrue(result['functional']['stream_probe'])
        self.assertNotIn('packed', result)
        self.assertNotIn('webm', result)


if __name__ == '__main__':
    unittest.main()
