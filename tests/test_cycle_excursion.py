"""Coarsely sampled real motion must not be classified static by a step ratio."""
import sys,unittest,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/comfyui-forge-video2dsprite/scripts'))
from PIL import Image,ImageDraw
import comfyui_forge_gait_loop as cycle

class ExcursionTests(unittest.TestCase):
    def frames(self,root,positions):
        root.mkdir()
        for n,x in enumerate(positions):
            image=Image.new('RGBA',(32,32));ImageDraw.Draw(image).rectangle((x,8,x+8,23),fill=(220,140,30,255));image.save(root/f'{n:03}.png')
        return root
    def test_sparse_pose_cycle_with_low_excursion_is_selected(self):
        with tempfile.TemporaryDirectory() as temp:
            frames=self.frames(Path(temp)/'poses',[2,10,18,10]*5)
            analysis=cycle.analyse(frames,24,min_seconds=.125,max_seconds=.5)
            recommendation=cycle.recommend(analysis)
            window=recommendation['window']
            self.assertEqual(window['classification']['class'],'valid-cycle')
            self.assertLess(window['amplitude_steps'],2)
            self.assertLessEqual(window['closure_steps'],cycle.CLOSURE_MAX_STEPS)
    def test_truly_static_clip_remains_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            frames=self.frames(Path(temp)/'still',[8]*20)
            with self.assertRaisesRegex(ValueError,'static clip'):cycle.analyse(frames,24,min_seconds=.125,max_seconds=.5)
    def test_bad_closure_is_still_rejected(self):
        from types import SimpleNamespace
        analysis=SimpleNamespace(usable={'endExclusive':40},lengths={'minFrames':4})
        metrics={'endExclusive':20,'frames':12,'closure_steps':1.5,'amplitude_steps':1.7,'root_drift_pct_body':0,'holds_inside':[]}
        verdict=cycle.classify_ambient(analysis,metrics)
        self.assertEqual(verdict['class'],'rejected');self.assertTrue(any('does not close' in reason for reason in verdict['reasons']))
        self.assertFalse(any('static' in reason for reason in verdict['reasons']))
