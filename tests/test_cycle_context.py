import json
import math
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'skills/comfyui-forge-video2dsprite/scripts'))
import comfyui_forge_gait_loop as gait
import comfyui_forge_register_clip as register
import comfyui_forge_prepare_i2v_input as prep
import comfyui_forge_finish_frames as finish
import comfyui_forge_finalize_animation as finalizer
import comfyui_forge_animation_spec as spec


class CycleContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.frames = self.root/'source'
        self.frames.mkdir()
        for i in range(38):
            phase = 2*math.pi*i/12
            image = Image.new('RGBA', (128,128))
            x = 52 + round(4*math.sin(phase))
            ImageDraw.Draw(image).rectangle((x,42,x+20,96),
                fill=(160+round(60*math.cos(phase)),90,50,255))
            image.save(self.frames/f'{i:03}.png')
        self.source_selection = self.select(self.frames, 'source-selection', '12:24')

    def tearDown(self):
        self.temp.cleanup()

    def select(self, frames, output, candidate=None):
        argv = ['select','--frames-dir',str(frames),'--fps','24','--min-seconds','0.5',
                '--max-seconds','0.5','--dedupe-cap','0','--no-aids',
                '--output-dir',str(self.root/output)]
        if candidate:
            argv += ['--candidate',candidate]
        return gait.cmd_select(gait.build_parser().parse_args(argv))

    def register_candidate(self):
        master = self.root/'master.png'
        image = Image.new('RGBA',(64,64))
        ImageDraw.Draw(image).rectangle((22,12,42,54),fill=(200,90,50,255))
        image.save(master)
        prepared = self.root/'prepared'
        prep.cmd_prepare(prep.build_parser().parse_args(['prepare','--master',str(master),
            '--motion-type','cycle','--description','periodic body motion','--canvas','128,128',
            '--subject-height','0.5','--output-dir',str(prepared)]))
        return register.cmd_apply(register.build_parser().parse_args(['apply',
            '--job',str(prepared/'registration_job.json'),'--frames',str(self.frames),
            '--cycle-selection',self.source_selection['selection'],'--rest-frames','none',
            '--output-dir',str(self.root/'registered')]))

    def test_truncation_is_missing_evidence_not_failed_closure(self):
        truncated = self.root/'truncated'
        truncated.mkdir()
        for path in sorted(self.frames.glob('*.png'))[12:24]:
            shutil.copy2(path,truncated/path.name)
        with self.assertRaisesRegex(ValueError, 'insufficient-context'):
            self.select(truncated,'truncated-selection')
        with self.assertRaisesRegex(ValueError, 'insufficient-context'):
            self.select(truncated,'truncated-candidate','0:12')
        self.assertFalse((self.root/'truncated-selection').exists())

    def test_registered_candidate_keeps_context_and_delivery_excludes_it(self):
        result = self.register_candidate()
        self.assertEqual(result['frames'],14)
        registered = self.root/'registered'
        metadata = json.loads((registered/'registration.json').read_text())
        self.assertEqual(metadata['candidateSelection']['sourceRange'],[12,24])
        self.assertEqual(metadata['candidateSelection']['contextSourceIndices'],[24,25])
        selection = self.select(registered/'frames','registered-selection')
        document = json.loads(Path(selection['selection']).read_text())
        self.assertEqual((document['start'],document['endExclusive']),(0,12))
        self.assertEqual(document['sourceIndices'],list(range(12)))
        self.assertEqual([r['sourceIndex'] for r in document['closureEvidence']],[12,13])
        self.assertEqual(document['candidateProvenance']['sourceRange'],[12,24])
        finished = self.root/'finished'
        finish.cmd_finish(finish.build_parser().parse_args(['hd','--frames',str(registered),
            '--target-height','20','--canvas','32x32','--canvas-anchor','16,27',
            '--output-dir',str(finished)]))
        specification = self.root/'spec.json'
        specification.write_text(json.dumps({'confirmed':True,
            'final':spec.final_spec('32x32',1,8,'cycle')}))
        source = self.root/'source.mp4'
        source.write_bytes(b'retained-source')
        receipt = finalizer.prepare(finished,selection['selection'],specification,source,self.root/'review')
        self.assertEqual(len(receipt['sourceIndices']),8)
        self.assertLess(max(receipt['sourceIndices']),12)
        evidence = registered/'frames/frame_000012.png'
        original = evidence.read_bytes()
        evidence.write_bytes(b'changed successor')
        with self.assertRaisesRegex(ValueError, 'input changed after review'):
            finalizer.approve(self.root/'review',self.root/'delivery','Context changed after review')
        self.assertFalse((self.root/'delivery').exists())
        evidence.write_bytes(original)
        finalizer.approve(self.root/'review',self.root/'delivery','Reviewed synthetic periodic motion')
        self.assertEqual(len(list((self.root/'delivery/frames').glob('*.png'))),8)
        evidence.write_bytes(b'changed successor')
        with self.assertRaisesRegex(ValueError, 'closure evidence checksum changed'):
            gait.verify_selection(gait.read_selection(Path(selection['selection'])),
                                  Path(selection['selection']),registered/'frames')

    def test_preserved_candidate_cannot_be_replaced_or_reused_after_tampering(self):
        self.register_candidate()
        with self.assertRaisesRegex(ValueError, 'differs from the cycle preserved'):
            self.select(self.root/'registered/frames','different-candidate','1:13')
        path = Path(self.source_selection['selection'])
        path.write_text(path.read_text()+' ')
        with self.assertRaisesRegex(ValueError, 'source selection changed'):
            self.select(self.root/'registered/frames','changed-selection')

    def test_real_closure_failure_and_drift_have_distinct_diagnostics(self):
        frames = self.root/'nonperiodic'
        frames.mkdir()
        for i in range(38):
            image = Image.new('RGBA',(48,48))
            ImageDraw.Draw(image).rectangle((12,10,30,38),fill=(40+i*5,90,50,255))
            image.save(frames/f'{i:03}.png')
        with self.assertRaisesRegex(ValueError, 'candidate-rejected.*does not close'):
            self.select(frames,'bad-closure','0:12')
        with self.assertRaisesRegex(ValueError, 'closure-failed'):
            self.select(frames,'no-closure')
        analysis = gait.analyse(self.frames,'24',min_seconds=0.5,max_seconds=0.5)
        analysis.usable = {**analysis.usable,'endExclusive':20,'reason':'measured scale drift'}
        with self.assertRaisesRegex(ValueError, 'drift-limit'):
            gait.recommend(analysis,candidate=(12,24))


if __name__ == '__main__':
    unittest.main()
