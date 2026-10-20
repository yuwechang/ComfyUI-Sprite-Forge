import json,sys,tempfile,subprocess,copy
from pathlib import Path
from fractions import Fraction
from types import SimpleNamespace
from unittest.mock import patch
import unittest
import numpy as np
from PIL import Image,ImageDraw
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'skills/comfyui-forge-video2dsprite/scripts'),str(ROOT/'skills/comfyui-forge-generate2dsprite/scripts')]
import comfyui_forge_sprite_set,comfyui_forge_prepare_i2v_input as prep,comfyui_forge_selection_tools as selection,comfyui_forge_gait_loop,comfyui_forge_animation_spec,comfyui_forge_contracts,comfyui_forge_av,comfyui_forge_master_still

class UnifiedTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def test_event_offset_inside_hold_stays_inside_hold(self):
        plan=selection.playback_plan({'indices':[0,1,2],'durations':[100,800,100],'start':0,'endExclusive':3,
             'raw':{'events':[{'name':'custom:signal','atMs':500}]}},8,'oneshot')
        self.assertEqual(plan['events'][0]['outputFrame'],4)
        with self.assertRaises(ValueError):selection.playback_plan({'indices':[2,0,1],'durations':[100]*3,
             'start':0,'endExclusive':3,'raw':{'events':[{'name':'in','atMs':0}]}},8,'oneshot')
    def test_source_count_has_no_magic_600_limit(self):
        for i in range(736):(self.root/f'{i:04}.png').touch()
        self.assertEqual(len(comfyui_forge_gait_loop.frame_paths(self.root)),736)
        with patch.dict('os.environ',{'COMFYUI_FORGE_ANALYSIS_MEMORY_MB':'1'}):
            with self.assertRaisesRegex(ValueError,'memory'):comfyui_forge_gait_loop.pairwise_l1(np.zeros((1000,1),np.float32))
    def test_conflicting_named_keys_find_another_colour(self):
        im=Image.new('RGBA',(96,96));draw=ImageDraw.Draw(im)
        for i,c in enumerate(((255,0,255,255),(0,255,0,255),(0,0,255,255))):
            draw.rectangle((10+i*25,20,30+i*25,80),fill=c)
        report=prep.key_preflight(np.asarray(im),'auto')
        winner=next(row for row in report['options'] if row['key']==report['recommended'])
        self.assertFalse(winner['rejected']);self.assertEqual(winner['matteRiskShare'],0)
        self.assertNotIn(winner['key'],('magenta','green','blue'))
    def test_strict_dimensions_counts_and_time_budget(self):
        import comfyui_forge_retime
        with self.assertRaises(ValueError):comfyui_forge_animation_spec.final_spec([128.5,128],1,8,'cycle')
        final=comfyui_forge_animation_spec.final_spec('32x32',1,8,'cycle');final['frameCount']=8.0
        with self.assertRaises(ValueError):comfyui_forge_contracts.final(final)
        with self.assertRaisesRegex(ValueError,'integer'):comfyui_forge_retime.auto_oneshot(np.ones(20),np.linspace(0,1,20),0,duration_ms=1001,rate=Fraction(8))
    def test_every_registered_script_exists(self):
        for path in comfyui_forge_sprite_set.SCRIPTS.values():self.assertTrue(path.is_file(),str(path))
    def make_plan(self, motion_type="oneshot-hold", finish="hd"):
        image=Image.new('RGBA',(64,64));ImageDraw.Draw(image).rectangle((20,10,44,54),fill=(235,165,35,255))
        source=self.root/'supplied.png';image.save(source)
        master,code=comfyui_forge_master_still.run(['approve','--still',str(source),'--name','subject','--subject','original subject',
            '--identity','original gold subject','--output-dir',str(self.root/'master')])
        self.assertEqual(code,0)
        spec=self.root/'spec.json';spec.write_text(json.dumps({'confirmed':True,
            'final':comfyui_forge_animation_spec.final_spec('32x32',1,8,motion_type),'source':{'size':[128,128],'requestedSeconds':3}}))
        motions=self.root/'motions.json';motions.write_text(json.dumps([{'id':'arbitrary','type':motion_type,
            'description':'the complete requested motion','durationSeconds':1}]))
        args=comfyui_forge_sprite_set.build_parser().parse_args(['plan','--spec',str(spec),'--master',master['metadata'],
              '--motions-file',str(motions),'--finish',finish,'--output-dir',str(self.root/'set')])
        return Path(comfyui_forge_sprite_set.cmd_plan(args)['plan'])
    def test_real_offline_batch_to_standard_zip_without_any_network(self):
        import comfyui_forge_media
        try:ffmpeg=comfyui_forge_av._tool('ffmpeg')
        except comfyui_forge_av.ForgeAVError:self.skipTest('ffmpeg is required for offline media integration')
        plan=self.make_plan(getattr(self,'motion_type','oneshot-hold'),getattr(self,'finish','hd'));runner=comfyui_forge_sprite_set.SetRunner(plan)
        runner.ensure_job('arbitrary');record=runner.open_take('arbitrary')
        folder=runner.root/record['dir'];raw=self.root/'synthetic';raw.mkdir()
        job=runner.root/runner.astate('arbitrary')['job']['dir']
        base=Image.open(job/'input.png').convert('RGB')
        for i in range(12):
            frame=base.copy();ImageDraw.Draw(frame).rectangle((59,60,66,70),fill=(230-i*2,160,35));frame.save(raw/f'{i:03}.png')
        media=folder/'media';media.mkdir()
        subprocess.run([ffmpeg,'-hide_banner','-loglevel','error','-framerate','24','-i',str(raw/'%03d.png'),
                        '-c:v','libx264','-crf','0','-pix_fmt','yuv444p',str(media/'clip.mp4')],check=True)
        with patch.object(comfyui_forge_media,'execute',side_effect=AssertionError('must not submit')):
            runner.run()
            self.assertIn(runner.astate('arbitrary')['status'],('blocked','needs-review'))
            self.assertEqual(len(runner.astate('arbitrary')['takes']),1)
            # Rerunning without missing information never submits another take.
            runner.run();self.assertEqual(len(runner.astate('arbitrary')['takes']),1)
            comfyui_forge_sprite_set.cmd_select(SimpleNamespace(plan=str(plan),action='arbitrary',take=1,range='0:12'))
            runner=comfyui_forge_sprite_set.SetRunner(plan);runner.run()
            self.assertEqual(runner.astate('arbitrary')['status'],'needs-review',runner.astate('arbitrary').get('message'))
            self.assertFalse((runner.root/'outputs').exists())
            comfyui_forge_sprite_set.cmd_accept(SimpleNamespace(plan=str(plan),action='arbitrary',take=1,note='Reviewed synthetic fixture final timing and light/dark edges.'))
            runner=comfyui_forge_sprite_set.SetRunner(plan);runner.run()
            self.assertEqual(runner.astate('arbitrary')['status'],'done',runner.astate('arbitrary').get('message'))
            import zipfile
            folder=runner.root/runner.astate('arbitrary')['output']['package']
            with zipfile.ZipFile(folder/'animation.zip') as z:
                names=z.namelist()
                self.assertEqual(len([n for n in names if n.startswith('frames/')]),8)
                self.assertTrue(all(n.endswith(('.png','.gif','.mp4')) for n in names))
            self.assertEqual(len(runner.astate('arbitrary')['takes']),1)

if __name__=='__main__':unittest.main()
