import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from PIL import Image,ImageSequence

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('preview_export',ROOT/'tools/comfyui_forge_export_preview.py')
preview=importlib.util.module_from_spec(spec);spec.loader.exec_module(preview)

class ExportTests(unittest.TestCase):
    def test_eight_transparent_frames_have_one_second_duration(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);frames=base/'frames';frames.mkdir()
            for i in range(16):
                im=Image.new('RGBA',(128,128),(0,0,0,0))
                im.paste((20+i*10,100,180,255),(10+i,20,80+i,110));im.save(frames/f'frame_{i:03}.png')
            (base/'select.json').write_text(json.dumps({'sourceIndices':list(range(4,16))}),encoding='utf-8')
            result=preview.export(frames,base/'out',8,1,base/'select.json')
            self.assertEqual(result['durationMs'],1000);self.assertEqual(result['durationsMs'],[125]*8)
            self.assertEqual(result['gifDurationsMs'],[120,130]*4)
            self.assertEqual(len(set(result['sourceIndices'])),8)
            self.assertGreaterEqual(min(result['sourceIndices']),4)
            with Image.open(base/'out/preview.gif') as gif:
                self.assertEqual(gif.n_frames,8)
                self.assertEqual(sum(f.info['duration'] for f in ImageSequence.Iterator(gif)),1000)
                gif.seek(0);self.assertEqual(gif.convert('RGBA').getpixel((0,0))[3],0)
            with Image.open(base/'out/spritesheet.png') as atlas:self.assertEqual(atlas.size,(1024,128))
            with Image.open(base/'out/preview.apng') as apng:
                self.assertEqual(apng.n_frames,8)
                self.assertEqual(sum(f.info['duration'] for f in ImageSequence.Iterator(apng)),1000)

    def test_does_not_invent_missing_frames(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);Image.new('RGBA',(128,128)).save(base/'one.png')
            with self.assertRaises(ValueError):preview.export(base,base/'out',8,1)
            self.assertFalse((base/'out').exists())

if __name__=='__main__':unittest.main()
