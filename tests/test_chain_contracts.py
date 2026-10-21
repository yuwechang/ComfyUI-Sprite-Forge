import json,sys,unittest,copy
from unittest.mock import patch
from PIL import Image
import numpy as np
from pathlib import Path
from fractions import Fraction
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'skills/comfyui-forge-video2dsprite/scripts'),str(ROOT/'skills/comfyui-forge-generate2dmedia/scripts')]
import test_workflow_improvements as fixtures
import comfyui_forge_retime as retime
import comfyui_forge_animation_spec as spec
import comfyui_forge_finalize_animation as finalizer
import contract_schema as schema
import comfyui_forge_gait_loop as cycle
import comfyui_forge_media as media
import comfyui_forge_route_media as router
import test_comfyui_media as media_fixture

class ChainTests(unittest.TestCase):
    def test_real_retime_selection_reaches_standard_delivery_and_schema(self):
        for kind in ('oneshot-return','oneshot-hold'):
            with self.subTest(kind=kind):
                case=fixtures.WorkflowTests();case.setUp()
                try:
                    finished,_,specfile,source=case.fixture();frames=case.root/'registered/frames'
                    out=case.root/'retimed'
                    args=retime.build_parser().parse_args(['--frames-dir',str(frames),'--fps','24','--kind',kind,
                        '--range','0:12','--auto-oneshot','--duration-ms','1000','--output-fps','8',
                        '--key','marker=5@0.5','--event-source','signal.ready=5','--output-dir',str(out)])
                    retime.retime(args);selection=out/'selection.json'
                    specfile.write_text(json.dumps({'confirmed':True,'final':spec.final_spec('32x32',1,8,kind)}))
                    review=finalizer.prepare(finished,selection,specfile,source,case.root/'review')
                    self.assertEqual(len(review['sourceIndices']),8)
                    self.assertIn('signal.ready',[e['name'] for e in review['timing']['events']])
                    finalizer.approve(case.root/'review',case.root/'delivery','Verified complete serialized test chain')
                    schemas=schema.SchemaSet(ROOT/'tests/schemas')
                    document=json.loads(selection.read_text());self.assertEqual(schemas.errors(document,'video.schema.json#/$defs/frame_selection_v2'),[])
                finally:case.tearDown()

    def test_continuous_cycle_selection_reaches_standard_delivery_without_authored_rhythm(self):
        import math,hashlib
        from PIL import ImageDraw
        case=fixtures.WorkflowTests();case.setUp()
        try:
            frames=case.root/'cycle-source';frames.mkdir();finished=case.root/'cycle-finished';(finished/'frames').mkdir(parents=True)
            records=[]
            for i in range(73):
                phase=2*math.pi*i/24;x=10+round(3*math.sin(phase));y=10+round(2*math.cos(phase))
                image=Image.new('RGBA',(32,32));ImageDraw.Draw(image).rectangle((x,y,x+9,y+12),fill=(200+round(20*math.sin(phase)),70+round(20*math.cos(phase)),30,255))
                name=f'{i:03}.png';image.save(frames/name);image.save(finished/'frames'/name)
                digest=hashlib.sha256((frames/name).read_bytes()).hexdigest()
                records.append({'file':'frames/'+name,'sha256':digest,'sourceFile':name,'sourceSha256':digest})
            (finished/'finish.json').write_text(json.dumps({'source':{'frames':'../cycle-source'},'frames':records}))
            source=case.root/'source.mp4';source.write_bytes(b'synthetic fixture source')
            specfile=case.root/'spec.json';specfile.write_text(json.dumps({'confirmed':True,'final':spec.final_spec('32x32',1,8,'cycle')}))
            selected=case.root/'selected'
            args=cycle.build_parser().parse_args(['select','--frames-dir',str(frames),'--fps','24','--kind','cycle',
                  '--policy','cycle','--min-seconds','1','--max-seconds','1','--output-dir',str(selected)])
            cycle.cmd_select(args);selection=selected/'selection.json'
            reviewed=json.loads(selection.read_text())
            self.assertEqual(reviewed['loopPolicy'],'cycle')
            self.assertEqual(reviewed['sourceIndices'],sorted(set(reviewed['sourceIndices'])))
            review=finalizer.prepare(finished,selection,specfile,source,case.root/'review')
            self.assertEqual(review['timing']['method'],'cycle-phase');self.assertEqual(review['timing']['events'],[])
            finalizer.approve(case.root/'review',case.root/'delivery','Reviewed synthetic forward cycle')
        finally:case.tearDown()

    def test_bad_clock_or_motion_metadata_is_refused_by_standard_delivery(self):
        for changed in [{'ticks':[1]*12,'tickHz':24}, {'motionType':'cycle','kind':'oneshot-hold'}, {'status':'rejected'}]:
            with self.subTest(changed=changed):
                case=fixtures.WorkflowTests();case.setUp()
                try:
                    finished,selection,specfile,source=case.fixture()
                    document=json.loads(selection.read_text());document.update(changed);selection.write_text(json.dumps(document))
                    frames=case.root/'registered/frames'
                    with self.assertRaises(ValueError):finalizer.prepare(finished,selection,specfile,source,case.root/'review')
                finally:case.tearDown()

class WorkflowChainTests(unittest.TestCase):
    setUp=media_fixture.ComfyTests.setUp
    tearDown=media_fixture.ComfyTests.tearDown
    def test_canvas_and_bindings_survive_resolve_post_receipt_and_resume(self):
        config=copy.deepcopy(media_fixture.CONFIG);config['planning']={'dimension_multiple':64,'minimum_source_size':[128,128]}
        (self.root/'config.json').write_text(json.dumps(config));Image.new('RGB',(128,128),'green').save(self.root/'input.png')
        self.args.duration=2.25;self.args.last_frame=self.args.reference
        resolved=router.resolve('video',wanted=router.Wanted(last_frame=True,duration=2.25))
        self.assertEqual(resolved.candidates[0].duration,56/24)
        client=media_fixture.FakeClient();result=media.execute(self.args,client)
        body=json.loads(next(body for method,path,body in client.calls if method=='POST' and path=='/prompt'))['prompt']
        self.assertEqual((body['4']['inputs']['width'],body['4']['inputs']['height'],body['4']['inputs']['length']),(128,128,56))
        self.assertEqual(body['5']['inputs']['fps'],24)
        receipt=json.loads((Path(self.args.out_dir)/'job.json').read_text())
        self.assertEqual((receipt['durationRequested'],receipt['frameCount'],receipt['durationUsed']),(2.25,56,56/24))
        with patch.object(client,'call',side_effect=AssertionError('done resume must not contact server')):
            resumed=media.resume(self.args.out_dir,client=client)
        self.assertEqual(resumed['sha256'],result['sha256'])
    def test_invalid_bindings_stop_before_upload_post_or_creating_a_job(self):
        for role,target,last in [('fps',['4','width'],False),('last_image',['1','image'],True),('width',['4','seed'],False)]:
            with self.subTest(role=role,target=target):
                config=copy.deepcopy(media_fixture.CONFIG);config['bindings'][role]=target
                (self.root/'config.json').write_text(json.dumps(config));self.args.last_frame=self.args.reference if last else None
                client=media_fixture.FakeClient()
                with self.assertRaises(media.ComfyError):media.execute(self.args,client)
                self.assertEqual(client.calls,[]);self.assertEqual(client.uploads,[]);self.assertFalse(Path(self.args.out_dir).exists())

if __name__=='__main__':unittest.main()
