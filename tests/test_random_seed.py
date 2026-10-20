"""Randomize only a fresh submission, and freeze its seed for all resume paths."""
import copy,json,unittest
from pathlib import Path
from unittest.mock import patch
import test_comfyui_media as fixture
comfy=fixture.comfy

class SeedTests(unittest.TestCase):
    setUp=fixture.ComfyTests.setUp
    tearDown=fixture.ComfyTests.tearDown
    def test_each_new_job_posts_its_recorded_random_seed(self):
        with patch.object(comfy.secrets,'randbelow',side_effect=[1001,1002]):
            for n in range(2):
                self.args.out_dir=str(self.root/f'job-{n}')
                client=fixture.FakeClient();result=comfy.execute(self.args,client)
                job=json.loads((Path(self.args.out_dir)/'job.json').read_text())
                payload=json.loads(next(body for _,path,body in client.calls if path=='/prompt'))
                self.assertEqual(job['seed'],1001+n);self.assertEqual(payload['prompt']['4']['inputs']['seed'],job['seed'])
                self.assertEqual(result['seed'],job['seed']);self.assertIs(type(job['seed']),int)
        self.assertEqual(fixture.GRAPH['4']['inputs']['seed'],123)
    def test_done_and_pending_resume_do_not_randomize_or_post(self):
        result=comfy.execute(self.args,fixture.FakeClient());folder=Path(self.args.out_dir)
        with patch.object(comfy.secrets,'randbelow',side_effect=AssertionError('must retain seed')):
            self.assertEqual(comfy.resume(folder)['seed'],result['seed'])
            job=json.loads((folder/'job.json').read_text());job['status']='pending';(folder/'job.json').write_text(json.dumps(job))
            client=fixture.FakeClient();resumed=comfy.resume(folder,client=client)
            self.assertEqual(resumed['seed'],result['seed']);self.assertFalse(any(path=='/prompt' for _,path,_ in client.calls))
    def test_dry_run_does_not_create_a_job(self):
        self.args.dry_run=True
        with patch.object(comfy.secrets,'randbelow',side_effect=AssertionError('dry run')):
            result=comfy.execute(self.args,fixture.FakeClient());self.assertEqual(result['seedPolicy'],'random-per-new-job')
        self.assertFalse(Path(self.args.out_dir).exists())
    def test_workflow_without_seed_submits_unchanged_without_randomizing(self):
        graph=copy.deepcopy(fixture.GRAPH);del graph['4']['inputs']['seed'];(self.root/'workflow.json').write_text(json.dumps(graph))
        client=fixture.FakeClient()
        with patch.object(comfy.secrets,'randbelow',side_effect=AssertionError('no seed socket')):
            result=comfy.execute(self.args,client)
        payload=json.loads(next(body for _,path,body in client.calls if path=='/prompt'))
        self.assertNotIn('seed',payload['prompt']['4']['inputs'])
        self.assertIsNone(result['seed'])
        job=json.loads((Path(self.args.out_dir)/'job.json').read_text())
        self.assertEqual(job['seedTargets'],[]);self.assertEqual(job['seedPolicy'],'workflow-default')
    def test_linked_seed_and_explicit_primitive_binding(self):
        graph=copy.deepcopy(fixture.GRAPH);graph['4']['inputs']['seed']=['6',0];graph['6']={'class_type':'PrimitiveInt','inputs':{'value':123}}
        prepared,_=comfy.prepare(fixture.CONFIG,graph,prompt='test',first='image',last=None,width=64,height=64,duration=3)
        with patch.object(comfy.secrets,'randbelow',return_value=456):
            randomized,seed,targets=comfy.randomize_seed(fixture.CONFIG,prepared)
        self.assertEqual(seed,456);self.assertEqual(randomized['4']['inputs']['seed'],456);self.assertNotIn('6',randomized)
        config=copy.deepcopy(fixture.CONFIG);config['bindings']['seed']=['6','value']
        with patch.object(comfy.secrets,'randbelow',return_value=789):randomized,seed,targets=comfy.randomize_seed(config,prepared)
        self.assertEqual(randomized['6']['inputs']['value'],789);self.assertEqual(randomized['4']['inputs']['seed'],['6',0])
        self.assertEqual(graph['6']['inputs']['value'],123)
    def test_seed_binding_cannot_replace_dimensions(self):
        config=copy.deepcopy(fixture.CONFIG);config['bindings']['seed']=config['bindings']['width']
        with self.assertRaisesRegex(comfy.ComfyError,'overlaps'):comfy.seed_targets(config,fixture.GRAPH)
