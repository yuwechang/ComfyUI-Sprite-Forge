import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
from fractions import Fraction
from PIL import Image, ImageDraw
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'skills/comfyui-forge-video2dsprite/scripts'))
import comfyui_forge_core as core
import comfyui_forge_gait_loop as gait
import comfyui_forge_prepare_i2v_input as prep
import comfyui_forge_register_clip as register
import comfyui_forge_retime as retime
import comfyui_forge_finish_frames as finish
import comfyui_forge_finalize_animation as finalizer
import comfyui_forge_animation_spec as spec
from comfyui_forge_selection_tools import playback_plan


class SelectionPreservationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def fixture(self,kind):
        root=self.root/kind;root.mkdir()
        frames=root/'source';frames.mkdir()
        for i in range(38):
            phase=2*math.pi*(i%12)/(12 if kind=='cycle' else 11)
            x=52+round(4*(math.sin(phase) if kind!='oneshot-hold' else (i%12)/11))
            im=Image.new('RGBA',(128,128))
            ImageDraw.Draw(im).rectangle((x,42,x+20,96),fill=(160+round(40*math.cos(phase)),90,50,255))
            im.save(frames/f'{i:03}.png')
        master=root/'master.png'
        im=Image.new('RGBA',(64,64));ImageDraw.Draw(im).rectangle((22,12,42,54),fill=(200,90,50,255));im.save(master)
        prep.cmd_prepare(prep.build_parser().parse_args(['prepare','--master',str(master),
            '--motion-type',kind,'--description','requested motion','--canvas','128,128',
            '--subject-height','0.5','--output-dir',str(root/'prepared')]))
        indices=[12,14,16,18,20,22 if kind=='cycle' else 23]
        ticks=[1,1,3,1,1,1]
        clip=gait.load_clip(frames,Fraction(24))
        extra={'motionType':kind,'ticks':ticks,'tickHz':8}
        if kind=='cycle':
            extra['closureEvidence']=[{'sourceIndex':i,'file':clip.names[i],'sha256':clip.hashes[i]} for i in (24,25)]
        selection=root/'selection.json'
        durations,_=retime.tick_durations(ticks,8)
        document=gait.build_selection(clip,root,indices,durations,
            policy='cycle' if kind=='cycle' else 'oneshot',method='authored candidate',review='known test poses',
            kind=kind,events=[{'name':'marker','tick':2,'sourceIndex':16}],extra=extra,window=(12,24))
        core.write_json(selection,document)
        register.cmd_apply(register.build_parser().parse_args(['apply','--job',str(root/'prepared/registration_job.json'),
            '--frames',str(frames),'--selection',str(selection),'--rest-frames','none','--output-dir',str(root/'registered')]))
        return root,selection

    def test_all_types_preserve_candidate_timing_event_pose_and_source_through_delivery(self):
        for kind in ('cycle','oneshot-return','oneshot-hold'):
            with self.subTest(kind=kind):
                root,original=self.fixture(kind)
                frames=root/'registered/frames'
                self.assertEqual(len(list(frames.glob('*.png'))),14 if kind=='cycle' else 12)
                incoming=original
                for revision in range(2):
                    output=root/f'retime-{revision}'
                    retime.retime(retime.build_parser().parse_args(['--frames-dir',str(frames),'--fps','24',
                        '--selection',str(incoming),'--output-dir',str(output)]))
                    incoming=output/'selection.json'
                    selected=gait.read_selection(incoming)
                    self.assertEqual(selected['raw']['ticks'],[1,1,3,1,1,1])
                    self.assertEqual(selected['indices'],[0,2,4,6,8,10 if kind=='cycle' else 11])
                    marker=next(e for e in selected['raw']['events'] if e['name']=='marker')
                    self.assertEqual(marker['sourceIndex'],4)
                    self.assertEqual(marker['tick'],2)
                    self.assertTrue(selected['raw']['validationInputs'])
                finish.cmd_finish(finish.build_parser().parse_args(['hd','--frames',str(root/'registered'),
                    '--target-height','20','--canvas','32x32','--canvas-anchor','16,27','--output-dir',str(root/'finished')]))
                specification=root/'spec.json';core.write_json(specification,{'confirmed':True,'final':spec.final_spec('32x32',1,8,kind)})
                source=root/'source.mp4';source.write_bytes(b'retained-test-source')
                work=root/'review'
                receipt=finalizer.prepare(root/'finished',incoming,specification,source,work)
                picked=receipt['sourceIndices']
                self.assertEqual(picked.count(4),3)
                self.assertEqual(len(picked),8)
                self.assertTrue(all(i<12 for i in picked))
                self.assertEqual([r['sourceIndex'] for r in receipt['sourceMapping']],[i+12 for i in picked])
                if kind!='cycle':
                    self.assertEqual((picked[0],picked[-1]),(0,11))
                marker=next(e for e in receipt['timing']['events'] if e['name']=='marker')
                self.assertEqual(picked[marker['outputFrame']],4)
                self.assertEqual(receipt['specification']['final']['motionType'],kind)
                original_bytes=original.read_bytes();original.write_bytes(original_bytes+b' ')
                with self.assertRaisesRegex(ValueError,'input changed after review'):
                    finalizer.approve(work,root/'delivery','Must reject changed evidence')
                self.assertFalse((root/'delivery').exists())
                original.write_bytes(original_bytes)
                unused_source=root/'source/013.png'
                unused_bytes=unused_source.read_bytes();unused_source.write_bytes(b'changed unselected evidence')
                with self.assertRaisesRegex(ValueError,'input changed after review'):
                    finalizer.approve(work,root/'delivery','Must retain the whole candidate evidence')
                unused_source.write_bytes(unused_bytes)
                finalizer.approve(work,root/'delivery','Known typed motion, timing and event poses verified')
                with zipfile.ZipFile(root/'delivery/animation.zip') as archive:
                    self.assertEqual(len(archive.namelist()),11)

    def test_event_pose_is_never_replaced_by_a_later_sample(self):
        result=retime.auto_oneshot(np.r_[np.ones(10),np.zeros(30)],np.zeros(40),20,
            duration_ms=1000,rate=Fraction(8),event_sources=[('contact',25),('release',37)])
        for event in result['events']:
            if event['name'] in ('contact','release'):
                position=retime._frame_at(result['edges'],event['tick'])
                self.assertEqual(result['indices'][position],event['sourceIndex'])
        self.assertEqual((result['indices'][0],result['indices'][-1]),(20,59))
        keyed=retime.auto_oneshot(np.ones(40),np.zeros(40),0,duration_ms=1000,rate=Fraction(8),
            keys=[{'name':'key','source':20,'at':0.5,'holdMs':250}],
            event_sources=[('contact',5),('release',31)])
        pose_slots=[keyed['indices'][retime._frame_at(keyed['edges'],slot*keyed['hz']//8)] for slot in range(8)]
        self.assertEqual(pose_slots[4:6],[20,20])
        self.assertIn(5,pose_slots);self.assertIn(31,pose_slots)
        clustered=retime.auto_oneshot(np.ones(40),np.zeros(40),0,duration_ms=1000,rate=Fraction(8),
            event_sources=[('event_'+str(i),i) for i in range(18,24)])
        self.assertEqual(clustered['indices'],[0,18,19,20,21,22,23,39])
        with self.assertRaisesRegex(ValueError,'event poses and endpoints exceed'):
            retime.auto_oneshot(np.ones(30),np.zeros(30),0,duration_ms=1000,rate=Fraction(4),
                event_sources=[('a',5),('b',10),('c',15)])

    def test_inherited_clock_quantization_cannot_change_event_pose(self):
        for kind in ('cycle','oneshot-return','oneshot-hold'):
            root,original=self.fixture(kind)
            frames=root/'registered/frames'
            for duration in (1000,2000):
                output=root/f'duration-{duration}'
                retime.retime(retime.build_parser().parse_args(['--frames-dir',str(frames),'--fps','24',
                    '--selection',str(original),'--duration-ms',str(duration),'--output-dir',str(output)]))
                chosen=gait.read_selection(output/'selection.json')
                plan=playback_plan(chosen,8,'loop' if kind=='cycle' else 'oneshot')
                event=next(e for e in plan['events'] if e['name']=='marker')
                self.assertEqual(plan['sourceIndices'][event['outputFrame']],4)
                self.assertEqual(sum(chosen['durations']),duration)
            with self.assertRaisesRegex(ValueError,'motion contract'):
                retime.retime(retime.build_parser().parse_args(['--frames-dir',str(frames),'--fps','24',
                    '--selection',str(original),'--kind','oneshot-hold' if kind!='oneshot-hold' else 'cycle',
                    '--output-dir',str(root/'wrong-type')]))

    def test_all_types_reject_silent_crop_truncation_and_retiming_from_replacement_ranges(self):
        for kind in ('cycle','oneshot-return','oneshot-hold'):
            with self.subTest(kind=kind):
                root,original=self.fixture(kind)
                with self.assertRaisesRegex(ValueError,'no truncation was applied'):
                    register.cmd_apply(register.build_parser().parse_args(['apply',
                        '--job',str(root/'prepared/registration_job.json'),'--frames',str(root/'source'),
                        '--range','12:99','--rest-frames','none','--output-dir',str(root/'truncated')]))
                self.assertFalse((root/'truncated').exists())
                with self.assertRaisesRegex(ValueError,'do not replace it'):
                    retime.retime(retime.build_parser().parse_args(['--frames-dir',str(root/'registered/frames'),
                        '--fps','24','--range','0:6','--kind',kind,'--output-dir',str(root/'replacement')]))
                path=root/'registered/registration.json'
                metadata=json.loads(path.read_text());metadata['frames'][0]['sourceIndex']+=1
                path.write_text(json.dumps(metadata))
                with self.assertRaisesRegex(ValueError,'frame mapping or checksum changed'):
                    retime.retime(retime.build_parser().parse_args(['--frames-dir',str(root/'registered/frames'),
                        '--fps','24','--selection',str(original),'--output-dir',str(root/'bad-mapping')]))


if __name__=='__main__':unittest.main()
