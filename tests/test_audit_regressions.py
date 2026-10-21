import json,sys
from pathlib import Path
from fractions import Fraction
from types import SimpleNamespace
from unittest.mock import patch
import unittest
import numpy as np
import test_unified_pipeline as fixtures
import comfyui_forge_sprite_set as batch
import comfyui_forge_retime as retime
import comfyui_forge_motion_contract as motion
import comfyui_forge_finalize_animation as finalizer
import comfyui_forge_gait_loop as cycle

class AuditTests(unittest.TestCase):
    def test_arbitrary_event_labels_agree_and_are_preserved(self):
        for name in ('marker','phase-2','signal.ready','custom:existing'):
            motion.validate_timing({},[{'name':name,'source':5}])
            self.assertEqual(retime.parse_event_source(name+'=5'),(name,5))
            self.assertEqual(retime.parse_event(name+'@125',False)['name'],name)
            result=retime.auto_oneshot(np.ones(20),np.linspace(0,1,20),0,duration_ms=1000,rate=Fraction(8),event_sources=[(name,5)])
            self.assertIn(name,[e['name'] for e in result['events']])
        with self.assertRaises(ValueError):motion.validate_timing({},[{'name':'bad name','source':5}])
    def test_impossible_key_phase_is_not_silently_shifted(self):
        with self.assertRaisesRegex(ValueError,'without moving'):
            retime.auto_oneshot(np.ones(20),np.linspace(0,1,20),0,duration_ms=1000,rate=Fraction(8),keys=[{'name':'marker','source':10,'at':.95,'holdMs':0}])
    def test_source_timing_keeps_arbitrary_events_on_exact_source_pose(self):
        from PIL import Image,ImageDraw
        case=fixtures.UnifiedTests();case.setUp()
        try:
            frames=case.root/'frames';frames.mkdir()
            for n in range(12):
                im=Image.new('RGBA',(32,32));ImageDraw.Draw(im).rectangle((8+n//3,8,20,25),fill=(80+n*8,120,180,255));im.save(frames/f'{n:03}.png')
            out=case.root/'timed'
            args=retime.build_parser().parse_args(['--frames-dir',str(frames),'--fps','24','--kind','oneshot-hold','--range','0:12','--event-source','signal-ready=5','--output-dir',str(out)])
            retime.retime(args)
            data=cycle.read_selection(out/'selection.json')
            event=next(e for e in data['raw']['events'] if e['name']=='signal-ready')
            self.assertEqual(data['indices'][event['frame']],5)
        finally:case.tearDown()

    def test_run_honors_reviewed_older_take_without_generating(self):
        runner=batch.SetRunner.__new__(batch.SetRunner)
        chosen={'take':1,'clip':{'path':'already-verified'}}
        state={'status':'selected','selectedTake':1,'round':2,'takes':[chosen,{'take':2,'round':2}]}
        runner.entries={'probe':{}};runner.check_masters=lambda:None;runner.order=lambda only:['probe'];runner.astate=lambda ident:state
        runner.ensure_job=lambda ident:None;runner.take=lambda ident,n:chosen if n==1 else None
        runner.open_take=lambda ident:self.fail('must not open a new take')
        runner.generate=lambda *a:self.fail('must not submit')
        seen=[];runner.evaluate=lambda ident,rec:seen.append(rec['take']);runner.post_process=lambda ident:None
        runner.summary=lambda order,generated:generated
        self.assertEqual(runner.run(),0);self.assertEqual(seen,[1])

    def test_plan_mutation_is_refused_before_reusing_work(self):
        case=fixtures.UnifiedTests();case.setUp()
        try:
            plan=case.make_plan();runner=batch.SetRunner(plan);runner.save()
            data=json.loads(plan.read_text());data['generation']['duration']=4.25;plan.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError,'plan changed'):batch.SetRunner(plan)
        finally:case.tearDown()
    def test_qc_failures_survive_selection_for_review(self):
        runner=batch.SetRunner.__new__(batch.SetRunner);state={};record={'take':1}
        runner.verify_clip=lambda rec:None;runner.astate=lambda ident:state;runner.stage=lambda *a:{}
        def qc(ident,rec):rec['qc']={'status':'fail','failures':['identity'],'reasons':['changed identity']}
        runner.run_qc=qc;runner.log_take=lambda *a:None;runner.save=lambda:None
        runner.evaluate('probe',record)
        self.assertEqual(record['failures'],['identity']);self.assertEqual(record['status'],'needs-review')
    def test_only_generic_forward_cycle_is_exposed(self):
        self.assertIsNotNone(cycle.build_parser());self.assertEqual(cycle.KINDS,('cycle',));self.assertNotIn('pingpong',cycle.LOOP_POLICIES)
        fake=SimpleNamespace()
        with patch.object(cycle,'search_ambient',return_value=[]):
            with self.assertRaisesRegex(ValueError,'inspect the source'):cycle.recommend(fake)
    def test_reselection_timing_revision_and_interrupted_delivery_recover(self):
        case=fixtures.UnifiedTests();case.setUp()
        try:
            case.test_real_offline_batch_to_standard_zip_without_any_network()
            plan=case.root/'set/set_plan.json';runner=batch.SetRunner(plan);old_output=runner.astate('arbitrary')['output']['package']
            timing=case.root/'timing.json';timing.write_text(json.dumps({'keys':{'focus':{'source':5,'at':.4,'holdMs':0}},'events':[{'name':'signal-ready','source':5}]}))
            batch.cmd_select(SimpleNamespace(plan=str(plan),action='arbitrary',take=1,range='0:12',timing_file=str(timing)))
            runner=batch.SetRunner(plan)
            with patch('comfyui_forge_media.execute',side_effect=AssertionError('no new GPU job')):
                runner.run();self.assertEqual(runner.astate('arbitrary')['status'],'needs-review')
                review=runner.root/runner.take('arbitrary',1)['stages']['final-review']['dir']/'review.json'
                document=json.loads(review.read_text());self.assertIn('qualityChecks',document)
                self.assertIn('signal-ready',[e['name'] for e in document['timing']['events']])
                batch.cmd_accept(SimpleNamespace(plan=str(plan),action='arbitrary',take=1,note='Reviewed revised timing and QC.'))
                runner=batch.SetRunner(plan);original=finalizer.deliver
                def lost_ack(*a,**kw):original(*a,**kw);raise OSError('simulated exit after delivery publication')
                with patch.object(finalizer,'deliver',side_effect=lost_ack):runner.run()
                self.assertEqual(runner.astate('arbitrary')['status'],'blocked')
                (review.parent/'review.json.tmp').write_text('interrupted legacy metadata write')
                runner=batch.SetRunner(plan);runner.run();self.assertEqual(runner.astate('arbitrary')['status'],'done',runner.astate('arbitrary').get('message'))
                self.assertTrue((runner.root/old_output/'animation.zip').is_file())
                # Recovered delivery is verified, not accepted merely because its folder exists.
                output=runner.root/runner.astate('arbitrary')['output']['package'];(output/'animation.zip').write_bytes(b'changed')
                work=runner.root/runner.take('arbitrary',1)['stages']['final-review']['dir']
                with self.assertRaisesRegex(ValueError,'contents changed'):finalizer.approve(work,output,'Verify changed delivery')
                self.assertEqual(len(runner.astate('arbitrary')['takes']),1)
        finally:case.tearDown()

if __name__=='__main__':unittest.main()
