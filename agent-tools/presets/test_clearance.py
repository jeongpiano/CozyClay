# 목적: 편집기를 열지 않고 카메라 거리 계산·보정·깊이 생성 연결의 회귀를 시험한다.
# 실행: 수동 python3 -m unittest -v test_clearance.
# 요청: 2026-11-07 원장 — SPEC_clearance.md 구현 후 실제 세 장면과 경계 조건 검증.
# 연결: cozy_clearance.py, cozy_make_depth.py, mosquito_cozy/MQ_*_spec.json; 렌더러는 모의 객체.
# 이력·되돌리기: test_clearance_report.md; 검증을 중지하려면 이 파일을 제거한다.
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import numpy as np

import cozy_clearance as c
import cozy_make_depth as depth

SCENES = Path('/Users/open/content_studio/work/mosquito_cozy')


def scene(name):
    return json.loads((SCENES / (name + '_spec.json')).read_text(encoding='utf-8'))


def simple(camera=None, objects=None, characters=None, frames=49):
    return dict(frames=frames, objects=objects or [], characters=characters or [],
                camera=camera or dict(mode='rail', points=[dict(x=-2., z=0.), dict(x=2., z=0.)], height=1.))


def object_shape(kind='cube', **kwargs):
    return dict(name='solid', kind=kind, pos=[0, 0, 0], scale=[2, 2, 2], **kwargs)


class GeometryTests(unittest.TestCase):
    def test_known_signed_distances(self):
        cases = {
            'cube': ([0, 1, 0], [2, 1, 0], [2, 3, 0], [-1, 1, 2 ** .5]),
            'sphere': ([0, 1, 0], [2, 1, 0], [0, 3, 0], [-1, 1, 1]),
            'cylinder': ([0, 1, 0], [2, 1, 0], [2, 3, 0], [-1, 1, 2 ** .5]),
            'capsule': ([0, 1, 0], [2, 1, 0], [0, 3, 0], [-1, 1, 1]),
        }
        for kind, (*points, expected) in cases.items():
            with self.subTest(kind=kind):
                shape = c.build_shapes(simple(objects=[object_shape(kind)]), [])[0]
                distances, normals = c.distance(shape, np.array(points, dtype=float))
                np.testing.assert_allclose(distances, expected, atol=1e-9)
                np.testing.assert_allclose(np.linalg.norm(normals, axis=1), 1.)
                self.assertTrue(np.isfinite(normals).all())

    def test_bottom_support_and_thin_rotated_box(self):
        obj = dict(name='leg', kind='cube', pos=[0, .01, 0], scale=[2, .42, .2], rot=[0, 90, 0])
        shape = c.build_shapes(simple(objects=[obj]), [])[0]
        d, _ = c.distance(shape, np.array([[0, .01, 0], [0, .43, 0], [0, 0, 0], [0, .22, .9], [.2, .22, 0]]))
        np.testing.assert_allclose(d, [0, 0, .01, -.1, .1], atol=1e-9)

    def test_xyz_rotation_normal_follows_distance_gradient(self):
        shape = c.build_shapes(simple(objects=[dict(name='box', kind='cube', pos=[0, 0, 0], scale=[1, 2, 3], rot=[20, 35, 15])]), [])[0]
        point = np.array([[1.5, 2.2, 3.]])
        d, normal = c.distance(shape, point)
        derivative = []
        for i in range(3):
            delta = np.eye(3)[i] * 1e-6
            derivative.append((c.distance(shape, point + delta)[0][0] - c.distance(shape, point - delta)[0][0]) / 2e-6)
        np.testing.assert_allclose(normal[0], derivative, atol=1e-7)
        self.assertGreater(d[0], 0)

    def test_long_capsule_axis(self):
        shape = c.build_shapes(simple(objects=[dict(name='post', kind='capsule', pos=[0, .2, 0], scale=[.4, 2, .4])]), [])[0]
        d, normals = c.distance(shape, np.array([[0, .4, 0], [0, 2., 0], [0, 2.3, 0], [.5, 1., 0]]))
        np.testing.assert_allclose(d, [-.2, -.2, .1, .3], atol=1e-9)
        np.testing.assert_allclose(np.sum(normals[:2] * (shape['b'] - shape['a']), axis=1), 0.)

    def test_solid_exclusions_are_independent_of_floor_height(self):
        objects = [object_shape('cube'), dict(object_shape('cube'), name='floor'),
                   dict(object_shape('cube'), name='ghost', solid=False),
                   dict(object_shape('cube'), name='custom'),
                   *[dict(object_shape(k), name=k) for k in ('empty', 'plane', 'text', 'light', 'effect')]]
        spec = simple(objects=objects)
        spec['camera']['solidExclude'] = ['custom']
        self.assertEqual([s['name'] for s in c.build_shapes(spec, [])], ['solid'])

    def test_body_model_dimensions_and_individual_parts(self):
        char = dict(name='person', pos=[1, 0, 2], bodyModel=dict(thigh_length=.6, torso_radius=.22, head=dict(a=[5, 6, 7], radius=.2)))
        parts = {p['name']: p for p in c.body_shapes(char, {})}
        np.testing.assert_allclose(parts['torso']['a'], [1, .92, 2])
        self.assertEqual(parts['torso']['radius'], .22)
        np.testing.assert_allclose(parts['head']['a'], [5, 6, 7])
        np.testing.assert_allclose(parts['head']['b'], [5, 6, 7])
        char.update(posture='seated', rot=[0, 90, 0])
        parts = {p['name']: p for p in c.body_shapes(char, {})}
        np.testing.assert_allclose(parts['thigh_l']['b'] - parts['thigh_l']['a'], [.6, .02, 0], atol=1e-9)

    def test_sitting_seat_knee_direction_and_grip(self):
        spec = scene('MQ_S1w5')
        parts = {p['name']: p for p in c.body_shapes(spec['characters'][0], {o['name']: o for o in spec['objects']})}
        np.testing.assert_allclose(parts['torso']['a'], [0, .54, -2.12])
        np.testing.assert_allclose(parts['hand_l']['a'], [.1, 1.06, -1.98])
        forward = np.array([-.12, 0., .38]); forward /= np.linalg.norm(forward)
        thigh = parts['thigh_r']['b'] - parts['thigh_r']['a']; thigh[1] = 0
        np.testing.assert_allclose(thigh, .45 * forward)


class PathTests(unittest.TestCase):
    def test_arc_length_height_and_range_holds(self):
        spec = simple(dict(mode='rail', points=[dict(x=0, z=0), dict(x=1, z=0), dict(x=1, z=3)], height=[dict(t=0, height=.1), dict(t=1, height=1.1)], range=[2, 6]), frames=9)
        p = c.camera_path(spec)
        np.testing.assert_allclose(p[3], [1, .35, 0])
        np.testing.assert_allclose(p[4], [1, .6, 1])
        np.testing.assert_allclose(p[0], p[2]); np.testing.assert_allclose(p[6], p[8])

    def test_keys_interpolation_and_holds(self):
        spec = simple(dict(mode='keys', keys=[dict(frame=6, pos=[2, 3, 4]), dict(frame=2, pos=[0, 1, 2])]), frames=9)
        p = c.camera_path(spec)
        np.testing.assert_allclose(p[4], [1, 2, 3])
        np.testing.assert_allclose(p[0], p[2]); np.testing.assert_allclose(p[6], p[8])

    def test_keys_mid_segment_hit_warns_without_new_keys(self):
        spec = simple(dict(mode='keys', keys=[dict(frame=0, pos=[-2, 1, 0], look=[0, 0, 0]), dict(frame=48, pos=[2, 1, 0], focalMm=35)]), objects=[object_shape()])
        fixed, report = c.fix_spec(spec)
        self.assertEqual(fixed, spec)
        self.assertFalse(report['changed'])
        self.assertTrue(report['remaining_segments'])
        self.assertTrue(any(w.startswith('key_interpolation_collision') for w in report['warnings']))

    def test_key_position_only_edits_and_irregular_timing(self):
        spec = simple(dict(mode='keys', keys=[dict(frame=0, pos=[0, 1, 0], look=[0, 0, 1]), dict(frame=3, pos=dict(x=0, y=1, z=.3), focalMm=35), dict(frame=48, pos=[3, 1, 0])]), objects=[object_shape()])
        saved = copy.deepcopy(spec)
        fixed, report = c.fix_spec(spec)
        self.assertTrue(report['changed'])
        self.assertEqual(spec, saved)
        self.assertEqual(len(fixed['camera']['keys']), 3)
        for a, b in zip(saved['camera']['keys'], fixed['camera']['keys']):
            self.assertEqual({k: v for k, v in a.items() if k != 'pos'}, {k: v for k, v in b.items() if k != 'pos'})
        self.assertIsInstance(fixed['camera']['keys'][1]['pos'], dict)

    def test_floor_short_clip_and_vertical_rail(self):
        for frames in (1, 3, 12):
            with self.subTest(frames=frames):
                spec = simple(dict(mode='rail', points=[dict(x=0, z=0)] * 2, height=[dict(t=0, height=-.1), dict(t=1, height=.2)]), frames=frames)
                fixed, report = c.fix_spec(spec)
                self.assertTrue(report['changed'])
                self.assertGreaterEqual(c.camera_path(fixed)[:, 1].min(), .05)
                self.assertLessEqual(len(fixed['camera']['height']), 8)
                self.assertGreaterEqual(len(fixed['camera']['points']), 2)

    def test_long_corrected_rail_is_capped_at_512_points(self):
        # 2026-11-07 Codex — 긴 영상에서도 편집기 레일 점 수 상한을 지킨다.
        spec = simple(frames=1200)
        spec['camera']['height'] = -.1
        fixed, report = c.fix_spec(spec)
        self.assertEqual(len(fixed['camera']['points']), 512)
        self.assertLessEqual(len(fixed['camera']['height']), 8)
        self.assertGreaterEqual(c.camera_path(fixed)[:, 1].min(), .05)

    def test_both_passthrough_bypasses_even_floor_and_preserves_spec(self):
        spec = simple(); spec['camera'].update(passThrough=dict(body=True, objects=True), height=-1)
        fixed, report = c.fix_spec(spec)
        self.assertEqual(fixed, spec)
        self.assertIsNot(fixed, spec)
        self.assertFalse(report['changed'])

    def test_body_objects_passthrough_separately(self):
        spec = scene('MQ_S1w5')
        spec['camera']['passThrough'] = dict(body=True, objects=False)
        fixed, report = c.fix_spec(spec)
        self.assertFalse(report['changed']); self.assertIsNone(report['min_before']['body'])
        spec = simple(objects=[object_shape()], characters=[dict(name='person', pos=[10, 0, 0])])
        spec['camera']['passThrough'] = dict(body=False, objects=True)
        fixed, report = c.fix_spec(spec)
        self.assertFalse(report['changed']); self.assertIsNone(report['min_before']['objects'])

    def test_configured_clearance_and_no_input_mutation(self):
        # 2026-11-07 Codex — 사용자 간격 검증은 법선 우회가 가능한 상자 옆 경로로 한다.
        spec = simple(objects=[object_shape()])
        spec['camera']['points'] = [dict(x=-2, z=1.1), dict(x=2, z=1.1)]
        spec['camera']['clearanceM'] = dict(body=.2, objects=.3)
        saved = copy.deepcopy(spec)
        fixed, report = c.fix_spec(spec)
        self.assertEqual(spec, saved)
        self.assertGreaterEqual(report['min_after']['objects'], .3 - 1e-7)
        self.assertLessEqual(report['iterations'], 6)

    def test_symmetric_unsolved_collision_is_reported_after_six_passes(self):
        # 2026-11-07 Codex — 정면 대칭 관통은 양쪽 법선이 맞서므로 성공으로 숨기지 않는다.
        fixed, report = c.fix_spec(simple(objects=[object_shape()]))
        self.assertEqual(report['iterations'], 6)
        self.assertTrue(report['remaining_segments'])
        self.assertIn('remaining_collisions', report['warnings'])
        self.assertLess(report['min_after']['objects'], .06)

    def test_unknown_mode_and_object_are_reported(self):
        spec = simple(dict(mode='orbit', focalMm=35))
        fixed, report = c.fix_spec(spec)
        self.assertEqual(fixed, spec); self.assertEqual(report['unsupported_mode'], 'orbit')
        spec = simple(objects=[object_shape('mesh')])
        fixed, report = c.fix_spec(spec)
        self.assertIn('unsupported_object:solid:mesh', report['warnings'])

    def test_invalid_dimensions_and_clearance(self):
        for spec in (simple(objects=[dict(object_shape(), scale=[-1, 1, 1])]),
                     simple(dict(mode='rail', points=[dict(x=0, z=0)] * 2, clearanceM=dict(body=-.1))),
                     simple(characters=[dict(bodyModel=dict(head_radius=float('nan')))])):
            with self.assertRaises(ValueError):
                c.fix_spec(spec)

    def test_smoothing_spreads_before_and_after_at_real_key_times(self):
        raw = np.zeros((49, 3)); raw[24, 0] = .1
        normal = np.tile([1., 0, 0], (49, 1)); required = raw[:, 0]
        push = c.smooth_push(raw, normal, required)
        self.assertGreaterEqual(push[24, 0], .1 - 1e-9)
        self.assertGreater(push[16, 0], 0); self.assertGreater(push[32, 0], 0)
        sparse = c.smooth_push(raw[[24, 26, 48]], normal[[24, 26, 48]], required[[24, 26, 48]], np.array([24, 26, 48]))
        self.assertGreater(sparse[1, 0], sparse[2, 0])


class SceneTests(unittest.TestCase):
    def test_three_required_scenes_and_serialized_report(self):
        for name in ('MQ_S1w5', 'MQ_S1w6', 'MQ_S4b'):
            with self.subTest(scene=name):
                spec = scene(name); saved = copy.deepcopy(spec)
                fixed, report = c.fix_spec(spec)
                self.assertEqual(spec, saved)
                if name == 'MQ_S1w6':
                    self.assertEqual(fixed, spec); self.assertFalse(report['changed'])
                else:
                    self.assertTrue(report['changed'])
                    self.assertLess(report['min_before']['body'], .12)
                    self.assertGreaterEqual(report['min_after']['body'], .12 - 1e-7)
                    self.assertTrue(any(s['what'].startswith(('thigh', 'shin', 'torso')) for s in report['segments']))
                self.assertGreaterEqual(report['min_after']['objects'], .06 - 1e-7)
                self.assertFalse(report['remaining_segments'])
                self.assertLessEqual(report['iterations'], 6)
                self.assertTrue(report['static_body_assumption'])
                self.assertTrue(2 <= len(fixed['camera']['points']) <= 512)
                self.assertLessEqual(len(fixed['camera']['height']), 8)
                p = c.camera_path(json.loads(json.dumps(fixed, allow_nan=False)))
                self.assertGreaterEqual(p[:, 1].min(), .05)
                shapes = c.build_shapes(fixed, [])
                minima = c.minima(c.measure(p, shapes)[0], shapes)
                self.assertEqual(report['min_after'], minima)
                self.assertEqual(report['accel_max_after'], c.acceleration(p))
                self.assertEqual({k: v for k, v in fixed.items() if k != 'camera'}, {k: v for k, v in spec.items() if k != 'camera'})
                for key in set(spec['camera']) - {'points', 'height'}:
                    self.assertEqual(fixed['camera'][key], spec['camera'][key])
                start, end = spec['camera']['range']
                np.testing.assert_allclose(p[end:], np.tile(p[end], (len(p) - end, 1)))
                self.assertLessEqual(report['accel_max_after'], report['accel_max_before'] * 1.5)

    def test_required_scene_passthrough(self):
        spec = scene('MQ_S1w5'); spec['camera']['passThrough'] = dict(body=True, objects=True)
        fixed, report = c.fix_spec(spec)
        self.assertEqual(fixed, spec); self.assertFalse(report['changed'])

    def test_cli_writes_json_and_last_line_report(self):
        with tempfile.TemporaryDirectory() as folder:
            fixed_path, report_path = Path(folder) / 'fixed.json', Path(folder) / 'report.json'
            run = subprocess.run([sys.executable, str(Path(c.__file__)), str(SCENES / 'MQ_S1w5_spec.json'), '--out', str(fixed_path), '--report', str(report_path)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            report = json.loads(run.stdout.splitlines()[-1])
            self.assertEqual(report, json.loads(report_path.read_text()))
            self.assertTrue(report['ok']); self.assertEqual(report['out'], str(fixed_path))
            fixed = json.loads(fixed_path.read_text()); self.assertEqual(fixed['camera']['range'], [0, 330])

    def test_cli_rejects_overwriting_source(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'source.json'; source.write_text(json.dumps(simple()))
            saved = source.read_bytes()
            run = subprocess.run([sys.executable, str(Path(c.__file__)), str(source), '--out', str(source)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 1); self.assertFalse(json.loads(run.stdout)['ok'])
            self.assertEqual(source.read_bytes(), saved)


# 2026-11-07 Codex — 실제 인형 대신 합성 깊이를 써서 편집기 없이 뒷면 컬링 신호를 재현한다.
class DepthLoopTests(unittest.TestCase):
    def test_depth_problems_synthetic_mp4(self):
        with tempfile.TemporaryDirectory() as folder:
            video = Path(folder) / 'synthetic.mp4'
            pixels = np.zeros((30, 52, 92), dtype=np.uint8)
            pixels[10:20, :, :37] = 255  # About 40% near, then an abrupt disappearance.
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'gray',
                            '-s', '92x52', '-r', '24', '-i', 'pipe:0', '-an', '-c:v', 'libx264',
                            '-crf', '0', '-pix_fmt', 'yuv444p', str(video)],
                           input=pixels.tobytes(), capture_output=True, check=True)
            self.assertEqual(c.depth_problems(str(video)), list(range(8, 20)))

    def test_depth_thresholds_and_lookahead_boundaries(self):
        pixels = np.zeros((30, 52 * 92), dtype=np.uint8)
        pixels[10:20, :1000] = 255  # Enter but not close: only the drop should trigger.
        with patch.object(c.subprocess, 'run', return_value=SimpleNamespace(stdout=pixels.tobytes())):
            self.assertEqual(c.depth_problems('mock.mp4'), list(range(8, 20)))
        pixels[:] = 235  # The near threshold is strictly greater, not greater-or-equal.
        with patch.object(c.subprocess, 'run', return_value=SimpleNamespace(stdout=pixels.tobytes())):
            self.assertEqual(c.depth_problems('mock.mp4'), [])
        pixels[:, :1500] = 255  # Persistent close frames need no following drop.
        with patch.object(c.subprocess, 'run', return_value=SimpleNamespace(stdout=pixels.tobytes())):
            self.assertEqual(c.depth_problems('mock.mp4'), list(range(30)))

    def test_depth_decode_failure_is_not_silently_clear(self):
        for output in (b'', b'partial frame'):
            with patch.object(c.subprocess, 'run', return_value=SimpleNamespace(stdout=output)):
                with self.assertRaises(ValueError):
                    c.depth_problems('mock.mp4')

    def test_aim_path_follows_distance_and_stops(self):
        target = dict(name='target', pos=[9, 9, 9], path=dict(
            points=[dict(x=0, y=1, z=0), dict(x=1, y=1, z=0), dict(x=1, y=1, z=2)], speed=2))
        spec = simple(objects=[target], frames=49)
        spec['camera']['aim'] = ['@target']
        aim = c.aim_path(spec)
        np.testing.assert_allclose(aim[[0, 6, 12, 24, 36, 48]],
                                   [[0, 1, 0], [.5, 1, 0], [1, 1, 0], [1, 1, 1], [1, 1, 2], [1, 1, 2]])
        target['path']['points'].insert(0, dict(x=0, y=1, z=0))
        np.testing.assert_allclose(c.aim_path(spec), aim)

    def test_aim_fixed_object_and_centroid_fallback(self):
        spec = simple(objects=[dict(name='target', pos=[1, 2, 3])])
        for aim in (['@target'], [1, 2, 3], dict(x=1, y=2, z=3)):
            spec['camera']['aim'] = aim
            np.testing.assert_allclose(c.aim_path(spec), np.tile([1, 2, 3], (49, 1)))
        for aim in (None, ['@missing']):
            spec['camera']['aim'] = aim
            np.testing.assert_allclose(c.aim_path(spec), np.tile(c.camera_path(spec).mean(axis=0), (49, 1)))

    def test_push_back_increases_distance_and_has_local_tails(self):
        spec = simple(dict(mode='rail', points=[dict(x=-10, z=2), dict(x=10, z=2)],
                           height=1., aim=[0, 1, 0], focalMm=35), frames=241)
        original = copy.deepcopy(spec)
        problems = list(range(112, 129))
        fixed, report = c.push_back(spec, problems + [120])
        before, after, aim = c.camera_path(spec), c.camera_path(fixed), c.aim_path(spec)
        self.assertTrue((np.linalg.norm(after - aim, axis=1)[problems] >
                         np.linalg.norm(before - aim, axis=1)[problems]).all())
        # Gaussian support is ±3σ from each problem; rail arc-length resampling adds small drift.
        outside = (np.arange(241) < 112 - 3 * .35 * 24) | (np.arange(241) > 128 + 3 * .35 * 24)
        self.assertLess(np.linalg.norm(after - before, axis=1)[outside].max(), .01)
        self.assertEqual(spec, original)
        self.assertEqual(report['frames'], len(problems))
        self.assertEqual(report['windows'], [[round(112 / 24, 6), round(128 / 24, 6)]])
        self.assertAlmostEqual(report['max_push_m'], np.linalg.norm(after - before, axis=1).max())
        self.assertEqual(fixed['camera']['aim'], spec['camera']['aim'])
        self.assertEqual(fixed['camera']['focalMm'], 35)

    def test_push_back_keys_only_positions_and_vertical_weight(self):
        # 2026-11-07 cctb-44: 기본 미는 방향이 radial 로 바뀜 — 이 시험은 예전 view 방식(y 0.5배)을 검사
        import os
        os.environ['COZY_PUSH_MODE'] = 'view'
        self.addCleanup(os.environ.pop, 'COZY_PUSH_MODE', None)
        spec = simple(dict(mode='keys', aim=[0, 0, 0], keys=[
            dict(frame=0, pos=[1, 1, 0], look=[0, 0, 0]),
            dict(frame=24, pos=dict(x=1, y=1, z=0), focalMm=35),
            dict(frame=48, pos=[1, 1, 0])]))
        fixed, report = c.push_back(spec, [24])
        delta = c.vec(fixed['camera']['keys'][1]['pos']) - [1, 1, 0]
        self.assertAlmostEqual(np.linalg.norm(delta), .12)
        self.assertAlmostEqual(delta[1] / delta[0], .5)
        self.assertGreater(report['max_push_m'], 0)
        self.assertIsInstance(fixed['camera']['keys'][1]['pos'], dict)
        for before, after in zip(spec['camera']['keys'], fixed['camera']['keys']):
            self.assertEqual({k: v for k, v in before.items() if k != 'pos'},
                             {k: v for k, v in after.items() if k != 'pos'})
        self.assertEqual(len(fixed['camera']['keys']), 3)

    def test_push_back_empty_short_and_invalid_frames(self):
        spec = simple(frames=1)
        fixed, report = c.push_back(spec, [])
        self.assertEqual(fixed, spec)
        self.assertEqual(report, dict(frames=0, windows=[], max_push_m=0.))
        fixed, report = c.push_back(spec, [0])
        self.assertTrue(np.isfinite(c.camera_path(fixed)).all())
        for frames in ([-1], [1], [.5]):
            with self.assertRaises(ValueError):
                c.push_back(spec, frames)


class IntegrationTests(unittest.TestCase):
    def test_parameterized_preset_and_overrides(self):
        spec = depth.cozy_preset.load('seated_side_rail')
        saved = copy.deepcopy(spec)
        fixed, report = depth.clearance_spec(spec, dict(rail_distance=3, seat_z=-2))
        self.assertEqual(fixed['camera']['points'][0]['x'], 3)
        self.assertEqual(fixed['objects'][0]['pos'][2], -2)
        self.assertEqual(spec, saved)
        with self.assertRaises(ValueError):
            depth.clearance_spec(spec, dict(unknown=3))
        with self.assertRaises(ValueError):
            depth.clearance_spec(spec, dict(rail_distance='bad'))

    def test_disabled_has_no_numpy_clearance_call(self):
        spec = scene('MQ_S1w5')
        with patch.object(c, 'fix_spec', side_effect=AssertionError('must not call')):
            fixed, report = depth.clearance_spec(spec, {}, True)
        self.assertIs(fixed, spec); self.assertFalse(report['enabled'])

    # 2026-11-07 Codex — 기존 모의 MP4를 디코더에 넘기지 않고 반복 결과만 명시적으로 제어한다.
    def fake_make(self, folder, *, disabled=False, source='MQ_S1w5', black=False,
                  detections=None, rounds=None, spec_override=None, seconds=15.):
        folder = Path(folder)
        args = SimpleNamespace(seconds=seconds, fps=24, out=str(folder / 'depth.mp4'), params='{}', preset=None,
                               spec=str(SCENES / (source + '_spec.json')), aim_per_frame=True,
                               no_clearance=disabled, width=640, height=360, preview=str(folder / 'preview.mp4'))
        if rounds is not None:
            args.depth_loop = rounds
        if spec_override is not None:
            args.spec = str(folder / 'source.json')
            Path(args.spec).write_text(json.dumps(spec_override))
        playwright = MagicMock(); browser = playwright.chromium.launch.return_value
        page = browser.new_page.return_value
        download = page.expect_download.return_value.__enter__.return_value
        download.value.save_as.side_effect = lambda path: Path(path).write_bytes(b'mocked MP4')
        manager = MagicMock(); manager.__enter__.return_value = playwright
        with patch('playwright.sync_api.sync_playwright', return_value=manager), \
             patch.object(depth.cozy_preset, 'CLAY', folder), \
             patch.object(depth.cozy_preset, 'apply') as apply, \
             patch.object(depth, 'status', side_effect=[dict(editors=[]), dict(editors=[dict(handle='mock-editor')])]), \
             patch.object(depth, 'probe', return_value=(360, 640, 360)), \
             patch.object(c, 'depth_problems', side_effect=detections if detections is not None else [[]]) as detect, \
             patch.object(depth.subprocess, 'run', return_value=SimpleNamespace(stdout='YMAX=0' if black else 'YMAX=200')):
            if black:
                with self.assertRaisesRegex(RuntimeError, '전부 검정'):
                    depth.make(args)
                self.assertFalse(Path(str(args.out) + '.part').exists())
                result = None
            else:
                result = depth.make(args)
            applied = apply.call_args.args[0]
            self.assertEqual(apply.call_args.kwargs['workspace'], 'mock-editor')
            self.assertEqual(apply.call_args.kwargs['frames'], round(seconds * 24))
            if not black:
                self.assertEqual(apply.call_count, len(result['clearance']['depth_loop']) + 1)
                if disabled or (applied['camera'].get('passThrough') or {}).get('body'):
                    detect.assert_not_called()
                else:
                    self.assertEqual(detect.call_count, apply.call_count)
                self.assertEqual(page.expect_download.call_count, 2 * apply.call_count)
                browser.new_page.assert_called_once()
            browser.close.assert_called_once()
        return result, applied

    def test_make_saves_fixed_spec_preview_and_result_without_browser(self):
        with tempfile.TemporaryDirectory() as folder:
            result, applied = self.fake_make(folder)
            self.assertTrue(result['ok']); self.assertTrue(result['clearance']['changed'])
            self.assertTrue(result['clearance']['enabled'])
            self.assertGreaterEqual(result['clearance']['min_after']['body'], .12)
            self.assertEqual(json.loads((Path(folder) / 'depth_spec_fixed.json').read_text()), applied)
            self.assertTrue(applied['camera']['follow']['aimPerFrame'])
            self.assertTrue(Path(result['preview']).exists()); self.assertTrue(Path(result['depth']).exists())

    def test_make_disable_and_unchanged_do_not_save_fixed_spec(self):
        for disabled, source in ((True, 'MQ_S1w5'), (False, 'MQ_S1w6')):
            with self.subTest(disabled=disabled, source=source), tempfile.TemporaryDirectory() as folder:
                result, applied = self.fake_make(folder, disabled=disabled, source=source)
                self.assertFalse(result['clearance']['changed'])
                self.assertFalse((Path(folder) / 'depth_spec_fixed.json').exists())
                self.assertEqual(applied, scene(source))

    def test_black_depth_check_remains_effective(self):
        with tempfile.TemporaryDirectory() as folder:
            self.fake_make(folder, black=True)

    # 2026-11-07 Codex — 마지막 깊이·미리보기·저장 spec이 모두 같은 보정 회차인지 검증한다.
    def test_depth_loop_resolves_and_overwrites_fixed_spec(self):
        with tempfile.TemporaryDirectory() as folder:
            result, applied = self.fake_make(folder, source='MQ_S1w6', detections=[[150, 151], [152], []])
            rounds = result['clearance']['depth_loop']
            self.assertEqual([r['round'] for r in rounds], [1, 2])
            self.assertEqual([r['problems'] for r in rounds], [2, 1])
            self.assertEqual(rounds[0]['windows'], [[6.25, round(151 / 24, 6)]])
            self.assertTrue(all(r['max_push_m'] > 0 for r in rounds))
            self.assertNotIn('depth_loop_unresolved', result)
            self.assertEqual(json.loads((Path(folder) / 'depth_spec_fixed.json').read_text()), applied)

    def test_depth_loop_default_three_rounds_reports_remaining_seconds(self):
        with tempfile.TemporaryDirectory() as folder:
            result, applied = self.fake_make(folder, detections=[[150], [150], [150], [151, 152]])
            self.assertEqual(len(result['clearance']['depth_loop']), 3)
            self.assertEqual(result['depth_loop_unresolved'], [round(151 / 24, 6), round(152 / 24, 6)])
            self.assertEqual(json.loads((Path(folder) / 'depth_spec_fixed.json').read_text()), applied)

    def test_depth_loop_zero_only_checks_and_custom_limit(self):
        for limit in (0, 1):
            with self.subTest(limit=limit), tempfile.TemporaryDirectory() as folder:
                result, applied = self.fake_make(folder, rounds=limit, detections=[[150]] * (limit + 1))
                self.assertEqual(len(result['clearance']['depth_loop']), limit)
                self.assertEqual(result['depth_loop_unresolved'], [6.25])

    def test_depth_loop_skips_body_passthrough(self):
        spec = scene('MQ_S1w5')
        spec['camera']['passThrough'] = dict(body=True, objects=False)
        with tempfile.TemporaryDirectory() as folder:
            result, applied = self.fake_make(folder, spec_override=spec, detections=[])
            self.assertEqual(result['clearance']['depth_loop'], [])
            self.assertNotIn('depth_loop_unresolved', result)

    def test_depth_loop_matches_export_duration(self):
        spec = simple(dict(mode='rail', points=[dict(x=-2, z=2), dict(x=2, z=2)],
                           height=1, range=[0, 48], aim=[0, 1, 0]), frames=49)
        with tempfile.TemporaryDirectory() as folder:
            result, applied = self.fake_make(folder, spec_override=spec, seconds=4., detections=[[80], []])
            self.assertEqual(applied['frames'], 96)
            self.assertEqual(applied['camera']['range'], [0, 95])
            self.assertEqual(result['clearance']['depth_loop'][0]['windows'], [[round(80 / 24, 6)] * 2])


if __name__ == '__main__':
    unittest.main()
