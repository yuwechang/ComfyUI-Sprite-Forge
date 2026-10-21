"""Cross-stage failure regressions from the full project audit; offline only."""
import copy,json,sys,unittest
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
from PIL import Image,ImageDraw
import test_unified_pipeline as fixtures
import test_comfyui_media as media_fixture
import comfyui_forge_contracts as contracts
import comfyui_forge_animation_spec as specs
import comfyui_forge_sprite_set as batch
import comfyui_forge_retime as retime
import comfyui_forge_gait_loop as cycle
import comfyui_forge_finalize_animation as finalizer
import comfyui_forge_media as media
import comfyui_forge_frame_rules as rules
import comfyui_forge_finish_frames as finish

class ContractTests(unittest.TestCase):
    def test_aliases_must_agree_with_exact_values(self):
        final=specs.final_spec('32x32',1,8,'cycle')
        for field,value in [('durationSeconds',2),('fps',12)]:
            changed={**final,field:value}
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'disagrees'):contracts.final(changed)
        final.pop('fps');final.pop('durationSeconds')
        normalized=contracts.final(final)
        self.assertEqual(normalized['fps'],8);self.assertEqual(normalized['durationSeconds'],1)
        for confirmation in [1,'true',False]:
            with self.assertRaises(ValueError):contracts.confirmed({'confirmed':confirmation,'final':final})
    def test_source_contract_and_canvas_match_executor(self):
        valid={'size':[128,128],'requestedSeconds':2.25}
        self.assertEqual(contracts.source(valid)['frameCount'],56)
        for extra in [{'fps':12},{'frameCount':56.0},{'actualSeconds':2.25},{'size':[127,128]},{'cadence':{'multiple':16}}]:
            with self.subTest(extra=extra),self.assertRaises(ValueError):contracts.source({**valid,**extra})
        with self.assertRaises(ValueError):rules.validate_canvas({'planning':{'minimum_source_size':[128,128]}},96,64)
    def test_seed_respects_actual_socket_limits_and_single_value(self):
        graph=copy.deepcopy(media_fixture.GRAPH);config=media_fixture.CONFIG;targets=media.seed_targets(config,graph)
        info={'I2V':{'input':{'required':{'seed':['INT',{'min':4,'max':6}]}}}}
        bounds=media.seed_bounds(graph,targets,info)
        for _ in range(30):
            result,seed,_=media.randomize_seed(config,graph,bounds)
            self.assertTrue(4<=seed<=6);self.assertEqual(result['4']['inputs']['seed'],seed)
        self.assertEqual(media.randomize_seed(config,graph,(123,123))[1],123)
        graph['4']['inputs'].pop('seed')
        self.assertEqual(media.randomize_seed(config,graph)[1:],(None,[]))
    def test_binding_validation_rejects_disconnected_and_conflicting_inputs(self):
        config=copy.deepcopy(media_fixture.CONFIG);graph=copy.deepcopy(media_fixture.GRAPH)
        config['bindings']['prompt']=['1','image']
        with self.assertRaisesRegex(media.ComfyError,'conflicting'):media.prepare(config,graph,prompt='text',first='image.png',last=None,width=96,height=64,duration=1)
        config=copy.deepcopy(media_fixture.CONFIG);graph['98']={'class_type':'Text','inputs':{'text':'unused'}}
        config['bindings']['prompt']=['98','text']
        with self.assertRaisesRegex(media.ComfyError,'does not reach'):media.prepare(config,graph,prompt='text',first='image.png',last=None,width=96,height=64,duration=1)
        config['bindings']['prompt']=['98']
        with self.assertRaisesRegex(media.ComfyError,'binding'):media.load_graph(config)
    def test_pairwise_memory_budget_and_reduction_share_the_same_limit(self):
        with patch.dict('os.environ',{'COMFYUI_FORGE_ANALYSIS_MEMORY_MB':'1'}):
            factor=cycle._reduction_factor((512,512),80)
            self.assertLessEqual(80*((512+factor-1)//factor)**2*4,1024**2//4)
            with self.assertRaisesRegex(ValueError,'memory'):cycle.pairwise_l1(np.zeros((1000,1),np.float32))
        distances=cycle.pairwise_l1(np.array([[0,1],[2,4]],np.float32))
        self.assertEqual(distances.dtype,np.float32);self.assertEqual(float(distances[0,1]),5)
    def test_forward_finishing_policies(self):
        self.assertEqual(finish.LOOP_POLICIES,('cycle','oneshot'))
    def test_event_sources_outside_candidate_are_rejected(self):
        for source in [4,25]:
            with self.assertRaises(ValueError):retime.auto_oneshot(np.ones(20),np.linspace(0,1,20),5,duration_ms=1000,rate=Fraction(8),event_sources=[('signal',source)])
    def test_inherited_tick_events_keep_phase_and_exact_timeline(self):
        args=retime.build_parser().parse_args(['--frames-dir','unused','--fps','24','--selection','unused','--output-dir','unused'])
        selected={'raw':{'ticks':[1,3,2],'tickHz':24,'events':[{'name':'signal','tick':2}]},'durations':[42,125,83]}
        chosen={'selection':selected,'indices':[5,6,7],'weights':selected['durations']}
        timeline=retime.timing(args,'oneshot-hold',chosen,Fraction(24))
        self.assertEqual(timeline['ticks'],[1,3,2]);self.assertEqual(timeline['tick_hz'],24)
        timeline.update(selection=selected,indices=chosen['indices']);args.tick_hz=24
        self.assertEqual(next(e for e in retime.build_events(args,timeline) if e['name']=='signal')['tick'],2)
        args.duration=1000
        timeline=retime.timing(args,'oneshot-hold',chosen,Fraction(24));timeline.update(selection=selected,indices=chosen['indices'])
        self.assertEqual(next(e for e in retime.build_events(args,timeline) if e['name']=='signal')['atMs'],333)
    def test_source_provenance_rejects_different_retained_video(self):
        case=fixtures.UnifiedTests();case.setUp()
        try:
            processed=case.root/'processed';(processed/'frames').mkdir(parents=True)
            (processed/'pipeline-meta.json').write_text(json.dumps({'video':{'sha256':'wrong'}}))
            reg=case.root/'registration.json';reg.write_text(json.dumps({'video':{'frameDirectory':'processed/frames'}}))
            source=case.root/'clip.mp4';source.write_bytes(media_fixture.MP4)
            record={'source':{'registration':{'path':'registration.json','sha256':finalizer.digest(reg)}}}
            with self.assertRaisesRegex(ValueError,'retained MP4'):finalizer.source_provenance(record,case.root,source)
        finally:case.tearDown()

class MotionMatrixTests(unittest.TestCase):
    def test_all_three_motion_contracts_in_both_finishes_through_delivery(self):
        for motion_type in ('cycle','oneshot-return','oneshot-hold'):
            for style in ('hd','pixel'):
                with self.subTest(motion_type=motion_type,finish=style):
                    case=fixtures.UnifiedTests();case.setUp();case.motion_type=motion_type;case.finish=style
                    try:case.test_real_offline_batch_to_standard_zip_without_any_network()
                    finally:case.tearDown()

class BatchIntegrityTests(unittest.TestCase):
    def setUp(self):self.case=fixtures.UnifiedTests();self.case.setUp()
    def tearDown(self):self.case.tearDown()
    def test_frozen_preparation_and_cached_stage_cannot_be_silently_reused(self):
        plan=self.case.make_plan();runner=batch.SetRunner(plan);runner.ensure_job('arbitrary')
        folder=runner.root/runner.astate('arbitrary')['job']['dir'];job=folder/'registration_job.json'
        old=job.read_bytes();data=json.loads(old);data['key']='blue';job.write_text(json.dumps(data))
        with self.assertRaises(ValueError):runner.ensure_job('arbitrary')
        job.write_bytes(old);runner.ensure_job('arbitrary')
        image=folder/'input.png';image.write_bytes(b'changed')
        with self.assertRaises(ValueError):runner.ensure_job('arbitrary')
        record=runner.open_take('arbitrary')
        def make(out):out.mkdir();(out/'frame.png').write_bytes(b'original');return {}
        runner.stage(record,'keyed',make)
        (runner.root/record['dir']/'keyed/frame.png').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'rebuild'):runner.stage(record,'keyed',make)
    def test_output_and_review_tampering_is_detected_and_local_rebuild_reuses_video(self):
        self.case.test_real_offline_batch_to_standard_zip_without_any_network()
        plan=self.case.root/'set/set_plan.json';runner=batch.SetRunner(plan);st=runner.astate('arbitrary')
        output=runner.root/st['output']['package'];(output/'animation.zip').write_bytes(b'changed')
        with patch.object(media,'execute',side_effect=AssertionError('must not generate')):
            runner.run();self.assertEqual(st['status'],'blocked');self.assertIn('changed',st['message'])
            batch.cmd_rebuild(SimpleNamespace(plan=str(plan),action='arbitrary',take=1,from_stage='finished'))
            runner=batch.SetRunner(plan);runner.run();self.assertEqual(runner.astate('arbitrary')['status'],'needs-review')
            record=runner.take('arbitrary',1);work=runner.root/record['stages']['final-review']['dir']
            receipt=json.loads((work/'review.json').read_text());self.assertEqual(receipt['sourceProvenance']['status'],'verified')
            (work/'preview.gif').write_bytes(b'changed preview')
            with self.assertRaisesRegex(ValueError,'preview'):finalizer.approve(work,runner.root/'new-output','Reviewed')
            self.assertEqual(len(runner.astate('arbitrary')['takes']),1)

if __name__=='__main__':unittest.main()
