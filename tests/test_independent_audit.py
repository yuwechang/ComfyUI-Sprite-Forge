import copy,json,math,sys,tempfile,unittest
from pathlib import Path
from fractions import Fraction
from unittest.mock import patch
from PIL import Image
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'skills/comfyui-forge-video2dsprite/scripts'),str(ROOT/'skills/comfyui-forge-generate2dmedia/scripts')]
import test_comfyui_media as f
import comfyui_forge_media as media,comfyui_forge_route_media as router
import comfyui_forge_contracts as contracts,comfyui_forge_selection_tools as selection
import comfyui_forge_gait_loop as cycle,comfyui_forge_deliver_animation as delivery
from types import SimpleNamespace
import contract_schema as schema

class IndependentTests(unittest.TestCase):
    def prepare(self,config,graph=None,last=None):
        return media.prepare(config,graph or f.GRAPH,prompt='requested motion',first='first.png',last=last,width=96,height=64,duration=1.25)
    def test_optional_bindings_cannot_overwrite_required_values(self):
        for role,target,last in [('fps',['4','width'],None),('last_image',['1','image'],'last.png')]:
            config=copy.deepcopy(f.CONFIG);config['bindings'][role]=target
            with self.subTest(role=role),self.assertRaisesRegex(media.ComfyError,'conflicting'):self.prepare(config,last=last)
    def test_optional_tail_socket_cannot_delete_an_active_input(self):
        config=copy.deepcopy(f.CONFIG);config['last_frame_input']=['1','image']
        with self.assertRaisesRegex(media.ComfyError,'conflicts'):self.prepare(config)
    def test_disconnected_fps_binding_is_rejected(self):
        config=copy.deepcopy(f.CONFIG);graph=copy.deepcopy(f.GRAPH)
        config['bindings']['fps']=['99','unused'];graph['99']['inputs']['unused']=12
        with self.assertRaisesRegex(media.ComfyError,'does not reach'):self.prepare(config,graph)
    def test_automatic_seed_detection_cannot_overlap_a_dimension(self):
        config=copy.deepcopy(f.CONFIG);config['bindings']['width']=['4','seed']
        graph,_=self.prepare(config)
        with self.assertRaisesRegex(media.ComfyError,'overlaps'):media.seed_targets(config,graph)
    def test_readonly_check_and_resolve_use_configured_canvas_rules(self):
        config=copy.deepcopy(f.CONFIG);config['planning']={'dimension_multiple':64,'minimum_source_size':[1536,640]}
        with patch.object(media,'load_config',return_value=config),patch.object(media,'load_graph',return_value=f.GRAPH):
            client=f.FakeClient();checked=media.check(client)
            self.assertIn('seedBounds',checked)
            resolved=router.resolve('video');self.assertGreater(resolved.candidates[0].duration,0)
            self.assertTrue(all(method=='GET' for method,_,_ in client.calls))
        width,height=media.diagnostic_canvas(config)
        self.assertEqual((width%64,height%64),(0,0));self.assertGreaterEqual(width,1536)
    def test_conflicting_tick_and_ms_durations_stop_before_sampling(self):
        value={'indices':[0,1],'durations':[500,500],'start':0,'endExclusive':2,
               'raw':{'ticks':[1,1],'tickHz':24,'events':[]}}
        with self.assertRaisesRegex(ValueError,'disagree'):selection.playback_plan(value,8,'hold')
        for raw in [{'ticks':[1,1]},{'tickHz':24},{'ticks':[1,True],'tickHz':2}]:
            with self.subTest(raw=raw),self.assertRaises(ValueError):contracts.timeline([500,500],raw)
    def test_conflicting_event_clocks_and_nonfinite_times_are_rejected(self):
        for event in [{'name':'signal','tick':1,'atMs':900},{'name':'signal','atMs':float('nan')},{'name':'signal','tick':True}]:
            with self.subTest(event=event),self.assertRaises(ValueError):contracts.timeline([500,500],{'ticks':[1,1],'tickHz':2,'events':[event]})
        contracts.timeline([42,41,42],{'ticks':[1,1,1],'tickHz':24,'events':[{'name':'signal','tick':1,'atMs':42}]})
    def test_selection_reader_also_rejects_inconsistent_clocks(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'selection.json'
            path.write_text(json.dumps({'schema':cycle.SELECTION_V2,'sourceDirectory':'frames','start':0,'endExclusive':2,
             'sourceHashes':['a'*64,'b'*64],'sourceIndices':[0,1],'durations_ms':[500,500],
             'loopPolicy':'oneshot','ticks':[1,1],'tickHz':24,'events':[]}))
            with self.assertRaisesRegex(ValueError,'disagree'):cycle.read_selection(path)
    def test_resource_reduction_has_an_impossibility_exit(self):
        with patch.dict('os.environ',{'COMFYUI_FORGE_ANALYSIS_MEMORY_MB':'1'}):
            with self.assertRaisesRegex(ValueError,'minimum reduced-frame storage'):cycle._reduction_factor((32,32),65537)
            factor=cycle._reduction_factor((128,128),65536)
            self.assertLessEqual(65536*math.ceil(128/factor)**2*4,1024**2//4)
    def test_invalid_server_schema_has_a_clear_pre_submission_error(self):
        with self.assertRaisesRegex(media.ComfyError,'JSON object'):media.seed_bounds(f.GRAPH,[('4','seed')],[])
    def test_core_rejects_a_selection_with_an_incompatible_playback_policy(self):
        selected={'indices':[0,1],'durations':[500,500],'start':0,'endExclusive':2,'policy':'cycle','raw':{}}
        with self.assertRaisesRegex(ValueError,'policy'):selection.playback_plan(selected,8,'hold')
    def test_rejected_selection_and_invalid_event_names_cannot_cross_other_entries(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'selection.json';p.write_text(json.dumps({'status':'rejected'}))
            with self.assertRaisesRegex(ValueError,'rejected'):cycle.read_selection(p)
        with self.assertRaisesRegex(ValueError,'event'):contracts.timeline([100],{'events':[{'name':'bad name','atMs':0}]})
    def test_schema_requires_the_actual_v2_playback_fields(self):
        document={'schema':cycle.SELECTION_V2,'sourceDirectory':'frames','sourceHashes':['a'*64],
                  'start':0,'endExclusive':1,'status':'selected-needs-visual-review'}
        schemas=schema.SchemaSet(ROOT/'tests/schemas')
        self.assertTrue(schemas.errors(document,'video.schema.json#/$defs/frame_selection_v2'))
    def test_selection_motion_metadata_cannot_contradict_its_policy(self):
        for raw,policy in [({'kind':'run'},'cycle'),({'kind':'cycle','motionType':'oneshot-hold'},'cycle'),({'motionType':'cycle'},'oneshot')]:
            with self.subTest(raw=raw),self.assertRaises(ValueError):contracts.selection_motion(raw,policy)
        for kind,policy in [('cycle','cycle'),('oneshot-return','oneshot'),('oneshot-hold','oneshot')]:contracts.selection_motion({'kind':kind,'motionType':kind},policy)
    def test_gif_format_limit_is_reported_without_partial_output(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'preview.gif'
            with self.assertRaisesRegex(ValueError,'format limit'):delivery.write_gif([Image.new('RGBA',(2,2),'red')],700,path)
            self.assertFalse(path.exists())
            delivery.write_gif([Image.new('RGBA',(2,2),'red')],Fraction(65535,100),path)
            with Image.open(path) as gif:self.assertEqual(gif.info['duration'],655350)

if __name__=='__main__':unittest.main()
