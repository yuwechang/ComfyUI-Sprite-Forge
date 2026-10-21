from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

from PIL import Image, ImageSequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills/comfyui-forge-video2dsprite/scripts'))
import comfyui_forge_animation_spec as spec
from comfyui_forge_deliver_animation import deliver


class PreviewTests(unittest.TestCase):
    def fixture(self, root, count=8):
        frames = root / 'selected'
        frames.mkdir()
        for i in range(count):
            im = Image.new('RGBA', (128, 128))
            im.paste((20 + i * 20, 100, 180, 255), (10 + i, 20, 80 + i, 110))
            im.save(frames / f'frame_{i:04}.png')
        source = root / 'source.mp4'
        source.write_bytes(b'synthetic source; delivery copies without decoding')
        profile = {'confirmed': True, 'final': spec.final_spec('128x128', 1, 8, 'cycle')}
        return frames, source, profile

    def test_selected_frames_keep_alpha_timing_and_standard_layout(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            frames, source, profile = self.fixture(root)
            result = deliver(frames, source, root / 'out', profile)
            self.assertEqual(result['gifFrameDurationsMs'], [120, 130] * 4)
            self.assertEqual(result['durationMs'], 1000)
            with Image.open(root / 'out/preview.gif') as gif:
                self.assertEqual(gif.n_frames, 8)
                self.assertEqual(sum(f.info['duration'] for f in ImageSequence.Iterator(gif)), 1000)
                gif.seek(0)
                self.assertEqual(gif.convert('RGBA').getpixel((0, 0))[3], 0)
            with Image.open(root / 'out/animation-sheet.png') as sheet:
                self.assertEqual(sheet.size, (512, 256))
            with zipfile.ZipFile(root / 'out/animation.zip') as archive:
                self.assertEqual(len(archive.namelist()), 11)
                for i, original in enumerate(sorted(frames.glob('*.png'))):
                    self.assertEqual(archive.read(f'frames/frame_{i:04}.png'), original.read_bytes())
            self.assertFalse(list((root / 'out').rglob('*.apng')))
            self.assertFalse(list((root / 'out').rglob('*.json')))

    def test_missing_selected_frames_are_refused_without_partial_delivery(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            frames, source, profile = self.fixture(root, count=1)
            with self.assertRaises(ValueError):
                deliver(frames, source, root / 'out', profile)
            self.assertFalse((root / 'out').exists())


if __name__ == '__main__':
    unittest.main()
