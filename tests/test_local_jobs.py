"""Offline regressions for decimal timing, provider removal and safe job recovery."""
import contextlib
import copy
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills/comfyui-forge-generate2dmedia/scripts'))
sys.path.insert(0, str(ROOT / 'skills/comfyui-forge-video2dsprite/scripts'))
sys.path.insert(0, str(ROOT / 'skills/comfyui-forge-generate2dsprite/scripts'))
import comfyui_forge_media as comfy
import comfyui_forge_frame_rules
import comfyui_forge_master_still
import comfyui_forge_sprite_set
from batch_fixture import confirmed
import test_comfyui_media as fixture
from test_comfyui_media import FakeClient, GRAPH, CONFIG, MP4


class JobTests(unittest.TestCase):
    setUp = fixture.ComfyTests.setUp
    tearDown = fixture.ComfyTests.tearDown

    def fail_submission(self, client, error):
        original = client.call
        def call(method, path, *a, **kw):
            if method == 'POST' and path == '/prompt':
                raise error
            return original(method, path, *a, **kw)
        client.call = MagicMock(side_effect=call)

    def submission_count(self, client):
        return sum(c.args[:2] == ('POST', '/prompt') for c in client.call.call_args_list)

    def job(self):
        return json.loads((Path(self.args.out_dir) / 'job.json').read_text())

    def runner(self):
        return SimpleNamespace(root=self.root, entries={'idle': {'pinLastFrame': True}},
                               plan={'generation': {'duration': 1.25}},
                               astate=lambda ident: {'job': {'dir': 'input-job'}})

    def test_decimal_seconds_submit_integer_frames_and_record_provenance(self):
        self.args.duration = 1.25
        client = FakeClient()
        result = comfy.execute(self.args, client)
        submitted = json.loads(next(body for _, path, body in client.calls if path == '/prompt'))
        self.assertIs(type(submitted['prompt']['4']['inputs']['length']), int)
        self.assertEqual(submitted['prompt']['4']['inputs']['length'], 39)
        job = self.job()
        self.assertEqual(job['client_id'], submitted['client_id'])
        self.assertEqual(job['durationRequested'], 1.25)
        self.assertEqual(result['durationUsed'], 39 / 24)
        self.assertEqual(len(job['fingerprints']['submitted_workflow']), 64)
        self.assertIn('createdAt', job)
        self.assertIn('updatedAt', job)

    def test_conflicting_source_settings_fail_before_network_or_output(self):
        for key, value in [('fps', 12), ('frame_multiple', 1), ('frame_offset', 0), ('frame_minimum', 1)]:
            cfg = {**CONFIG, key: value}
            (self.root / 'config.json').write_text(json.dumps(cfg))
            with self.subTest(key=key), self.assertRaises(ValueError):
                comfy.execute(self.args, FakeClient())
            self.assertFalse(Path(self.args.out_dir).exists())

    def test_fixed_formula_across_fractional_boundaries(self):
        for i in range(1, 2000):
            seconds = i / 96
            n = max(5, round(seconds * 24))
            self.assertEqual(comfyui_forge_frame_rules.frame_count(seconds), n + (5 - n % 17) % 17)
            self.assertIs(type(comfyui_forge_frame_rules.frame_count(seconds)), int)

    def test_bad_timeouts_refused_before_output(self):
        for timeout in [0, -1, float('nan'), float('inf')]:
            self.args.timeout = timeout
            with self.subTest(timeout=timeout), self.assertRaises(comfy.ComfyError):
                comfy.execute(self.args, FakeClient())
            self.assertFalse(Path(self.args.out_dir).exists())

    def test_lost_submission_keeps_unknown_and_client_id(self):
        client = FakeClient()
        self.fail_submission(client, OSError('response lost after acceptance'))
        with self.assertRaises(OSError):
            comfy.execute(self.args, client)
        self.assertEqual(self.submission_count(client), 1)
        self.assertEqual(self.job()['status'], 'unknown')
        self.assertTrue(self.job()['client_id'])

    def test_http_validation_rejection_is_definitive(self):
        client = FakeClient()
        self.fail_submission(client, HTTPError('/prompt', 400, 'invalid', {}, io.BytesIO(b'bad binding')))
        with self.assertRaises(comfy.ComfyError):
            comfy.execute(self.args, client)
        self.assertEqual(self.job()['status'], 'failed')
        self.assertEqual(self.submission_count(client), 1)

    def test_missing_prompt_id_is_unknown_instead_of_failed(self):
        client = FakeClient()
        client.call = MagicMock(return_value={})
        with self.assertRaisesRegex(comfy.ComfyError, 'unknown'):
            comfy.execute(self.args, client)
        self.assertEqual(self.job()['status'], 'unknown')

    def test_explicit_node_errors_are_failed(self):
        client = FakeClient()
        client.call = MagicMock(return_value={'node_errors': {'4': 'bad input'}})
        with self.assertRaises(comfy.ComfyError):
            comfy.execute(self.args, client)
        self.assertEqual(self.job()['status'], 'failed')

    def test_upload_failure_never_submits(self):
        client = FakeClient()
        client.upload = MagicMock(side_effect=OSError('upload failed'))
        with self.assertRaises(OSError):
            comfy.execute(self.args, client)
        self.assertFalse(any(method == 'POST' for method, _, _ in client.calls))
        self.assertEqual(self.job()['submission'], 'not_sent')

    def unknown(self):
        client = FakeClient()
        self.fail_submission(client, OSError('connection lost'))
        with self.assertRaises(OSError):
            comfy.execute(self.args, client)
        folder = Path(self.args.out_dir)
        graph = json.loads((folder / 'submitted-workflow.json').read_text())
        job = self.job()
        prompt = [1, 'test-id', graph, {'client_id': job['client_id']}, ['5']]
        return folder, prompt

    def test_unknown_inspection_is_read_only_and_matches_client_and_graph(self):
        folder, prompt = self.unknown()
        before = (folder / 'job.json').read_bytes()
        client = FakeClient()
        client.call = MagicMock(side_effect=[{'queue_running': [prompt]}, {}])
        result = comfy.inspect_job(folder, client)
        self.assertEqual(result['matches'][0]['prompt_id'], 'test-id')
        self.assertEqual(before, (folder / 'job.json').read_bytes())
        self.assertTrue(all(call.args[0] == 'GET' for call in client.call.call_args_list))

    def test_unknown_unique_match_resumes_without_post(self):
        folder, prompt = self.unknown()
        client = FakeClient()
        original = client.call
        client.call = lambda method, path, *a, **k: ({'queue_pending': [prompt]} if path == '/queue' else
                                                  {} if path == '/history' else original(method, path, *a, **k))
        result = comfy.resume(folder, client=client)
        self.assertEqual(Path(result['artifact']).read_bytes(), MP4)
        self.assertFalse(any(path == '/prompt' for _, path, _ in client.calls))

    def test_unknown_ambiguous_match_never_submits_or_changes_receipt(self):
        folder, prompt = self.unknown()
        other = copy.deepcopy(prompt)
        other[1] = 'second-id'
        before = (folder / 'job.json').read_bytes()
        client = FakeClient()
        client.call = MagicMock(side_effect=[{'queue_pending': [prompt, other]}, {}])
        with self.assertRaisesRegex(comfy.ComfyError, 'unknown'):
            comfy.resume(folder, client=client)
        self.assertEqual(before, (folder / 'job.json').read_bytes())

    def test_unknown_wrong_client_is_not_adopted(self):
        folder, prompt = self.unknown()
        prompt[3]['client_id'] = 'another-client'
        client = FakeClient()
        client.call = MagicMock(side_effect=[{'queue_pending': [prompt]}, {}])
        self.assertEqual(comfy.inspect_job(folder, client)['matches'], [])

    def test_changed_submitted_workflow_refused(self):
        folder, _ = self.unknown()
        (folder / 'submitted-workflow.json').write_text(json.dumps(GRAPH))
        client = FakeClient()
        with self.assertRaisesRegex(comfy.ComfyError, 'checksum'):
            comfy.resume(folder, client=client)
        self.assertEqual(client.calls, [])

    def test_download_rejects_header_only_container(self):
        with self.assertRaises(comfy.ComfyError):
            comfy.validate_mp4(b'\0\0\0\x18ftypisom' + b'fake payload')

    def test_batch_does_not_adopt_clip_over_unknown_receipt(self):
        folder = self.root / 'take/media'
        folder.mkdir(parents=True)
        (folder / 'clip.mp4').write_bytes(MP4)
        (folder / 'job.json').write_text('{}')
        with patch.object(comfy, 'resume', side_effect=comfy.ComfyError('unknown')) as resume, patch.object(comfy, 'execute') as submit:
            result = comfyui_forge_sprite_set.SetRunner.generate(self.runner(), 'idle', {'dir': 'take'}, 1)
        self.assertEqual(result['status'], 'error')
        resume.assert_called_once()
        submit.assert_not_called()
        self.assertTrue((folder / 'clip.mp4').exists())

    def test_batch_checks_completed_artifact_checksum(self):
        self.args.out_dir = str(self.root / 'take/media')
        result = comfy.execute(self.args, FakeClient())
        Path(result['artifact']).write_bytes(b'replaced')
        with patch.object(comfy, 'execute') as submit:
            result = comfyui_forge_sprite_set.SetRunner.generate(self.runner(), 'idle', {'dir': 'take'}, 1)
        self.assertEqual(result['status'], 'error')
        self.assertIn('checksum', result['message'])
        submit.assert_not_called()

    def test_batch_tail_error_does_not_retry_without_tail(self):
        (self.root / 'take').mkdir()
        (self.root / 'take/prompt.txt').write_text('run')
        (self.root / 'input-job').mkdir()
        (self.root / 'input-job/input.png').write_bytes(b'fixture')
        with patch.object(comfy, 'execute', side_effect=OSError('last frame response lost')) as submit:
            result = comfyui_forge_sprite_set.SetRunner.generate(self.runner(), 'idle', {'dir': 'take'}, 1)
        self.assertEqual(result['status'], 'error')
        submit.assert_called_once()
        self.assertIsNotNone(submit.call_args.args[0].last_frame)

    def test_get_transport_retry_and_post_no_retry(self):
        client = comfy.Client(CONFIG['url'])
        client.opener = MagicMock()
        client.opener.open.side_effect = [OSError('temporary'), io.BytesIO(b'{}')]
        with patch.object(comfy.time, 'sleep'):
            self.assertEqual(client.call('GET', '/history'), {})
        self.assertEqual(client.opener.open.call_count, 2)
        client.opener.open.reset_mock(side_effect=True)
        client.opener.open.side_effect = OSError('response lost')
        with self.assertRaises(OSError):
            client.call('POST', '/prompt', b'{}')
        self.assertEqual(client.opener.open.call_count, 1)

    def test_obsolete_master_generation_commands_and_delegate_flags_are_gone(self):
        parser = comfyui_forge_master_still.build_parser()
        for argv in [['generate'], ['edit'], ['prompt', '--media-cli', 'x'], ['prompt', '--media-arg=x']]:
            with self.subTest(argv=argv), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                parser.parse_args(argv)
        self.assertFalse(hasattr(comfyui_forge_master_still, 'MediaCli'))
        self.assertFalse(hasattr(comfyui_forge_master_still, 'call_media'))

    def test_local_master_prompt_and_edit_prompt_still_work(self):
        flags = ['--name', 'hero', '--subject', 'a knight', '--identity', 'silver armor']
        summary, code = comfyui_forge_master_still.run(['prompt', *flags, '--output-dir', str(self.root / 'prompt')])
        self.assertEqual(code, 0)
        self.assertTrue(Path(summary['prompt']).is_file())
        summary, code = comfyui_forge_master_still.run(['edit-prompt', *flags, '--still', self.args.reference,
                                         '--change', 'raise the sword', '--output-dir', str(self.root / 'edit')])
        self.assertEqual(code, 0)
        self.assertIn('raise the sword', Path(summary['prompt']).read_text())

    def test_batch_plan_preserves_decimal_seconds(self):
        args = comfyui_forge_sprite_set.build_parser().parse_args(['plan','--spec',confirmed(self.root), '--master', 'master.json', '--output-dir', 'new', '--motions-file','motions.json', '--duration', '2.25'])
        self.assertEqual(args.duration, 2.25)

    def test_supplied_master_approval_and_decimal_batch_plan(self):
        from PIL import Image, ImageDraw
        image = Image.new('RGB', (128, 128), 'magenta')
        ImageDraw.Draw(image).rectangle((40, 15, 85, 110), fill='navy')
        image.save(self.root / 'knight.png')
        summary, code = comfyui_forge_master_still.run(['approve', '--still', str(self.root / 'knight.png'),
                                         '--name', 'hero', '--subject', 'a knight', '--identity', 'navy armor',
                                         '--output-dir', str(self.root / 'approved')])
        self.assertEqual(code, 0)
        motions=self.root/'motions.json'
        motions.write_text(json.dumps([{'id':'arbitrary','type':'cycle','description':'requested movement'}]))
        args = comfyui_forge_sprite_set.build_parser().parse_args(['plan','--spec',confirmed(self.root,2.25), '--master', summary['metadata'],
                                                    '--motions-file',str(motions), '--duration', '2.25',
                                                    '--output-dir', str(self.root / 'set')])
        result = comfyui_forge_sprite_set.cmd_plan(args)
        plan = json.loads(Path(result['plan']).read_text())
        self.assertEqual(plan['generation']['duration'], 2.25)
        self.assertEqual(plan['generation']['frameCount'], 56)

    def test_media_schema_matches_real_receipt(self):
        sys.path.insert(0, str(ROOT / 'shared'))
        from comfyui_forge_schema import SchemaSet
        comfy.execute(self.args, FakeClient())
        schemas = SchemaSet(ROOT / 'shared/schemas')
        self.assertEqual(schemas.errors(self.job(), 'media.schema.json#/$defs/job'), [])
        invalid = self.job()
        invalid['frameCount'] = 39.5
        self.assertTrue(schemas.errors(invalid, 'media.schema.json#/$defs/job'))

    def test_processing_resume_verifies_source_even_after_stages_exist(self):
        source = self.root / 'clip.mp4'
        source.write_bytes(MP4)
        record = {'clip': {'path': 'clip.mp4', 'sha256': comfy.digest(MP4)}, 'stages': {'keyed': {}}}
        comfyui_forge_sprite_set.SetRunner.verify_clip(self.runner(), record)
        source.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            comfyui_forge_sprite_set.SetRunner.verify_clip(self.runner(), record)


if __name__ == '__main__':
    unittest.main()
