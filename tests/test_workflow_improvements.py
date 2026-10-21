import argparse
import copy
from fractions import Fraction
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import numpy as np
from PIL import Image, ImageDraw

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'skills/comfyui-forge-video2dsprite/scripts'))
sys.path.insert(0,str(ROOT/'skills/comfyui-forge-generate2dmedia/scripts'))
import comfyui_forge_prepare_i2v_input as prep
import comfyui_forge_register_clip as reg
import comfyui_forge_gait_loop
import comfyui_forge_core
import comfyui_forge_animation_spec
import comfyui_forge_finalize_animation as finalizer
import comfyui_forge_doctor
import comfyui_forge_media
from comfyui_forge_selection_tools import sample_indices, playback_plan


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)

    def tearDown(self):self.temp.cleanup()

    def artwork(self, alpha=255):
        image=Image.new('RGBA',(64,64),(0,255,0,alpha))
        ImageDraw.Draw(image).rectangle((22,12,42,54),fill=(240,160,30,255))
        return np.asarray(image)

    def test_near_opaque_green_background_is_not_a_cutout(self):
        self.assertTrue(prep.needs_background_keying(self.artwork(250),'green'))
        self.assertTrue(prep.needs_background_keying(self.artwork(255),'auto'))

    def test_true_transparency_and_translucent_background_are_preserved(self):
        self.assertFalse(prep.needs_background_keying(self.artwork(0),'green'))
        self.assertFalse(prep.needs_background_keying(self.artwork(128),'green'))

    def test_near_opaque_non_key_background_is_not_blindly_discarded(self):
        pixels=self.artwork(250).copy();pixels[:12,:,:3]=[80,80,80]
        pixels[54:,:,:3]=[120,120,120];pixels[:,:22,:3]=[130,90,70]
        self.assertFalse(prep.needs_background_keying(pixels,'auto'))

    def test_prepare_keys_alpha250_and_records_candidate_slots(self):
        source=self.root/'source.png';Image.fromarray(self.artwork(250)).save(source)
        args=prep.build_parser().parse_args(['prepare','--master',str(source),'--motion-type','cycle','--description','requested continuous motion',
                    '--master-key','green','--key','auto','--canvas','128,128','--duration','3.25',
                    '--output-dir',str(self.root/'input')])
        result=prep.cmd_prepare(args)
        doc=json.loads(Path(result['metadata']).read_text())
        self.assertEqual(doc['masterKeying']['originalAlphaRange'],[250,255])
        self.assertEqual(Image.open(self.root/'input/master.png').getchannel('A').getextrema()[0],0)
        self.assertEqual(doc['candidateCount'],3)
        self.assertTrue(any(doc['padding']))
        self.assertEqual(doc['promptMode'],'candidate-template')
        self.assertEqual({row['candidate'] for row in doc['timeline']},{1,2,3})

    def test_custom_prompt_does_not_claim_default_timeline_or_return_pose(self):
        source=self.root/'source.png';Image.fromarray(self.artwork()).save(source)
        prompt=self.root/'custom.txt';prompt.write_text('custom supplied motion',encoding='utf-8')
        args=prep.build_parser().parse_args(['prepare','--master',str(source),'--motion-type','cycle','--description','requested continuous motion',
                    '--master-key','green','--canvas','128,128','--duration','3',
                    '--prompt-file',str(prompt),'--output-dir',str(self.root/'custom')])
        result=prep.cmd_prepare(args);doc=json.loads(Path(result['metadata']).read_text())
        self.assertEqual(doc['timeline'],[]);self.assertFalse(doc['returnsToRest'])
        self.assertFalse(doc['candidateTimingPlanned'])
        self.assertEqual(doc['prompt']['sha256'],comfyui_forge_core.sha256_file(self.root/'custom/prompt.txt'))
        self.assertFalse(reg.load_job(Path(result['metadata'])).returns_to_rest)

    def test_run_candidates_are_continuous_and_final_playback_is_separate(self):
        rows=prep.timeline(prep.motion_template('cycle','requested continuous motion'),3.25,3)
        self.assertEqual(len(rows),3)
        self.assertEqual(rows[-1]['endS'],3.25)
        self.assertTrue(all(row['role']=='candidate' for row in rows))
        self.assertTrue(all('no stop' in row['text'] for row in rows))

    def test_terminal_action_has_independent_candidates_and_no_reset_after_last(self):
        rows=prep.timeline(prep.motion_template('oneshot-hold','requested terminal motion'),3,3)
        self.assertEqual(sum(row['role']=='reset' for row in rows),2)
        self.assertEqual(rows[-1]['role'],'candidate')
        self.assertIn('terminal pose',rows[-1]['text'])
        self.assertFalse(prep.motion_template('oneshot-hold','requested terminal motion').returns_to_rest)
        self.assertEqual({row['candidate'] for row in rows if row['role']=='candidate'},{1,2,3})

    def test_key_preflight_compares_without_modifying_art(self):
        pixels=self.artwork(0);before=pixels.copy()
        report=prep.key_preflight(pixels,'auto')
        self.assertGreater(len(report['options']),3)
        self.assertIsNotNone(report['recommended'])
        np.testing.assert_array_equal(pixels,before)

    def test_canvas_overflow_retries_once_without_scaling_or_gpu(self):
        path=self.root/'registration.json';path.write_text('{}')
        error=reg.RegistrationQAError('overflow',[{'id':'canvas-overflow','status':'fail','value':{'neededPadding':[0,61,0,0]}}],[0,0,0,0])
        args=argparse.Namespace(action_padding=None,auto_padding=True)
        with patch.object(reg,'_cmd_apply_once',side_effect=[error,{'metadata':str(path)}]) as apply:
            result=reg.cmd_apply(args)
        self.assertEqual(apply.call_count,2)
        self.assertEqual(apply.call_args.args[0].action_padding,(0,61,0,0))
        self.assertIsNone(args.action_padding)
        self.assertEqual(result['automaticPadding']['added'],[0,61,0,0])

    def test_source_clipping_and_other_failures_never_auto_repair(self):
        for problem in ('video-edge-touch','rest-scale-error'):
            error=reg.RegistrationQAError('clipped',[{'id':problem,'status':'fail'}])
            with patch.object(reg,'_cmd_apply_once',side_effect=error) as apply,self.assertRaises(reg.RegistrationQAError):
                reg.cmd_apply(argparse.Namespace(auto_padding=True))
            self.assertEqual(apply.call_count,1)

    def test_auto_padding_is_bounded_and_can_be_disabled(self):
        error=reg.RegistrationQAError('overflow',[{'id':'canvas-overflow','status':'fail','value':{'neededPadding':[1,1,1,1]}}])
        with patch.object(reg,'_cmd_apply_once',side_effect=error) as apply,self.assertRaises(reg.RegistrationQAError):
            reg.cmd_apply(argparse.Namespace(auto_padding=True))
        self.assertEqual(apply.call_count,2)
        with patch.object(reg,'_cmd_apply_once',side_effect=error) as apply,self.assertRaises(reg.RegistrationQAError):
            reg.cmd_apply(argparse.Namespace(auto_padding=False))
        self.assertEqual(apply.call_count,1)

    def test_sample_preserves_oneshot_endpoints_and_important_pose(self):
        result=sample_indices(list(range(20,50)),8,'oneshot',[34])
        self.assertEqual((result[0],result[-1]),(20,49));self.assertIn(34,result)
        self.assertEqual(len(result),8)

    def test_reversed_duplicate_or_insufficient_candidate_is_refused(self):
        for indices in ([1,2,1],[1,1,2],[3,2,1],[1,2]):
            with self.assertRaises(ValueError):sample_indices(indices,8)

    def fixture(self):
        original=self.root/'registered/frames';original.mkdir(parents=True)
        finished=self.root/'finished';(finished/'frames').mkdir(parents=True)
        records=[]
        for i in range(12):
            im=Image.new('RGBA',(32,32));ImageDraw.Draw(im).rectangle((8,8,22,26),fill=(40+i*10,120,180,255))
            name=f'frame_{i:06}.png';im.save(original/name);im.save(finished/'frames'/name)
            sha=comfyui_forge_core.sha256_file(original/name)
            records.append({'file':'frames/'+name,'sha256':sha,'sourceFile':name,'sourceSha256':sha})
        (finished/'finish.json').write_text(json.dumps({'source':{'frames':'../registered/frames'},'frames':records}))
        selection=self.root/'selection.json'
        clip=comfyui_forge_gait_loop.load_clip(original,Fraction(24))
        selection.write_text(json.dumps(comfyui_forge_gait_loop.build_selection(clip,self.root,list(range(12)),[42]*12,
                                       policy='cycle',method='offline candidate',review='inspect',window=(0,12))))
        spec=self.root/'spec.json';spec.write_text(json.dumps({'confirmed':True,'final':comfyui_forge_animation_spec.final_spec('32x32',1,8,'loop')}))
        source=self.root/'source.mp4';source.write_bytes(b'test-source')
        return finished,selection,spec,source

    def test_finalization_reviews_exact_final_frames_then_delivers(self):
        args=self.fixture();work=self.root/'review'
        result=finalizer.prepare(*args,work)
        self.assertEqual(result['status'],'needs-visual-review')
        self.assertEqual(len(result['sourceIndices']),8)
        self.assertIsNotNone(result['finalSeam'])
        self.assertFalse((self.root/'delivery').exists())
        delivered=finalizer.approve(work,self.root/'delivery','Inspected both steps, light/dark edges and seam.')
        self.assertEqual(delivered['frameCount'],8)
        self.assertEqual(json.loads((work/'review.json').read_text())['status'],'approved')

    def test_finalization_refuses_changed_source_finish_or_reviewed_output(self):
        args=self.fixture();finished,selection,spec,source=args
        file=finished/'frames/frame_000002.png';file.write_bytes(b'changed')
        with self.assertRaises(ValueError):finalizer.prepare(*args,self.root/'bad')
        self.assertFalse((self.root/'bad').exists())

    def test_approval_requires_note_and_unchanged_frames(self):
        args=self.fixture();work=self.root/'review';finalizer.prepare(*args,work)
        with self.assertRaises(ValueError):finalizer.approve(work,self.root/'delivery','')
        (work/'frames/frame_0000.png').write_bytes(b'changed')
        with self.assertRaises(ValueError):finalizer.approve(work,self.root/'delivery','Reviewed')
        self.assertFalse((self.root/'delivery').exists())

    def test_finalization_preserves_oneshot_terminal_frame(self):
        finished,selection,spec,source=self.fixture()
        document=json.loads(selection.read_text());document['loopPolicy']='oneshot';selection.write_text(json.dumps(document))
        spec.write_text(json.dumps({'confirmed':True,'final':comfyui_forge_animation_spec.final_spec('32x32',1,8,'oneshot')}))
        result=finalizer.prepare(finished,selection,spec,source,self.root/'review')
        self.assertEqual(result['sourceIndices'][0],0)
        self.assertEqual(result['sourceIndices'][-1],11)
        self.assertIsNone(result['finalSeam'])

    def attack_selection(self):
        return {'indices':[20,21,23,24,28,29], 'durations':[100,100,400,100,200,100],
                'start':20,'endExclusive':30,'policy':'oneshot',
                'raw':{'method':'retime --auto-oneshot', 'ticks':[1,1,4,1,2,1], 'tickHz':10,
                       'events':[{'name':'in','tick':0},{'name':'hit','tick':2},{'name':'end','tick':10}]}}

    def test_attack_timeline_preserves_hit_hold_and_candidate(self):
        plan=playback_plan(self.attack_selection(),8,'oneshot')
        self.assertEqual(len(plan['sourceIndices']),8)
        self.assertEqual((plan['sourceIndices'][0],plan['sourceIndices'][-1]),(20,29))
        self.assertGreaterEqual(plan['sourceIndices'].count(23),3)
        hit=plan['events'][1]
        self.assertEqual(plan['sourceIndices'][hit['outputFrame']],23)
        self.assertEqual(plan['events'][-1]['outputFrame'],8)
        self.assertTrue(all(20<=i<30 for i in plan['sourceIndices']))

    def test_original_auto_oneshot_timing_survives_same_rate_finalization(self):
        import comfyui_forge_retime
        steps=np.ones(20)*0.1;steps[0]=0
        result=comfyui_forge_retime.auto_oneshot(steps,np.linspace(0,1,20),20,duration_ms=1000,rate=Fraction(8),
                                 keys=[{'name':'hit','source':27,'at':0.375,'holdMs':250}])
        durations,_=comfyui_forge_retime.tick_durations(result['ticks'],result['hz'])
        selection={'indices':result['indices'],'durations':durations,'start':20,'endExclusive':40,
                   'raw':{'ticks':result['ticks'],'tickHz':result['hz'],'events':result['events'],'auto':result['info']}}
        plan=playback_plan(selection,8,'oneshot')
        expected=[i for i,t in zip(result['indices'],result['ticks']) for _ in range(t//(result['hz']//8))]
        self.assertEqual(plan['sourceIndices'],expected)
        hit=next(e for e in plan['events'] if e['name']=='hit')
        self.assertEqual(plan['sourceIndices'][hit['outputFrame']],27)

    def test_nonattack_has_no_invented_hit_or_hold_rule(self):
        selection=self.attack_selection();selection['raw']={'events':[]}
        plan=playback_plan(selection,8,'oneshot')
        self.assertEqual(plan['events'],[])
        selection['durations']=[100]*6
        selection['indices']=list(range(20,32,2));selection['endExclusive']=32;selection['policy']='cycle'
        plan=playback_plan(selection,4,'loop')
        self.assertEqual(plan['method'],'cycle-phase')
        self.assertEqual(len(set(plan['sourceIndices'])),4)

    def test_event_overflow_and_bad_timing_fail_without_dropping_keys(self):
        selection=self.attack_selection()
        with self.assertRaisesRegex(ValueError,'exceed'):playback_plan(selection,2,'oneshot')
        selection['raw']['events'][1]['tick']=11
        with self.assertRaisesRegex(ValueError,'outside'):playback_plan(selection,8,'oneshot')

    def test_authored_cycle_and_ms_events_inherit_timing(self):
        selection=self.attack_selection();selection['raw'].pop('ticks');selection['raw'].pop('tickHz')
        selection['raw']['events']=[{'name':'custom:turn','atMs':200}];selection['policy']='cycle'
        plan=playback_plan(selection,8,'loop')
        self.assertEqual(plan['method'],'retime-duration-quantization')
        self.assertEqual(plan['sourceIndices'][plan['events'][0]['outputFrame']],23)
        self.assertGreaterEqual(plan['sourceIndices'].count(23),3)

    def test_finalizer_inherits_real_retime_events_holds_and_delivers(self):
        finished,selection,spec,source=self.fixture()
        document=json.loads(selection.read_text())
        document.update(sourceIndices=[0,2,3,6,9,11],durations_ms=[100,100,400,100,200,100],
                        ticks=[1,1,4,1,2,1],tickHz=10,loopPolicy='oneshot',
                        method='retime --auto-oneshot',events=[{'name':'hit','tick':2}, {'name':'end','tick':10}])
        selection.write_text(json.dumps(document))
        spec.write_text(json.dumps({'confirmed':True,'final':comfyui_forge_animation_spec.final_spec('32x32',1,8,'oneshot')}))
        result=finalizer.prepare(finished,selection,spec,source,self.root/'review')
        self.assertGreaterEqual(result['sourceIndices'].count(3),3)
        hit=result['timing']['events'][0]
        self.assertEqual(hit['atMs'],hit['outputFrame']*125)
        self.assertEqual(result['sourceIndices'][hit['outputFrame']],3)
        delivered=finalizer.approve(self.root/'review',self.root/'delivery','Reviewed impact hold and recovery.')
        self.assertEqual(delivered['frameCount'],8)
        self.assertEqual(delivered['gifDurationMs'],1000)


    def test_submission_rejects_prompt_changed_since_preparation(self):
        from test_comfyui_media import GRAPH, CONFIG, FakeClient
        reference=self.root/'input.png';Image.fromarray(self.artwork()).save(reference)
        prompt=self.root/'prompt.txt';prompt.write_text('changed motion')
        preparation=self.root/'registration_job.json'
        preparation.write_text(json.dumps({'input':{'path':'input.png','sha256':comfyui_forge_core.sha256_file(reference)},
                                          'prompt':{'path':'prompt.txt','sha256':'0'*64}}))
        args=SimpleNamespace(reference=str(reference),prompt_file=str(prompt),preparation=str(preparation),
                             out_dir=str(self.root/'submission'),timeout=1,last_frame=None,duration=3,dry_run=False)
        client=FakeClient()
        with patch.object(comfyui_forge_media,'load_config',return_value=CONFIG),patch.object(comfyui_forge_media,'load_graph',return_value=GRAPH),self.assertRaisesRegex(comfyui_forge_media.ComfyError,'prepared prompt'):
            comfyui_forge_media.execute(args,client)
        self.assertEqual(client.calls,[])
        self.assertFalse((self.root/'submission').exists())

    def test_offline_doctor_never_calls_the_service(self):
        with patch.object(sys,'argv',['forge_doctor','--offline']),patch.object(comfyui_forge_media,'check',side_effect=AssertionError('network')):
            self.assertEqual(comfyui_forge_doctor.main(),0)
        identity=comfyui_forge_doctor.runtime_identity()
        self.assertEqual(len(identity['adapterSha256']),64)
        self.assertIn('adapterPath',identity)


if __name__=='__main__':unittest.main()
