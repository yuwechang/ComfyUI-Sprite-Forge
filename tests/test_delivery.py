"""The delivery ZIP contains only selected frames, sheet, preview and source."""
import json
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


class DeliveryTests(unittest.TestCase):
    def prepare(self, root, size=(32, 32), mode='oneshot'):
        frames = root / 'work/selected';frames.mkdir(parents=True)
        for i in range(8):
            im = Image.new('RGBA', size, (0, 0, 0, 0))
            im.paste((20 + i * 20, 120, 180, 255), (2 + i, 6, 15 + i, 28))
            im.save(frames / f'frame_{i:04}.png')
        (frames / 'internal.json').write_text('private processing metadata')
        (root / 'work/unselected.png').write_bytes(b'not a delivery')
        source = root / 'work/original.mp4';source.write_bytes(b'test MP4 payload, no video decode required')
        profile = spec.save(spec.plan(cell='32x32', mode=mode), 'balanced', root / 'prefs.json', True)
        return frames, source, profile

    def test_only_four_kinds_are_zipped_and_metadata_stays_at_work(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp);frames, source, profile = self.prepare(root)
            out = root / 'delivery';report = root / 'work/receipt.json'
            result = deliver(frames, source, out, profile, columns=4, report=report)
            expected = {f'frames/frame_{i:04}.png' for i in range(8)} | {'animation-sheet.png', 'preview.gif', 'source.mp4'}
            with zipfile.ZipFile(out / 'animation.zip') as z:self.assertEqual(set(z.namelist()), expected)
            self.assertFalse(list(out.rglob('*.json')))
            self.assertTrue(report.exists());self.assertTrue(source.exists());self.assertTrue((frames / 'internal.json').exists())
            self.assertEqual(Image.open(out / 'animation-sheet.png').size, (128, 64))
            with Image.open(out / 'preview.gif') as gif:
                self.assertEqual(sum(f.info['duration'] for f in ImageSequence.Iterator(gif)), 1000)
                self.assertEqual(gif.info['loop'], 0)
            self.assertEqual(result['mode'], 'oneshot')

    def test_incorrect_frame_size_or_extra_unselected_frame_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp);frames, source, profile = self.prepare(root)
            Image.new('RGBA', (64, 64)).save(frames / 'frame_0000.png')
            with self.assertRaises(ValueError):deliver(frames, source, root / 'bad', profile)
            self.assertFalse((root / 'bad').exists())
            Image.new('RGBA', (32, 32)).save(frames / 'unselected.png')
            with self.assertRaises(ValueError):deliver(frames, source, root / 'bad', profile)

    def test_existing_output_and_internal_report_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp);frames, source, profile = self.prepare(root)
            out = root / 'delivery'
            with self.assertRaises(ValueError):deliver(frames, source, out, profile, report=out / 'report.json')
            self.assertFalse(out.exists())
            out.mkdir();(out / 'keep.txt').write_text('keep')
            with self.assertRaises(ValueError):deliver(frames, source, out, profile)
            self.assertEqual((out / 'keep.txt').read_text(), 'keep')

    def test_unconfirmed_proposal_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp);frames, source, _ = self.prepare(root)
            with self.assertRaises(ValueError):deliver(frames, source, root / 'bad', spec.plan(mode='loop'))


if __name__ == '__main__':
    unittest.main()
