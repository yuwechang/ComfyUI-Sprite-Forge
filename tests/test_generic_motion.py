"""Behavior regressions for arbitrary motion labels and flat input backgrounds."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from fractions import Fraction
import numpy as np
from PIL import Image, ImageDraw
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'skills/comfyui-forge-video2dsprite/scripts'))
import comfyui_forge_motion_contract as mc
import comfyui_forge_background_input as bg
import comfyui_forge_prepare_i2v_input as prep
import comfyui_forge_retime
import comfyui_forge_gait_loop
import comfyui_forge_animation_spec
import comfyui_forge_sprite_set
from batch_fixture import confirmed

class GenericTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
    def tearDown(self): self.tmp.cleanup()
    def art(self,colour,alpha=255):
        im=Image.new('RGBA',(64,64),(*colour,alpha))
        ImageDraw.Draw(im).rectangle((20,12,44,52),fill=(100,70,160,255))
        return np.asarray(im).copy()
    def test_flat_arbitrary_neutral_and_chromatic_backgrounds_extract(self):
        for colour in ((255,255,255),(25,25,25),(255,120,10),(0,255,255),(123,150,177)):
            with self.subTest(colour=colour):
                pixels=self.art(colour);before=pixels.copy()
                out,report=bg.extract(pixels)
                self.assertEqual(report['colour'],list(colour))
                self.assertEqual(out[0,0,3],0);self.assertEqual(out[30,30,3],255)
                np.testing.assert_array_equal(out[30,30,:3],pixels[30,30,:3])
                np.testing.assert_array_equal(pixels,before)
    def test_failed_extraction_stops_before_publication(self):
        for case in ('inconsistent','ambiguous','empty'):
            pixels=self.art((255,255,255))
            if case=='inconsistent': pixels[:8,:,:3]=(20,100,200)
            if case=='ambiguous': pixels[25:35,25:35,:3]=(255,255,255)
            if case=='empty': pixels[:]=(255,255,255,255)
            path=self.root/(case+'.png');Image.fromarray(pixels).save(path)
            args=prep.build_parser().parse_args(['prepare','--master',str(path),'--motion-type','cycle',
                '--description','requested movement','--canvas','128,128','--output-dir',str(self.root/case)])
            with self.assertRaises(ValueError):prep.cmd_prepare(args)
            self.assertFalse((self.root/case).exists())
    def test_alpha250_any_flat_colour_is_extracted_and_generation_key_can_change(self):
        source=self.root/'input.png';Image.fromarray(self.art((230,210,170),250)).save(source)
        args=prep.build_parser().parse_args(['prepare','--master',str(source),'--motion-type','oneshot-hold',
             '--description','requested terminal movement','--canvas','128,128','--output-dir',str(self.root/'ready')])
        doc=prep.cmd_prepare(args);job=json.loads(Path(doc['metadata']).read_text())
        self.assertEqual(job['motionType'],'oneshot-hold');self.assertFalse(job['returnsToRest'])
        self.assertNotEqual(job['keyColor'],job['masterKeying']['backdrop'])
        with Image.open(self.root/'ready/master.png') as im:self.assertEqual(im.getchannel('A').getextrema()[0],0)
    def test_real_alpha_is_preserved(self):
        pixels=self.art((150,80,30),0)
        self.assertFalse(prep.needs_background_keying(pixels))
    def test_three_contracts_are_distinct_and_labels_do_not_choose_behavior(self):
        rows=[{'id':label,'type':kind,'description':'bespoke requested motion','durationSeconds':1}
              for label,kind in zip(('unlisted_a','unlisted_b','unlisted_c'),mc.TYPES)]
        path=self.root/'motions.json';path.write_text(json.dumps(rows))
        loaded=mc.definitions(path)
        self.assertEqual(len(loaded),3)
        for row in rows:
            preset=comfyui_forge_sprite_set.generic_preset(row)
            self.assertEqual(preset.prepare_action,row['type'])
            self.assertFalse(preset.hit_tick);self.assertFalse(preset.pin_last)
            self.assertEqual(preset.returns_to_rest,row['type']=='oneshot-return')
            self.assertEqual(comfyui_forge_animation_spec.final_spec('32x32',1,8,row['type'])['motionType'],row['type'])
            changed=dict(row,id='different_label')
            self.assertEqual(preset,comfyui_forge_sprite_set.generic_preset(changed))
    def test_prompt_library_has_only_generic_contracts(self):
        library=comfyui_forge_sprite_set.load_library()
        self.assertEqual(set(library.templates),set(mc.TYPES))
        self.assertEqual(library.negatives,{})

    def test_type_and_description_are_required_no_named_presets(self):
        path=self.root/'motions.json'
        for row in ({'id':'a','description':'x'}, {'id':'a','type':'cycle'},
                    {'id':'a','type':'unknown','description':'x'},
                    {'id':'a','type':'oneshot-return','description':'x'}):
            path.write_text(json.dumps([row]))
            with self.assertRaises(ValueError):mc.definitions(path)
    def test_source_candidate_endings_differ_without_action_templates(self):
        for kind in mc.TYPES:
            template=prep.motion_template(kind,'bespoke movement')
            rows=prep.timeline(template,3.25,3)
            candidates=[x for x in rows if x['role']=='candidate']
            self.assertEqual(len(candidates),3)
            self.assertEqual(sum(x['role']=='reset' for x in rows),0 if kind=='cycle' else 2)
            self.assertEqual(rows[-1]['role'],'candidate')
            self.assertEqual(template.returns_to_rest,kind=='oneshot-return')
    def frames(self):
        folder=self.root/'frames';folder.mkdir(exist_ok=True)
        for i in range(36):
            im=Image.new('RGBA',(40,40));d=ImageDraw.Draw(im)
            x=10+(i%12)//2
            d.rectangle((x,10,x+10,30),fill=(80+i*3,120,180,255))
            im.save(folder/f'frame_{i:04}.png')
        return folder
    def test_both_single_play_contracts_keep_one_candidate_and_its_terminal(self):
        frames=self.frames()
        for kind in ('oneshot-return','oneshot-hold'):
            out=self.root/kind
            args=comfyui_forge_retime.build_parser().parse_args(['--frames-dir',str(frames),'--fps','24','--kind',kind,
                '--range','12:24','--auto-oneshot','--duration-ms','1000','--output-fps','8','--output-dir',str(out),
                '--key','focus=17@0.4+250'])
            comfyui_forge_retime.retime(args)
            selected=comfyui_forge_gait_loop.read_selection(out/'selection.json')
            self.assertEqual(selected['indices'][0],12);self.assertEqual(selected['indices'][-1],23)
            self.assertTrue(all(12<=i<24 for i in selected['indices']))
            self.assertEqual(selected['raw']['motionType'],kind)
            self.assertIn('focus',[e['name'] for e in selected['raw']['events']])
            self.assertNotIn('hit',[e['name'] for e in selected['raw']['events']])
    def test_single_play_cannot_be_relabelled_continuous_by_matching_poses(self):
        for kind in ('oneshot-return','oneshot-hold'):
            with self.assertRaises(ValueError):comfyui_forge_retime.check_policy(kind,'cycle',[0,1,2])
            self.assertTrue(comfyui_forge_retime.check_policy(kind,'oneshot',[0,1,2]))
        with self.assertRaises(ValueError):comfyui_forge_retime.check_policy('cycle','pingpong',[0,1,2])
    def test_auto_source_endpoints_are_not_trimmed_to_an_inferred_neutral_pose(self):
        result=comfyui_forge_retime.auto_oneshot(np.r_[np.ones(6),np.zeros(14)],np.r_[np.arange(6),np.zeros(14)],
                                 40,duration_ms=1000,rate=Fraction(8))
        self.assertEqual(result['indices'][0],40);self.assertEqual(result['indices'][-1],59)
    def test_general_cycle_selector_handles_unlisted_periodic_motion(self):
        frames=self.root/'cycle-frames';frames.mkdir()
        import math
        for i in range(72):
            phase=2*math.pi*(i%18)/18
            im=Image.new('RGBA',(48,48));d=ImageDraw.Draw(im)
            x=14+round(4*math.sin(phase))
            d.rectangle((x,10,x+12,35),fill=(round(140+60*math.cos(phase)),90,170,255))
            im.save(frames/f'frame_{i:04}.png')
        analysis=comfyui_forge_gait_loop.analyse(frames,24,kind='cycle',min_seconds=0.5,max_seconds=1)
        chosen=comfyui_forge_gait_loop.recommend(analysis,policy='cycle')
        self.assertEqual(chosen['policy'],'cycle')
        self.assertEqual(chosen['cycles'],1)
        self.assertGreater(chosen['window']['endExclusive'],chosen['window']['start'])

    def test_actual_batch_plan_accepts_arbitrary_labels_and_three_contracts(self):
        sys.path.insert(0,str(ROOT/'skills/comfyui-forge-generate2dsprite/scripts'))
        import comfyui_forge_master_still
        source=self.root/'source.png';Image.fromarray(self.art((0,255,0))).save(source)
        master,code=comfyui_forge_master_still.run(['approve','--still',str(source),'--name','subject','--subject','original subject',
                                    '--identity','original purple subject','--output-dir',str(self.root/'approved')])
        self.assertEqual(code,0)
        motions=self.root/'motions.json'
        motions.write_text(json.dumps([{'id':'label_'+str(i),'type':kind,'description':'motion defined for this request',
                                         'durationSeconds':1} for i,kind in enumerate(mc.TYPES)]))
        args=comfyui_forge_sprite_set.build_parser().parse_args(['plan','--spec',confirmed(self.root),'--master',master['metadata'],'--motions-file',str(motions),
                      '--fps','8','--output-dir',str(self.root/'planned')])
        result=comfyui_forge_sprite_set.cmd_plan(args);plan=json.loads(Path(result['plan']).read_text())
        self.assertEqual(len(plan['actions']),3)
        for entry,kind in zip(plan['actions'],mc.TYPES):
            self.assertEqual(entry['motionType'],kind)
            self.assertEqual(entry['returnsToRest'],kind=='oneshot-return')
            self.assertFalse(entry['hitTick'])
            self.assertFalse(entry['gates']['feet']['enabled'])
            self.assertEqual(entry['motion'],'motion defined for this request')
            if kind!='cycle':
                self.assertEqual(entry['timing']['durationMs'],1000)
                self.assertEqual(entry['timing']['keys'],{})

    def test_one_shot_batch_requires_candidate_before_any_retime_call(self):
        runner=SimpleNamespace(entries={'free':{'motionType':'oneshot-hold','kind':'oneshot','timing':
                     {'mode':'auto','durationMs':1000},'candidateRange':None}},root=self.root,
                     plan={'package':{'fps':8}})
        record={'stages':{'registered':{'dir':'registered','frames':36},'keyed':{'fps':'24'}},'qc':{'motion':{}}}
        runner.run_auto_oneshot=lambda *a: comfyui_forge_sprite_set.SetRunner.run_auto_oneshot(runner,*a)
        with patch.object(comfyui_forge_sprite_set,'run_tool',side_effect=AssertionError('must not run')):
            with self.assertRaisesRegex(ValueError,'candidateRange'):
                comfyui_forge_sprite_set.SetRunner.run_motion(runner,'free',record,self.root/'selected','',None)

if __name__=='__main__':unittest.main()
