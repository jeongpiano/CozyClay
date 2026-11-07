# 목적: 인체·사물과 카메라의 간격을 검사하고 굽기 전에 부드러운 우회 레일을 만든다.
# 실행: cozy_make_depth.make 또는 수동 python3 cozy_clearance.py spec.json --out fixed.json.
# 요청: 2026-11-07 원장 — SPEC_clearance.md의 카메라 인체·사물 투과 방지 구현.
# 연결: SPEC_clearance.md, 장면 JSON, numpy; 편집기·게이트웨이는 호출하지 않는다.
# 이력·되돌리기: cctb-44; --no-clearance 또는 passThrough 양쪽 true로 우회한다.
"""Static, metre-based SDF clearance. Rotation uses degrees and XYZ Euler order.

bodyModel overrides any scalar in BODY_DEFAULTS, or individual named parts with
{a: [x,y,z], b: [x,y,z], radius: metres} (world coordinates; b defaults to a).
Rail reports always measure the serialized output, including height compression.
"""
import argparse
import copy
import json
import math
import os
from pathlib import Path
import subprocess
import sys

import numpy as np

FPS = 24
EPS = 1e-10
BODY_DEFAULTS = dict(hip_height=.92, knee_height=.48, ankle_height=.08,
                     hip_half_width=.10, seat_height=.46, seat_hip_offset=.08,
                     seated_knee_offset=.10, thigh_length=.45, shin_forward=.05,
                     seated_ankle_height=.09, foot_length=.16, foot_height=.05,
                     thigh_radius=.085, shin_radius=.06, foot_radius=.05,
                     torso_length=.52, torso_radius=.16, torso_lean=.06,
                     head_offset=.13, head_radius=.11, head_lean=.05,
                     shoulder_drop=.04, shoulder_half_width=.19,
                     resting_hand_offset=.08, elbow_drop=.10, elbow_out=.06,
                     upper_arm_radius=.05, forearm_radius=.045, hand_radius=.05,
                     standing_hand_out=.22)


def vec(value):
    if isinstance(value, dict):
        value = [value.get(k, 0) for k in ('x', 'y', 'z')]
    result = np.asarray(value, dtype=float)
    if result.shape != (3,) or not np.isfinite(result).all():
        raise ValueError('좌표는 유한한 x,y,z 세 값이어야 합니다')
    return result


def unit(v, fallback=(1., 0., 0.)):
    length = np.linalg.norm(v, axis=-1, keepdims=True)
    return np.divide(v, length, out=np.broadcast_to(fallback, v.shape).copy(), where=length > EPS)


def rotation(value):
    x, y, z = np.radians(vec(value))
    rx = np.array([[1, 0, 0], [0, math.cos(x), -math.sin(x)], [0, math.sin(x), math.cos(x)]])
    ry = np.array([[math.cos(y), 0, math.sin(y)], [0, 1, 0], [-math.sin(y), 0, math.cos(y)]])
    rz = np.array([[math.cos(z), -math.sin(z), 0], [math.sin(z), math.cos(z), 0], [0, 0, 1]])
    return rz @ ry @ rx


def capsule(name, group, a, b, radius):
    if not math.isfinite(radius) or radius < 0:
        raise ValueError('반지름은 유한한 음이 아닌 값이어야 합니다')
    return dict(name=name, group=group, kind='capsule', a=vec(a), b=vec(b), radius=radius)


def distance(shape, points):
    """Return signed distance and outward normal for every point, including inside."""
    kind = shape['kind']
    if kind == 'capsule':
        a, b = shape['a'], shape['b']
        axis = b - a
        t = np.clip((points - a) @ axis / max(float(axis @ axis), EPS), 0, 1)
        delta = points - (a + t[:, None] * axis)
        # Axis-centre ties need a perpendicular, deterministic escape direction.
        fallback = np.cross(axis, [0., 0., 1.])
        fallback = unit(fallback) if np.linalg.norm(fallback) > EPS else np.array([1., 0., 0.])
        return np.linalg.norm(delta, axis=1) - shape['radius'], unit(delta, fallback)
    local = (points - shape['center']) @ shape['rotation']
    if kind == 'cube':
        q = np.abs(local) - shape['half']
        outside = np.maximum(q, 0)
        d = np.linalg.norm(outside, axis=1) + np.minimum(np.max(q, axis=1), 0)
        normals = unit(outside * np.where(local < 0, -1., 1.))
        inside = np.max(q, axis=1) <= 0
        nearest = np.argmax(q, axis=1)
        normals[inside] = 0
        rows = np.flatnonzero(inside)
        normals[rows, nearest[rows]] = np.where(local[rows, nearest[rows]] < 0, -1., 1.)
    elif kind == 'cylinder':
        radial = np.linalg.norm(local[:, [0, 2]], axis=1)
        q = np.column_stack((radial - shape['radius'], np.abs(local[:, 1]) - shape['half'][1]))
        d = np.linalg.norm(np.maximum(q, 0), axis=1) + np.minimum(q.max(axis=1), 0)
        side = unit(np.column_stack((local[:, 0], np.zeros(len(points)), local[:, 2])))
        cap = np.column_stack((np.zeros(len(points)), np.where(local[:, 1] < 0, -1., 1.), np.zeros(len(points))))
        weights = np.maximum(q, 0)
        normals = unit(side * weights[:, :1] + cap * weights[:, 1:])
        inside = q.max(axis=1) <= 0
        normals[inside] = np.where((q[:, 0] >= q[:, 1])[inside, None], side[inside], cap[inside])
    else:
        raise ValueError('지원하지 않는 거리 모양: ' + kind)
    return d, normals @ shape['rotation'].T


def body_shapes(character, objects):
    overrides = character.get('bodyModel') or {}
    dims = {**BODY_DEFAULTS, **{k: float(v) for k, v in overrides.items() if k in BODY_DEFAULTS}}
    if any(not math.isfinite(v) or v < 0 for v in dims.values()):
        raise ValueError('bodyModel 치수는 유한한 음이 아닌 값이어야 합니다')
    pos = vec(character.get('pos', [0, 0, 0]))
    motions = character.get('motion', [])
    seat_motion = next((m.get('args', {}) for m in motions if m.get('skill') == 'sitInSeat'), None)
    seated = seat_motion is not None or str(character.get('posture', '')).lower() in ('sit', 'sitting', 'seated')
    grips = [m.get('args', {}) for m in motions if m.get('skill') == 'reachGrip' and 'p' in m.get('args', {}).get('define', {})]
    yaw = character.get('rot', [0, 0, 0])
    yaw = float(yaw) if isinstance(yaw, (int, float)) else vec(yaw)[1]
    forward = np.array([math.sin(math.radians(yaw)), 0, math.cos(math.radians(yaw))])
    seat = objects.get(str((seat_motion or {}).get('seat', '')).lstrip('@'))
    top = pos[1] + dims['seat_height']
    hip = pos + [0, dims['hip_height'], 0]
    if seated:
        if seat:
            support = vec(seat.get('pos', [0, 0, 0]))
            top = support[1] + vec(seat.get('scale', [1, 1, 1]))[1]
            hip = support.copy()
        else:
            hip = pos.copy()
        hip[1] = top + dims['seat_hip_offset']
        knee_grip = next((g for g in grips if str(g.get('anchor', '')).lower() in ('kneel', 'kneer')), None)
        if knee_grip:
            delta = vec(knee_grip['define']['p']) - hip
            delta[1] = 0
            if np.linalg.norm(delta) > EPS:
                forward = unit(delta)
    side = np.array([forward[2], 0, -forward[0]])
    chin = [g for g in grips if str(g.get('anchor', '')).lower().startswith(('chin', 'cheek'))]
    lean = np.zeros(3)
    if chin:
        lean = np.mean([vec(g['define']['p']) for g in chin], axis=0) - hip
        lean[1] = 0
        lean = unit(lean) if np.linalg.norm(lean) > EPS else np.zeros(3)
    neck = hip + [0, dims['torso_length'], 0] + (lean * dims['torso_lean'] if seated else 0)
    head = neck + [0, dims['head_offset'], 0] + (lean * dims['head_lean'] if seated else 0)
    parts = []

    def add(name, a, b, radius):
        override = overrides.get(name, {})
        a = override.get('a', a)
        b = override.get('b', a if 'a' in override else b)
        parts.append(capsule(name, 'body', a, b, float(override.get('radius', radius))))
        parts[-1]['character'] = character.get('name', 'character')

    add('torso', hip, neck, dims['torso_radius'])
    add('head', head, head, dims['head_radius'])
    for suffix, sign in (('l', 1), ('r', -1)):
        root = hip + sign * dims['hip_half_width'] * side
        knee = root + dims['thigh_length'] * forward if seated else pos + sign * dims['hip_half_width'] * side
        knee[1] = top + dims['seated_knee_offset'] if seated else pos[1] + dims['knee_height']
        ankle = knee + dims['shin_forward'] * forward if seated else knee.copy()
        ankle[1] = pos[1] + (dims['seated_ankle_height'] if seated else dims['ankle_height'])
        foot = ankle + dims['foot_length'] * forward
        foot[1] = pos[1] + dims['foot_height']
        add('thigh_' + suffix, root, knee, dims['thigh_radius'])
        add('shin_' + suffix, knee, ankle, dims['shin_radius'])
        add('foot_' + suffix, ankle, foot, dims['foot_radius'])
        shoulder = neck + [0, -dims['shoulder_drop'], 0] + sign * dims['shoulder_half_width'] * side
        grip = next((g for g in grips if str(g.get('side', '')).lower() in (suffix, 'left' if suffix == 'l' else 'right')), None)
        wrist = vec(grip['define']['p']) if grip else (knee + [0, dims['resting_hand_offset'], 0] if seated else hip + sign * dims['standing_hand_out'] * side)
        elbow = (shoulder + wrist) / 2 + [0, -dims['elbow_drop'], 0] + sign * dims['elbow_out'] * side
        add('upper_arm_' + suffix, shoulder, elbow, dims['upper_arm_radius'])
        add('forearm_' + suffix, elbow, wrist, dims['forearm_radius'])
        add('hand_' + suffix, wrist, wrist, dims['hand_radius'])
    return parts


def build_shapes(spec, warnings):
    camera = spec.get('camera', {})
    passthrough = camera.get('passThrough') or {}
    excluded = set(camera.get('solidExclude', ['floor', 'aimDot']))
    shapes = []
    objects = {o.get('name'): o for o in spec.get('objects', [])}
    if not passthrough.get('body', False):
        for character in spec.get('characters', []):
            shapes.extend(body_shapes(character, objects))
    if not passthrough.get('objects', False):
        for obj in objects.values():
            kind, name = obj.get('kind', ''), obj.get('name', '')
            if obj.get('solid') is False or name == 'floor' or name in excluded or kind in ('empty', 'plane', 'text', 'light', 'effect'):
                continue
            if kind not in ('cube', 'cylinder', 'sphere', 'capsule'):
                warnings.append('unsupported_object:' + name + ':' + kind)
                continue
            pos, size = vec(obj.get('pos', [0, 0, 0])), vec(obj.get('scale', [1, 1, 1]))
            if (size < 0).any():
                raise ValueError('scale은 음수가 될 수 없습니다')
            center = pos + [0, size[1] / 2, 0]
            radius = size[0] / 2
            if kind in ('sphere', 'capsule'):
                extent = max(0., size[1] / 2 - radius) if kind == 'capsule' else 0.
                shapes.append(capsule(name, 'objects', center - [0, extent, 0], center + [0, extent, 0], radius))
            else:
                shapes.append(dict(kind=kind, name=name, group='objects', center=center,
                                   half=size / 2, radius=radius,
                                   rotation=rotation(obj.get('rot', [0, 0, 0])) if kind == 'cube' else np.eye(3)))
    return shapes


def arc(points):
    return np.r_[0., np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))]


def camera_path(spec, at=None):
    camera = spec['camera']
    frames = int(spec.get('frames', 360))
    if frames < 1:
        raise ValueError('frames는 양수여야 합니다')
    at = np.arange(frames, dtype=float) if at is None else np.asarray(at, dtype=float)
    if camera['mode'] == 'keys':
        keys = sorted(camera.get('keys', []), key=lambda k: k['frame'])
        if not keys:
            raise ValueError('keys 카메라에 키가 없습니다')
        times = np.array([k['frame'] for k in keys], dtype=float)
        if len(times) > 1 and (np.diff(times) <= 0).any():
            raise ValueError('키 frame은 중복될 수 없습니다')
        positions = np.array([vec(k['pos']) for k in keys])
        return np.column_stack([np.interp(at, times, positions[:, i]) for i in range(3)])
    points = np.array([[p['x'], p['z']] for p in camera.get('points', [])], dtype=float)
    if len(points) < 2 or not np.isfinite(points).all():
        raise ValueError('레일 points는 유한한 점 두 개 이상이어야 합니다')
    start, end = camera.get('range', [0, frames - 1])
    if end < start:
        raise ValueError('레일 range 끝은 시작보다 작을 수 없습니다')
    u = np.clip((at - start) / max(end - start, EPS), 0, 1)
    lengths = arc(points)
    xz = np.column_stack([np.interp(u * lengths[-1], lengths, points[:, i]) for i in range(2)])
    height = camera.get('height', 1.4)
    if isinstance(height, (int, float)):
        y = np.full(len(at), float(height))
    else:
        marks = sorted(height, key=lambda h: h['t'])
        if not marks:
            raise ValueError('높이 마크가 비어 있습니다')
        y = np.interp(u, [h['t'] for h in marks], [h['height'] for h in marks])
    result = np.column_stack((xz[:, 0], y, xz[:, 1]))
    if not np.isfinite(result).all():
        raise ValueError('카메라 위치는 유한해야 합니다')
    return result


# 2026-11-07 Codex — 캡슐 근사와 다른 실제 표면은 렌더된 깊이와 실제 겨냥 경로로 보정한다.
def aim_path(spec):
    """Sample a fixed aim or a named object's metre-per-second path at 24 fps."""
    positions = camera_path(spec)
    aim = spec['camera'].get('aim')
    if isinstance(aim, list) and len(aim) == 1 and isinstance(aim[0], str) and aim[0].startswith('@'):
        target = next((obj for obj in spec.get('objects', []) if obj.get('name') == aim[0][1:]), None)
        if target is not None:
            path = target.get('path') or {}
            points = path.get('points') or []
            if points:
                points = np.array([vec(point) for point in points])
                lengths = arc(points)
                speed = float(path.get('speed', 0.))
                if not math.isfinite(speed) or speed < 0:
                    raise ValueError('path.speed는 유한한 음이 아닌 값이어야 합니다')
                travelled = np.minimum(speed * np.arange(len(positions)) / FPS, lengths[-1])
                # Repeated points add no distance; retaining the last one keeps interpolation defined.
                keep = np.r_[np.diff(lengths) > EPS, True]
                return np.column_stack([np.interp(travelled, lengths[keep], points[keep, i]) for i in range(3)])
            if 'pos' in target:
                return np.tile(vec(target['pos']), (len(positions), 1))
    elif isinstance(aim, dict) or isinstance(aim, (list, tuple)) and len(aim) == 3:
        return np.tile(vec(aim), (len(positions), 1))
    return np.tile(positions.mean(axis=0), (len(positions), 1))


# 2026-11-07 Codex — 가까운 면이 사라지는 뒷면 컬링 신호를 저해상도 실측으로 찾는다.
def depth_problems(depth_mp4: str, fps=24, near_level=235, enter=.15, leave=.02, close=.30) -> list[int]:
    if not math.isfinite(fps) or fps <= 0:
        raise ValueError('fps는 유한한 양수여야 합니다')
    decoded = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(depth_mp4),
                              '-vf', f'fps={fps},scale=92:52', '-pix_fmt', 'gray',
                              '-f', 'rawvideo', 'pipe:1'], capture_output=True, check=True)
    pixels = np.frombuffer(decoded.stdout, dtype=np.uint8)
    if not pixels.size or pixels.size % (92 * 52):
        raise ValueError('깊이 영상을 완전한 92×52 프레임으로 읽지 못했습니다')
    near = (pixels.reshape(-1, 92 * 52) > near_level).mean(axis=1)
    problems = near >= close
    lookahead = max(1, round(.25 * fps))
    for frame in np.flatnonzero(near >= enter):
        if (near[frame + 1:frame + lookahead + 1] <= leave).any():
            problems[max(0, frame - lookahead):frame + 1] = True
    return np.flatnonzero(problems).tolist()


# 2026-11-07 Codex — 시선 반대로 물러서면 몸 근사가 놓친 면에서도 겨냥점을 유지할 수 있다.
def _body_center(spec, positions):
    """2026-11-07 cctb-44: 바깥으로 밀 기준점 — 첫 인물이 sitInSeat 면 그 의자 중심, 아니면 인물 위치, 없으면 카메라 경로 무게중심."""
    objects = {o.get('name'): o for o in spec.get('objects', [])}
    for c in spec.get('characters', []):
        for m in c.get('motion', []) or []:
            seat = str(((m.get('args') or {}).get('seat')) or '')
            if m.get('skill') == 'sitInSeat' and seat.startswith('@') and seat[1:] in objects:
                return vec(objects[seat[1:]]['pos'])
        if c.get('pos') is not None:
            return vec(c['pos'])
    return positions.mean(axis=0)


def push_back(spec, frames: list[int], amount=.12):
    result = copy.deepcopy(spec)
    positions = camera_path(spec)
    mask = np.zeros(len(positions), dtype=bool)
    if not math.isfinite(amount) or amount < 0:
        raise ValueError('amount는 유한한 음이 아닌 값이어야 합니다')
    for frame in frames:
        if not isinstance(frame, (int, np.integer)) or not 0 <= frame < len(positions):
            raise ValueError('문제 frame은 spec 프레임 범위 안의 정수여야 합니다')
        mask[frame] = True
    report = dict(frames=int(mask.sum()), windows=[[round(lo / FPS, 6), round(hi / FPS, 6)]
                                                  for lo, hi in intervals(mask)], max_push_m=0.)
    if not mask.any() or amount == 0:
        return result, report
    # 2026-11-07 cctb-44 원장 #32899 실측: '바라보는 방향 반대로 물리기'는 허벅지 위를 미끄러지는 길에서 뚫는 곳을 앞으로 옮기기만 함(6.1→5.6→5.3→5.0초)
    #   → 기본은 인물 중심(앉았으면 의자 중심)에서 카메라 쪽 '수평 바깥 + 약간 위(0.35)'. 문제 구간 앞뒤 0.5초까지 넓혀 민다. COZY_PUSH_MODE=view 면 예전 방식.
    if os.environ.get('COZY_PUSH_MODE', 'radial') == 'view':
        normals = -unit(aim_path(spec) - positions)
        normals[:, 1] *= .5
        normals = unit(normals)
    else:
        center = _body_center(spec, positions)
        radial = positions - center
        radial[:, 1] = 0
        normals = unit(unit(radial) + np.array([0., .35, 0.]))
        grow = int(round(.5 * FPS))
        for lo, hi in list(intervals(mask)):
            mask[max(0, lo - grow):min(len(mask), hi + grow + 1)] = True
    required = mask.astype(float) * amount
    push = smooth_push(normals * required[:, None], normals, required)
    if result['camera']['mode'] == 'rail':
        write_rail(result, positions + push)
    else:
        # Existing keys are the only editable samples; interpolation must not create new keys.
        for key in result['camera']['keys']:
            offset = np.array([np.interp(key['frame'], np.arange(len(push)), push[:, i]) for i in range(3)])
            position = vec(key['pos']) + offset
            key['pos'] = dict(zip(('x', 'y', 'z'), map(float, position))) if isinstance(key['pos'], dict) else position.tolist()
    report['max_push_m'] = float(np.linalg.norm(camera_path(result) - positions, axis=1).max())
    return result, report


def measure(points, shapes):
    if not shapes:
        return np.empty((len(points), 0)), np.empty((len(points), 0, 3))
    values = [distance(s, points) for s in shapes]
    return np.column_stack([v[0] for v in values]), np.stack([v[1] for v in values], axis=1)


def minima(distances, shapes):
    return {group: float(distances[:, cols].min()) if cols else None
            for group in ('body', 'objects')
            for cols in [[i for i, s in enumerate(shapes) if s['group'] == group]]}


def intervals(mask):
    edges = np.diff(np.r_[False, mask, False].astype(int))
    return zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1) - 1)


def segments(distances, shapes, limits, displacements):
    result = []
    for i, shape in enumerate(shapes):
        for lo, hi in intervals(distances[:, i] < limits[i] - 1e-7):
            item = dict(t0=round(lo / FPS, 6), t1=round(hi / FPS, 6),
                        pushed_m=float(displacements[lo:hi + 1].max()), what=shape['name'],
                        group=shape['group'], min_distance=float(distances[lo:hi + 1, i].min()))
            if 'character' in shape:
                item['character'] = shape['character']
            result.append(item)
    return result


def smooth_push(raw, normals, required, times=None):
    sigma = .35 * FPS
    radius = math.ceil(3 * sigma)
    kernel = np.exp(-.5 * (np.arange(-radius, radius + 1) / sigma) ** 2)
    kernel /= kernel.sum()
    if times is None:
        # Full convolution + explicit crop also works for clips shorter than the kernel.
        smooth = np.column_stack([np.convolve(raw[:, i], kernel, 'full')[radius:radius + len(raw)] for i in range(3)])
        times = np.arange(len(raw))
    else:
        # 2026-11-07 Codex — 키 간격이 불규칙해도 초 단위 sigma를 지킨다.
        offsets = np.asarray(times)[:, None] - np.asarray(times)[None, :]
        weights = np.exp(-.5 * (offsets / sigma) ** 2)
        weights[np.abs(offsets) > radius] = 0
        smooth = (weights / weights.sum(axis=1, keepdims=True)) @ raw
    active = required > 0
    projection = np.sum(smooth * normals, axis=1)
    # 2026-11-07 Codex — 반대 법선 하나의 상쇄가 레일 전체를 수 m 밀지 않도록
    # 필요한 배율을 각 프레임에서 구하고 가우시안 최대 포락선으로 주변에 펼친다.
    aligned = active & (projection > required * .2)
    gain = np.ones(len(raw))
    gain[aligned] = np.maximum(1., required[aligned] / projection[aligned])
    envelope = gain.copy()
    for index in np.flatnonzero(gain > 1):
        offsets = np.asarray(times) - times[index]
        lobe = (gain[index] - 1) * np.exp(-.5 * (offsets / sigma) ** 2)
        lobe[np.abs(offsets) > radius] = 0
        envelope = np.maximum(envelope, 1 + lobe)
    smooth *= envelope[:, None]
    # Conflicting normals cannot share one direction. A local residual is the
    # minimum projection satisfying that frame; later passes check all shapes.
    residual = np.maximum(required - np.sum(smooth * normals, axis=1), 0.)
    # 2026-11-07 Codex — 안전 프레임의 가우시안 꼬리를 법선에 맞춰 잘라내지 않는다.
    residual[~active] = 0.
    smooth += normals * residual[:, None]
    return smooth


def write_rail(spec, corrected):
    camera = spec['camera']
    start, end = camera.get('range', [0, len(corrected) - 1])
    # Only the moving interval belongs to the rail; holds must not consume length.
    times = np.unique(np.r_[start, np.arange(math.ceil(start), math.floor(end) + 1), end])
    moving = np.column_stack([np.interp(times, np.arange(len(corrected)), corrected[:, i]) for i in range(3)])
    lengths = arc(moving[:, [0, 2]])
    count = min(512, max(2, math.ceil(len(corrected) / 2)))
    if lengths[-1] < EPS:
        camera['points'] = [dict(x=float(moving[0, 0]), z=float(moving[0, 2]))] * 2
        # Vertical-only rail: keep height parametrized by time even without xz length.
        u = np.linspace(0, 1, len(moving))
    else:
        u = lengths / lengths[-1]
        uniform = np.linspace(0, 1, count)
        camera['points'] = [dict(x=float(x), z=float(z)) for x, z in
                            np.column_stack([np.interp(uniform, u, moving[:, i]) for i in (0, 2)])]
    # Max-error splitting spends the eight available marks on the largest bends.
    unique, indices = np.unique(u, return_index=True)
    height = np.maximum(.05, moving[indices, 1])
    if len(unique) == 1:
        camera['height'] = [dict(t=0., height=float(height[0])), dict(t=1., height=float(height[0]))]
        return
    chosen = [0, len(unique) - 1]
    while len(chosen) < min(8, len(unique)):
        approximation = np.interp(unique, unique[chosen], height[chosen])
        error = np.abs(height - approximation)
        error[chosen] = -1
        index = int(np.argmax(error))
        if error[index] < 1e-6:
            break
        chosen = sorted([*chosen, index])
    camera['height'] = [dict(t=float(unique[i]), height=float(height[i])) for i in chosen]


def acceleration(points):
    return float(np.linalg.norm(np.diff(points, n=2, axis=0), axis=1).max() * FPS ** 2) if len(points) > 2 else 0.


def fix_spec(spec: dict) -> tuple[dict, dict]:
    """Return an independent spec and JSON-safe report; input is never mutated."""
    result = copy.deepcopy(spec)
    report = dict(ok=True, changed=False, min_before=dict(body=None, objects=None),
                  min_after=dict(body=None, objects=None), segments=[], remaining_segments=[],
                  static_body_assumption=True, warnings=[], iterations=0,
                  max_displacement_m=0., accel_max_before=0., accel_max_after=0.)
    camera = result.get('camera', {})
    passthrough = camera.get('passThrough') or {}
    if passthrough.get('body', False) and passthrough.get('objects', False):
        report['skipped'] = 'passThrough'
        return result, report
    if camera.get('mode') not in ('rail', 'keys'):
        report['unsupported_mode'] = camera.get('mode')
        report['warnings'].append('unsupported_mode')
        return result, report
    shapes = build_shapes(result, report['warnings'])
    clearance = {**dict(body=.12, objects=.06), **(camera.get('clearanceM') or {})}
    if any(not math.isfinite(float(v)) or float(v) < 0 for v in clearance.values()):
        raise ValueError('clearanceM은 유한한 음이 아닌 값이어야 합니다')
    limits = np.array([float(clearance[s['group']]) for s in shapes])
    original = camera_path(result)
    before, _ = measure(original, shapes)
    report['min_before'] = minima(before, shapes)
    report['accel_max_before'] = acceleration(original)
    current = original.copy()
    for iteration in range(6):
        # Keys may only move existing key positions. Inter-key hits are warned below.
        at = np.array([k['frame'] for k in camera['keys']], dtype=float) if camera['mode'] == 'keys' else None
        points = camera_path(result, at) if at is not None else current
        d, normals = measure(points, shapes)
        deficits = limits - d
        required = np.zeros(len(points))
        direction = np.zeros_like(points)
        if shapes:
            nearest = np.argmax(deficits, axis=1)
            required = np.maximum(deficits[np.arange(len(points)), nearest], 0.)
            direction = normals[np.arange(len(points)), nearest].copy()
        floor = .05 - points[:, 1]
        floor_wins = floor > required
        direction[floor_wins] = [0, 1, 0]
        required = np.maximum(required, floor)
        if required.max() < 1e-7:
            break
        active = required > 0
        required[active] += .012  # Small headroom pays for bounded rail/height compression.
        surface_normal = direction.copy()
        direction[:, 1] *= .5
        direction = unit(direction)
        raw = direction * np.divide(required, np.maximum(np.sum(direction * surface_normal, axis=1), .1))[:, None]
        if camera['mode'] == 'rail':
            push = smooth_push(raw, surface_normal, required)
            points += push
            points[:, 1] = np.maximum(points[:, 1], .05)
            write_rail(result, points)
        else:
            # 2026-11-07 Codex — 키 추가 없이 실제 프레임 시각으로 부드럽게 보정한다.
            points += smooth_push(raw, surface_normal, required, at)
            points[:, 1] = np.maximum(points[:, 1], .05)
            for key, position in zip(camera['keys'], points):
                key['pos'] = dict(zip(('x', 'y', 'z'), map(float, position))) if isinstance(key['pos'], dict) else position.tolist()
        report['iterations'] = iteration + 1
        current = camera_path(result)
    after, _ = measure(current, shapes)
    displacement = np.linalg.norm(current - original, axis=1)
    report.update(changed=result != spec, min_after=minima(after, shapes),
                  segments=segments(before, shapes, limits, displacement),
                  remaining_segments=segments(after, shapes, limits, displacement),
                  max_displacement_m=float(displacement.max()), accel_max_after=acceleration(current),
                  min_height_before=float(original[:, 1].min()), min_height_after=float(current[:, 1].min()))
    if report['remaining_segments']:
        report['warnings'].append('remaining_collisions')
        if camera['mode'] == 'keys':
            report['warnings'].append('key_interpolation_collision: existing keys only; no keys added')
    if (current[:, 1] < .05 - 1e-7).any():
        report['warnings'].append('remaining_floor_clearance')
    if report['accel_max_after'] > max(report['accel_max_before'] * 1.5, report['accel_max_before'] + .5):
        report['warnings'].append('acceleration_increased')
    return result, report


def main():
    parser = argparse.ArgumentParser(description='CozyClay 카메라 인체·사물 우회')
    parser.add_argument('spec')
    parser.add_argument('--out', required=True)
    parser.add_argument('--report')
    args = parser.parse_args()
    fixed, report = fix_spec(json.loads(Path(args.spec).read_text(encoding='utf-8')))
    out = Path(args.out)
    if out.resolve() == Path(args.spec).resolve():
        raise ValueError('--out은 원본 spec과 다른 경로여야 합니다')
    if args.report and Path(args.report).resolve() in (out.resolve(), Path(args.spec).resolve()):
        raise ValueError('--report는 입력·출력 spec과 다른 경로여야 합니다')
    report['out'] = str(out)
    out.write_text(json.dumps(fixed, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    if args.report:
        Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, allow_nan=False))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps(dict(ok=False, error=str(error)), ensure_ascii=False))
        sys.exit(1)
