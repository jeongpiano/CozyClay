# 목적: 콘티·대본·씬 연속성 입력과 기존 CozyClay LLM 호출 호환성을 검증한다.
# 실행: 사람이 python3 -m unittest -v test_llm_v2 로 실행한다; 실제 LLM·편집기를 부르지 않는다.
# 요청: 2026-11-08 사용자 — SPEC_llm_v2.md 구현과 요청 본문 단위 시험.
# 연결: cozy_llm.py, library/*.json; 입력·출력 fixture는 임시 폴더에만 만든다.
# 이력·되돌리기: SPEC_llm_v2_report.md; 이 시험 파일만 제거해도 운영 호출에 영향이 없다.
import base64
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cozy_llm as llm


def scene_spec():
    return {
        'name': 'test_scene', 'desc': '검증용 장면', 'frames': 120,
        'params': {}, 'objects': [],
        'characters': [{'name': 'A', 'model': 'y-bot-tpose',
                        'motion': [{'skill': 'standIdle', 'f0': 0,
                                    'args': {'at': [0, 0], 'until': 119}}]}],
        'camera': {'mode': 'rail', 'points': [{'x': 1, 'z': 2}, {'x': 1, 'z': 1}],
                   'height': 1.5, 'aim': ['@A'], 'focalMm': 35, 'range': [0, 119]},
    }


def display_metadata():
    return {'based_on': 'seated_side_rail', 'variant': '',
            'camera_story': ['0~2초 인물 옆 넓은 화면', '2~4초 인물에게 부드럽게 접근',
                             '4~5초 얼굴 앞 구도에서 정지']}


class LlmV2Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='cozy-llm-v2-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.input = self.root / 'scene.json'
        self.input.write_text(json.dumps({'description': '의자에 앉은 인물'}), encoding='utf-8')
        self.out = self.root / 'spec.json'
        self.argv = ['--scene-json', str(self.input), '--seconds', '5', '--out', str(self.out)]

    def image(self, name):
        path = self.root / name
        path.write_bytes(b'\x89PNG\r\n\x1a\n' + name.encode())
        return path

    def neighbors(self, data):
        path = self.root / 'neighbors.json'
        path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        return path

    def parse(self, *extra):
        return llm._build_parser().parse_args(self.argv + list(extra))

    def saved(self):
        return json.loads(self.out.read_text(encoding='utf-8'))

    def test_legacy_parser_defaults_and_optional_inputs(self):
        args = self.parse()
        self.assertEqual(args.provider, 'local')
        for field in ('conti_image', 'conti_caption', 'neighbors', 'script', 'preset'):
            self.assertIsNone(getattr(args, field))
        self.assertEqual(llm._context(args), ('', []))
        args = self.parse('--conti-image', '/tmp/conti.png', '--conti-caption', '설명',
                          '--neighbors', '/tmp/neighbors.json', '--script', '대사', '--preset', 'seated_side_rail')
        self.assertEqual((args.conti_image, args.conti_caption, args.neighbors, args.script, args.preset),
                         ('/tmp/conti.png', '설명', '/tmp/neighbors.json', '대사', 'seated_side_rail'))

    def test_three_images_are_base64_in_role_order_in_generate_body(self):
        paths = [self.image(name) for name in ('conti.PNG', 'previous.jpg', 'next.jpeg')]
        neighbors = self.neighbors({'prev': {'n': 0, 'summary': '앞 씬 끝', 'end_frame': paths[1].name, 'camera': '오른쪽'},
                                    'next': {'n': 2, 'summary': '뒤 씬 시작', 'start_frame': str(paths[2])}})
        context, images = llm._context(self.parse('--conti-image', str(paths[0]), '--neighbors', str(neighbors),
                                                 '--conti-caption', '허리 위', '--script', 'A: 안녕'))
        body = llm._build_local_request('vision-model', context, images)
        self.assertEqual([base64.b64decode(v) for v in body['images']], [p.read_bytes() for p in paths])
        self.assertIn('1: storyboard', body['prompt'])
        self.assertIn('2: previous scene ending', body['prompt'])
        self.assertIn('3: next scene opening', body['prompt'])
        self.assertIn('앞 씬 끝', body['prompt'])
        self.assertIn('A: 안녕', body['prompt'])
        self.assertIn('허리 위', body['prompt'])
        self.assertEqual(body['model'], 'vision-model')
        self.assertEqual(body['format'], 'json')
        self.assertFalse(body['stream'])
        self.assertFalse(body['think'])

    def test_next_supports_symmetric_end_frame_and_null_prev(self):
        image = self.image('next.png')
        neighbors = self.neighbors({'prev': None, 'next': {'n': 2, 'end_frame': str(image)}})
        context, images = llm._context(self.parse('--neighbors', str(neighbors)))
        self.assertEqual(images, [base64.b64encode(image.read_bytes()).decode('ascii')])
        self.assertIn('1: next scene opening', context)

    def test_no_images_key_for_legacy_body_and_three_image_limit(self):
        body = llm._build_local_request('model', 'scene')
        self.assertNotIn('images', body)
        self.assertEqual(body['keep_alive'], 120)
        with self.assertRaisesRegex(ValueError, 'three images'):
            llm._build_local_request('model', 'scene', ['a'] * 4)

    def test_text_providers_use_caption_script_neighbors_without_reading_images(self):
        neighbors = self.neighbors({'prev': {'n': 0, 'summary': '앞', 'end_frame': '/missing/prev.png'},
                                    'next': {'n': 2, 'summary': '뒤', 'start_frame': '/missing/next.png'}})
        for provider in ('cloud', 'hermes', 'deepseek'):
            with self.subTest(provider=provider):
                context, images = llm._context(self.parse('--provider', provider, '--conti-image', '/missing/conti.png',
                                                         '--conti-caption', '화면 왼쪽 인물', '--script', 'A: 네',
                                                         '--neighbors', str(neighbors)))
                self.assertEqual(images, [])
                self.assertIn('화면 왼쪽 인물', context)
                self.assertIn('A: 네', context)
                self.assertIn('"summary": "뒤"', context)
                self.assertNotIn('/missing/', context)
                context, _ = llm._context(self.parse('--provider', provider, '--conti-image', '/missing/image.png'))
                self.assertEqual(context, '')

    def test_invalid_optional_inputs_fail_before_llm(self):
        for data in ([], {'prev': 2}, {'next': []}):
            with self.subTest(data=data), self.assertRaisesRegex(ValueError, 'neighbors'):
                llm._context(self.parse('--neighbors', str(self.neighbors(data))))
        with self.assertRaisesRegex(ValueError, 'absolute PNG/JPG'):
            llm._context(self.parse('--conti-image', 'relative.png'))
        with self.assertRaises(FileNotFoundError):
            llm._context(self.parse('--conti-image', str(self.root / 'absent.png')))
        with self.assertRaises(ValueError):
            llm._context(self.parse('--preset', '../outside'))

    def test_catalog_lists_names_descriptions_and_variants(self):
        entries = [json.loads(line) for line in llm._preset_catalog().splitlines()]
        self.assertEqual(len(entries), len(list((llm.ROOT / 'library').glob('*.json'))))
        for row in entries:
            self.assertIn(row['name'], llm.SYSTEM)
            self.assertIn(json.dumps(row['desc'], ensure_ascii=False), llm.SYSTEM)
            self.assertIsInstance(row['camera_variants'], list)
        library = self.root / 'library'
        library.mkdir()
        for variants in ({'side': {}, 'push': {}}, [{'name': 'side'}, {'name': 'push'}], ['side', 'push']):
            path = library / 'catalog.json'
            path.write_text(json.dumps({'name': 'sample', 'desc': 'sample desc', 'camera_variants': variants}), encoding='utf-8')
            row = json.loads(llm._preset_catalog(library))
            self.assertEqual(row['camera_variants'], ['side', 'push'])

    def test_explicit_starting_preset_and_temporal_feedback_rules(self):
        context, images = llm._context(self.parse('--preset', 'seated_side_rail'))
        self.assertIn('Required starting preset', context)
        self.assertIn('"name": "seated_side_rail"', context)
        self.assertIn('[at 3.2s]', llm.SYSTEM)
        for rule in ('16-20mm', '24-28mm', '35mm', '50-85mm', '180-degree', '0.03m', '0.2m', 'backtracking', 'two revolutions'):
            self.assertIn(rule, llm.SYSTEM)
        self.assertEqual(images, [])

    def test_validate_legacy_and_new_metadata(self):
        self.assertEqual(llm.validate(scene_spec(), 120), [])
        spec = scene_spec() | display_metadata()
        self.assertEqual(llm.validate(spec, 120), [])
        for key, value in (('based_on', []), ('variant', 2), ('camera_story', '설명'),
                           ('camera_story', ['짧음']), ('camera_story', ['a', 'b', None]),
                           ('camera_story', [''] * 3), ('camera_story', ['a'] * 7)):
            with self.subTest(key=key, value=value):
                bad = copy.deepcopy(spec)
                bad[key] = value
                self.assertTrue(any(key in e for e in llm.validate(bad, 120)))

    def test_validate_legacy_errors_and_normalize_still_work(self):
        self.assertTrue(llm.validate([], 120))
        for key in ('name', 'params', 'objects', 'camera'):
            bad = scene_spec()
            del bad[key]
            self.assertTrue(llm.validate(bad, 120))
        bad = scene_spec()
        bad['frames'] = 119
        bad['characters'][0]['motion'][0]['f0'] = 120
        bad['camera']['height'] = 0.01
        bad['camera']['points'] = []
        errors = '; '.join(llm.validate(bad, 120))
        for message in ('frames must equal', 'f0', 'two points', 'height'):
            self.assertIn(message, errors)
        spec = scene_spec()
        spec['camera']['height'] = [{'t': 0, 'height': 1}, {'t': 2, 'height': 2}]
        spec['camera']['points'][0]['y'] = 1
        self.assertEqual(llm.validate(llm._normalize(spec), 120), [])
        self.assertNotIn('y', spec['camera']['points'][0])

    def test_gap_and_normal_clearance_thresholds(self):
        for gap, distance, valid in ((False, .21, True), (False, .19, False),
                                      (True, .04, True), (True, .02, False)):
            with self.subTest(gap=gap, distance=distance):
                spec = scene_spec()
                spec['camera']['gap'] = gap
                spec['camera']['points'] = [{'x': distance, 'z': 0}, {'x': 1, 'z': 1}]
                self.assertEqual(not llm.validate(spec, 120), valid)
        spec['camera']['gap'] = 'true'
        self.assertIn('camera.gap must be a boolean', llm.validate(spec, 120))

    def test_main_legacy_call_preserves_scene_and_existing_result_fields(self):
        spec = scene_spec()
        with patch('core.llm.local_model', return_value=('http://ollama', 'vision')), \
                patch('core.llm._post', return_value={'response': json.dumps(spec)}) as post, \
                patch.object(llm, 'llm_chat_meta') as fallback:
            result = llm.main(self.argv)
        self.assertEqual(self.saved(), spec)
        self.assertTrue(result['ok'])
        self.assertEqual(result['spec'], str(self.out))
        self.assertEqual(result['changes'], [])
        self.assertEqual((result['provider'], result['model']), ('local', 'vision'))
        self.assertEqual(result['camera_story'], [])
        self.assertFalse(result['gap'])
        self.assertNotIn('images', post.call_args.args[1])
        fallback.assert_not_called()

    def test_main_local_images_metadata_strip_and_camera_gap_retained(self):
        image = self.image('conti.png')
        spec = scene_spec() | display_metadata()
        spec['camera']['gap'] = True
        with patch('core.llm.local_model', return_value=('http://ollama', 'vision')), \
                patch('core.llm._post', return_value={'response': json.dumps(spec)}) as post:
            result = llm.main(self.argv + ['--conti-image', str(image)])
        self.assertEqual(post.call_args.args[0], 'http://ollama/api/generate')
        self.assertEqual(base64.b64decode(post.call_args.args[1]['images'][0]), image.read_bytes())
        for key, value in display_metadata().items():
            self.assertEqual(result[key], value)
            self.assertNotIn(key, self.saved())
        self.assertTrue(result['gap'])
        self.assertTrue(self.saved()['camera']['gap'])

    def test_main_cloud_hermes_deepseek_use_text_context_and_existing_routes(self):
        for provider in ('cloud', 'hermes', 'deepseek'):
            with self.subTest(provider=provider), \
                    patch.object(llm, '_openai_chat', return_value=(scene_spec(), provider, 'model')) as chat, \
                    patch.object(llm, 'llm_chat_meta', return_value=(json.dumps(scene_spec()), provider, 'model')) as meta:
                result = llm.main(self.argv + ['--provider', provider, '--conti-image', '/missing/ignored.png',
                                               '--conti-caption', '옆모습', '--script', 'A: 응'])
                self.assertTrue(result['ok'])
                if provider == 'cloud':
                    prompt = meta.call_args.args[0]
                    chat.assert_not_called()
                    self.assertEqual(meta.call_args.kwargs['provider'], 'auto')
                else:
                    prompt = chat.call_args.args[1]
                    meta.assert_not_called()
                self.assertIn('옆모습', prompt)
                self.assertIn('A: 응', prompt)

    def test_feedback_changes_and_invalid_result_retry_keep_images(self):
        current = self.root / 'current.json'
        current.write_text(json.dumps(scene_spec()), encoding='utf-8')
        good = scene_spec() | display_metadata() | {'changes': ['3.2초 부근의 카메라만 수정했습니다.']}
        bad = copy.deepcopy(good)
        bad['frames'] = 119
        image = self.image('conti.png')
        with patch('core.llm.local_model', return_value=('http://ollama', 'vision')), \
                patch('core.llm._post', side_effect=[{'response': json.dumps(bad)}, {'response': json.dumps(good)}]) as post:
            result = llm.main(self.argv + ['--current', str(current), '--feedback', '[at 3.2s] 조금 더 가까이',
                                           '--conti-image', str(image)])
        self.assertEqual(post.call_count, 2)
        self.assertEqual(post.call_args_list[0].args[1]['images'], post.call_args_list[1].args[1]['images'])
        self.assertIn('frames must equal 120', post.call_args.args[1]['prompt'])
        self.assertIn('[at 3.2s] 조금 더 가까이', post.call_args.args[1]['prompt'])
        self.assertEqual(result['changes'], good['changes'])
        self.assertNotIn('changes', self.saved())

    def test_local_image_failure_never_drops_images_via_text_fallback(self):
        image = self.image('conti.png')
        with patch('core.llm.local_model', return_value=('http://ollama', 'vision')), \
                patch('core.llm._post', side_effect=OSError('vision offline')) as post, \
                patch.object(llm, 'llm_chat_meta') as fallback:
            with self.assertRaisesRegex(RuntimeError, 'three attempts: vision offline'):
                llm.main(self.argv + ['--conti-image', str(image)])
        self.assertEqual(post.call_count, 3)
        fallback.assert_not_called()
        self.assertFalse(self.out.exists())

    def test_text_only_local_call_keeps_existing_fallback(self):
        with patch('core.llm.local_model', return_value=('', '')), \
                patch.object(llm, 'llm_chat_meta', return_value=(json.dumps(scene_spec()), 'local', 'fallback')) as meta:
            result = llm.main(self.argv)
        self.assertEqual(result['model'], 'fallback')
        self.assertEqual(meta.call_args.kwargs['provider'], 'local')

    def test_unavailable_model_and_empty_image_reply_do_not_fall_back(self):
        image = self.image('conti.png')
        for model in ('', 'vision'):
            with self.subTest(model=model), \
                    patch('core.llm.local_model', return_value=('http://ollama', model)), \
                    patch('core.llm._post', return_value={'response': ''}), \
                    patch.object(llm, 'llm_chat_meta') as fallback:
                with self.assertRaisesRegex(RuntimeError, 'three attempts: local image request'):
                    llm.main(self.argv + ['--conti-image', str(image)])
                fallback.assert_not_called()
                self.assertFalse(self.out.exists())

    def test_malformed_json_retry_also_keeps_images(self):
        image = self.image('conti.png')
        with patch('core.llm.local_model', return_value=('http://ollama', 'vision')), \
                patch('core.llm._post', side_effect=[{'response': 'not JSON'},
                                                     {'response': json.dumps(scene_spec())}]) as post:
            result = llm.main(self.argv + ['--conti-image', str(image)])
        self.assertTrue(result['ok'])
        self.assertEqual(post.call_count, 2)
        self.assertEqual(post.call_args_list[0].args[1]['images'], post.call_args_list[1].args[1]['images'])
        self.assertIn('previous reply was not valid JSON', post.call_args.args[1]['prompt'])


if __name__ == '__main__':
    unittest.main()
