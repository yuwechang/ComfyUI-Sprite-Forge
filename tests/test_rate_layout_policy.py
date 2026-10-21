"""Final-rate boundaries and delivery layout, including durations other than one second."""
from pathlib import Path
import sys
import tempfile
import unittest

from PIL import Image, ImageSequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills/comfyui-forge-video2dsprite/scripts'))
import comfyui_forge_animation_spec as spec
import comfyui_forge_contracts as contracts
from comfyui_forge_deliver_animation import deliver


class RateLayoutPolicyTests(unittest.TestCase):
    def test_final_rate_bounds_at_planning_and_confirmed_boundaries(self):
        for fps in (4, 6, 8, 10, 12, 14, 16, 18, 20, 24):
            with self.subTest(fps=fps):
                final = spec.plan(fps=fps, mode='oneshot-return')['final']
                self.assertEqual(contracts.final(final)['frameCount'], fps)
        for fps in (3, '3999/1000', '24001/1000', 25, 100):
            with self.subTest(fps=fps):
                with self.assertRaisesRegex(ValueError, 'between 4 and 24'):
                    spec.plan(fps=fps, mode='oneshot-return')
                final = spec.final_spec('16x16', 1, 8, 'oneshot-return')
                final.update(fps=float(contracts.positive(fps)), fpsRational=str(fps))
                with self.assertRaisesRegex(ValueError, 'between 4 and 24'):
                    contracts.confirmed({'confirmed': True, 'final': final})

    def test_actual_sheet_order_alpha_timing_and_receipt_resume(self):
        # frame count, fps, seconds, columns, rows
        cases = [(4, 4, 1, 4, 1), (6, 6, 1, 6, 1), (8, 8, 1, 4, 2),
                 (10, 10, 1, 5, 2), (12, 12, 1, 6, 2), (14, 14, 1, 7, 2),
                 (16, 16, 1, 8, 2), (24, 24, 1, 12, 2),
                 (24, 12, 2, 12, 2), (9, 6, '3/2', 5, 2), (2, 4, '1/2', 2, 1)]
        for count, fps, seconds, columns, rows in cases:
            with self.subTest(count=count, fps=fps, seconds=seconds), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); frames = root / 'selected'; frames.mkdir()
                images = []
                for index in range(count):
                    image = Image.new('RGBA', (16, 16))
                    image.paste((index * 9, 60, 140, 255), (3, 3, 13, 14))
                    image.save(frames / f'frame_{index:04}.png'); images.append(image)
                source = root / 'source.mp4'; source.write_bytes(b'offline delivery fixture')
                profile = {'confirmed': True, 'final': spec.final_spec('16x16', seconds, fps, 'oneshot-return')}
                out = root / 'delivery'; report = root / 'receipt.json'
                receipt = deliver(frames, source, out, profile, report=report)
                self.assertEqual((receipt['columns'], receipt['rows']), (columns, rows))
                with Image.open(out / 'animation-sheet.png') as sheet:
                    self.assertEqual(sheet.size, (columns * 16, rows * 16))
                    for index, expected in enumerate(images):
                        x, y = index % columns * 16, index // columns * 16
                        self.assertEqual(sheet.crop((x, y, x + 16, y + 16)).tobytes(), expected.tobytes())
                    if count < columns * rows:
                        self.assertIsNone(sheet.crop(((columns - 1) * 16, 16, columns * 16, 32)).getbbox())
                with Image.open(out / 'preview.gif') as gif:
                    self.assertEqual(sum(frame.info['duration'] for frame in ImageSequence.Iterator(gif)), receipt['durationMs'])
                self.assertEqual(deliver(frames, source, out, profile, report=report), receipt)
                override = deliver(frames, source, root / 'explicit-layout', profile, columns=count)
                self.assertEqual((override['columns'], override['rows']), (count, 1))
                if rows == 2:
                    with self.assertRaisesRegex(ValueError, 'different inputs or specification'):
                        deliver(frames, source, out, profile, columns=count, report=report)


if __name__ == '__main__':
    unittest.main()
