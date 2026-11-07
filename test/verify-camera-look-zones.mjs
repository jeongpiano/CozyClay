// 목적: 구역 겨냥·기존 레일 호환성·명령 저장·내보내기 공통 경로를 검증한다.
// 실행: node test/verify-camera-look-zones.mjs 또는 tools/run-tests.mjs.
// 요청: 2026-11-07 원장, 협업 1107-14ed67 — 무릎 근처 목표를 보다가 기본 겨냥으로 복귀.
// 연결: camera-look-zones.js, commands/shot-rail.js, SPEC_look_zones.md.
// 이력·되돌리기: 해당 구현과 함께 제거; 실행은 장면 파일이나 편집기를 변경하지 않는다.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { cloneLookZones, lookZoneWeights, lookZoneRailSpans, lookZoneAimOverride } from '../src/camera-look-zones.js';
import { createCameraBlock, updateCameraBlock, removeCameraRail } from '../src/camera-block.js';
import { buildRail, buildRailFollowTrack } from '../src/camera-follow.js';
import { buildShotCameraTracks, castAimPoint } from '../src/camera-direction.js';
import { shotGeometryFacts } from '../src/studio-geometry-facts.js';
import { sampleAt } from '../src/sample-at.js';
import { playbackSceneWithTrack } from '../src/stage-gizmo.js';
import { createShotAuthoringDocument } from '../src/shot-authoring.js';
import { shotsFixture } from './bus/shots-fixture.mjs';

const points = [{ x: -4, z: 4 }, { x: 4, z: 4 }], rail = buildRail(points), fps = 24, frames = 480;
const subjectTrack = Array.from({ length: frames }, (_, f) => ({ x: 0.08 * Math.sin(f / 60), z: 0 }));
const camera = createCameraBlock({ mode: 'rail', cameraRail: points, followCam: { lead: 0 } });
const shot = { id: 'shot-z', name: 'Zones', startFrame: 0, endFrame: frames - 1, cameraKeys: [], camera };
const target = { x: 0.3, y: 0.45, z: 0.3 };
const zone = { id: 'z1', target: { point: target }, range: { t0: 0.3, t1: 0.55 }, feather: 0.08 };
const compile = (lookZones, extra = {}) => buildShotCameraTracks({ shots: [{ ...shot, camera: updateCameraBlock(camera, { lookZones, ...extra }) }], subjectTrack, fps });
const base = compile(), zoned = compile([zone]);
const direction = s => [-Math.sin(s.yaw) * Math.cos(s.pitch), Math.sin(s.pitch), -Math.cos(s.yaw) * Math.cos(s.pitch)];
const error = (s, at) => {
  const v = [at.x - s.pos.x, at.y - s.pos.y, at.z - s.pos.z], d = direction(s);
  return Math.acos(Math.max(-1, Math.min(1, d.reduce((sum, c, i) => sum + c * v[i], 0) / Math.hypot(...v)))) * 180 / Math.PI;
};
const angleDifference = (a, b) => Math.acos(Math.max(-1, Math.min(1, direction(a).reduce((sum, v, i) => sum + v * direction(b)[i], 0)))) * 180 / Math.PI;
const arc = (a, b) => Math.abs(Math.atan2(Math.sin(a - b), Math.cos(a - b)));
const maxPan = track => Math.max(...track.slice(1).map((s, i) => arc(s.yaw, track[i].yaw)));

test('no zones retains the old block bytes and exact rail tracks with and without a fixed aim', () => {
  assert.equal('lookZones' in camera, false);
  for (const lookZones of [undefined, [], null, [{}]]) {
    assert.equal(JSON.stringify(updateCameraBlock(camera, { lookZones })), JSON.stringify(camera));
    assert.deepEqual(compile(lookZones), base);
  }
  assert.deepEqual(base, buildRailFollowTrack(subjectTrack, fps, rail, { ...camera.followCam, craneHeight: camera.craneHeight, dollyTiming: camera.dollyTiming, initialDir: { x: 0, z: 1 } }));
  const aim = { point: { x: 0, y: 1, z: 0 } };
  const aimed = compile(undefined, { aim });
  assert.deepEqual(aimed, buildRailFollowTrack(subjectTrack.map(() => aim.point), fps, rail, { ...camera.followCam, craneHeight: camera.craneHeight, dollyTiming: camera.dollyTiming, initialDir: { x: 0, z: 1 }, aimPerFrame: true, distanceInfluence: 0, pitchOffsetDeg: 0 }));
  assert.deepEqual(compile([], { aim }), aimed);
  assert.deepEqual(buildRailFollowTrack(subjectTrack, fps, rail, { aimOverride: () => null }), buildRailFollowTrack(subjectTrack, fps, rail));
  assert.deepEqual(compile([{ ...zone, strength: 0 }]), base);
});

test('range aims at the target after settling, restores default aim, and never changes dolly positions', () => {
  assert.deepEqual(zoned.map(s => [s.pos, s.s]), base.map(s => [s.pos, s.s]));
  assert.deepEqual(compile([zone], { aim: { point: { x: 0, y: 1, z: 0 } } }).map(s => s.pos), compile(undefined, { aim: { point: { x: 0, y: 1, z: 0 } } }).map(s => s.pos));
  const middle = base.findIndex(s => s.s / rail.length > 0.45);
  assert.ok(error(zoned[middle], target) < 3, `settled error ${error(zoned[middle], target)}`);
  assert.ok(angleDifference(zoned[20], base[20]) < 0.5);
  assert.ok(angleDifference(zoned[430], base[430]) < 0.5);
  const tilted = compile([zone], { followCam: { pitchOffsetDeg: 15 } });
  const defaultTilt = compile(undefined, { followCam: { pitchOffsetDeg: 15 } });
  assert.ok(error(tilted[middle], target) < 3, 'the zone temporarily overrides the default composition tilt');
  assert.ok(angleDifference(tilted[430], defaultTilt[430]) < 0.5);
  assert.ok(maxPan(zoned) <= maxPan(base) * 3, `${maxPan(zoned)} vs ${maxPan(base)}`);
  const sharp = compile([{ ...zone, feather: 0 }]);
  assert.ok(maxPan(sharp) < 3 * Math.PI / 180);
  assert.ok(Math.max(...sharp.slice(1).map((s, i) => Math.abs(s.pitch - sharp[i].pitch))) < 5 * Math.PI / 180, 'height transitions also keep the aim spring');
});

test('near uses horizontal camera distance and range and near multiply', () => {
  const nearZone = { id: 'near', target: { point: target }, near: { x: 0, z: 4, radius: 1.2 } };
  const track = compile([nearZone]);
  const middle = base.findIndex(s => s.s / rail.length > 0.52);
  assert.ok(error(track[middle], target) < 3);
  assert.ok(angleDifference(track[10], base[10]) < 0.5);
  assert.ok(angleDifference(track[450], base[450]) < 0.5);
  assert.deepEqual(track.map(s => s.pos), base.map(s => s.pos));
  const samples = [{ s: rail.length * 0.25, pos: { x: 0, y: 100, z: 4 } }, { s: rail.length * 0.45, pos: { x: 1.325, y: 100, z: 4 } }];
  assert.deepEqual(lookZoneWeights(samples, rail, [nearZone]), [1, 0.5]);
  const rangeOnly = lookZoneWeights(samples, rail, [zone]);
  const both = lookZoneWeights(samples, rail, [{ ...zone, near: nearZone.near, feather: 0.25 }]);
  assert.ok(rangeOnly[0] > 0 && rangeOnly[0] < 1);
  assert.equal(both[1], 0.5);
  assert.deepEqual(lookZoneWeights([null], rail, [zone]), [0]);
  assert.deepEqual(lookZoneRailSpans([zone, nearZone]), [{ id: 'z1', t0: 0.3, t1: 0.55, feather: 0.08 }]);
});

test('overlap is a normalized weighted average with exact default target outside all zones', () => {
  const samples = [{ s: rail.length * 0.4, pos: { x: 0, z: 4 } }, { s: 0, pos: { x: -4, z: 4 } }];
  const zones = [{ ...zone, transition: 0 }, { ...zone, id: 'z2', transition: 0, target: { point: { x: 2.3, y: 0.45, z: 0.3 } } }];
  const blend = lookZoneAimOverride(samples, rail, zones, t => t.point), fallback = { x: 0, y: 1.35, z: 0 };
  for (const [axis, value] of Object.entries({ x: 1.3, y: 0.45, z: 0.3 })) assert.ok(Math.abs(blend(0, fallback)[axis] - value) < 1e-12);
  assert.equal(blend(1, fallback), fallback, 'outside zones is exactly the default target');
  assert.deepEqual(lookZoneWeights(samples, rail, zones), [1, 0]);
  assert.deepEqual(compile([{ ...zone, target: { ids: ['gone'] } }]), base, 'missing runtime targets restore default aim');
});

test('animated cast targets and explicit height are resolved at absolute timeline frames', () => {
  const start = 24, end = 383, cast = { objects: [{ id: 'monster', x: 0.3, y: 0.1, z: 0.3, height: 0.7 }] };
  const calls = [];
  const aimed = buildShotCameraTracks({ shots: [{ ...shot, startFrame: start, endFrame: end, camera: updateCameraBlock(camera, { lookZones: [{ id: 'moving', target: { ids: ['monster'] }, height: 0.45, range: { t0: 0, t1: 1 } }] }) }], subjectTrack, fps,
    aimAt: (id, f) => { calls.push(f); return { ...castAimPoint(id, f, cast), x: 0.3 + 0.2 * Math.sin(f / 80) }; } });
  assert.equal(aimed[start - 1], null);
  assert.equal(aimed[end + 1], null);
  assert.ok(Math.min(...calls) >= start && Math.max(...calls) <= end);
  const f = 250;
  assert.ok(error(aimed[f], { x: 0.3 + 0.2 * Math.sin(f / 80), y: 0.45, z: 0.3 }) < 3);
});

test('normalization clamps, rejects malformed data, caps at 8 and owns nested data', () => {
  const clean = cloneLookZones([null, {}, { ...zone, id: '' }, { ...zone, target: { ids: [] } }, { ...zone, range: { t0: 0.7, t1: 0.2 } },
    { ...zone, range: undefined, near: { x: 0, z: 0, radius: 0 } }, { ...zone, feather: -1, strength: 4, range: { t0: -2, t1: 4 } }]);
  assert.deepEqual(clean, [{ ...zone, feather: 0, strength: 1, range: { t0: 0, t1: 1 } }]);
  const nine = Array.from({ length: 9 }, (_, i) => ({ ...zone, id: `z${i}` }));
  assert.equal(cloneLookZones(nine).length, 8);
  const source = [{ ...zone, target: { ids: ['a', 'a', '', 7, 'b', 'c', 'd', 'e'] } }];
  assert.deepEqual(cloneLookZones(source)[0].target.ids, ['a', 'b', 'c', 'd']);
  clean[0].target.point.x = 99;
  assert.equal(zone.target.point.x, 0.3);
  assert.equal('lookZones' in createCameraBlock({ lookZones: [zone] }), false);
  assert.equal('lookZones' in removeCameraRail(updateCameraBlock(camera, { lookZones: [zone] })), false);
});

test('commands round-trip through the owned shot document, refuse stale cast, undo and clear', () => {
  const f = shotsFixture(), args = { shotId: 'shot-a' }, zones = [{ ...zone, target: { ids: ['actor-a'] }, height: 0.45 }];
  try {
    assert.equal(f.run('shot.setLookZones', { ...args, lookZones: zones }, 'agent').code, 'TARGET_NOT_READY');
    assert.equal(f.run('shot.setCameraRail', { ...args, points, lookZones: zones }, 'agent').ok, true);
    const saved = () => createShotAuthoringDocument({ shots: f.shots.read(), frameCount: 120 }).shots[0].camera;
    assert.deepEqual(saved().lookZones, cloneLookZones(zones));
    const before = saved(), receipt = f.run('shot.setLookZones', { ...args, lookZones: [zone] }, 'agent');
    assert.equal(receipt.ok, true, JSON.stringify(receipt));
    assert.match(receipt.summary, /look zones: z1 30–55% →/);
    assert.deepEqual(saved().lookZones, cloneLookZones([zone]));
    assert.equal(f.run('edit.undo', { receiptId: receipt.receiptId }).status, 'undone');
    assert.deepEqual(saved(), before);
    for (const action of ['shot.setLookZones', 'shot.setCameraRail']) {
      const refused = f.run(action, { ...args, ...(action.endsWith('Rail') ? { points } : {}), lookZones: [{ ...zone, target: { ids: ['gone'] } }] }, 'agent');
      assert.equal(refused.code, 'STALE_TARGET', JSON.stringify(refused));
      assert.deepEqual(saved(), before);
    }
    assert.equal(f.run('shot.setCameraRail', { ...args, points }, 'agent').ok, true);
    assert.deepEqual(saved().lookZones, before.lookZones, 'omitted zones survive redrawing');
    for (const action of ['shot.setLookZones', 'shot.setCameraRail']) {
      assert.equal(f.run(action, { ...args, ...(action.endsWith('Rail') ? { points } : {}), lookZones: null }, 'agent').ok, true);
      assert.equal('lookZones' in saved(), false);
    }
  } finally { f.dispose(); }
});

test('framing geometry and Depth share playback camera sampling, including off-playhead rails', () => {
  const authored = { ...shot, camera: updateCameraBlock(camera, { lookZones: [zone] }) };
  const scene = playbackSceneWithTrack({ frameCount: frames }, subjectTrack, zoned), frame = 220;
  const sampleStateAt = f => {
    const s = sampleAt(scene, authored, f).camera, d = direction(s);
    return { camera: { position: s.pos, lookAt: { x: s.pos.x + d[0], y: s.pos.y + d[1], z: s.pos.z + d[2] } } };
  };
  const state = { frame, characters: [], objects: [], camera: { position: { x: 99, y: 99, z: 99 }, lookAt: target }, shotDocument: { shots: [authored] } };
  const facts = shotGeometryFacts(state, { ports: { sampleStateAt } }).shots[0].camera;
  const expected = sampleStateAt(frame).camera;
  for (const axis of ['x', 'y', 'z']) assert.ok(Math.abs(facts.lookAt[axis] - expected.lookAt[axis]) <= 0.0005);
  assert.notEqual(facts.position.x, 99);
  assert.ok(shotGeometryFacts({ ...state, frame: 999 }, { ports: { sampleStateAt } }).shots[0].camera);
  const app = readFileSync(new URL('../src/App.jsx', import.meta.url), 'utf8');
  assert.match(app, /sampleAt\(playbackScene, shot, frame\)/);
  assert.match(app, /playbackSceneWithTrack\(playbackSceneBase, subjectTrack, followTrack\)/);
  assert.match(readFileSync(new URL('../src/studio-app-binding.js', import.meta.url), 'utf8'), /shotGeometryFacts\(scene,.*sampleStateAt: ports.sampleStateAt/);
});

// 2026-11-07 cctb-44 원장 #32958: 전환 시간(transition) — 길수록 천천히, 구역에서 먼 프레임은 정확히 기본 겨냥
test('transition spreads the swing symmetrically and longer transitions swing slower', () => {
  const n = 240, samples = Array.from({ length: n }, (_, f) => ({ s: rail.length * f / (n - 1), pos: { x: 0, z: 4 } }));
  const fallback = { x: 0, y: 1.35, z: 0 };
  const influence = transition => { const blend = lookZoneAimOverride(samples, rail, [{ ...zone, feather: 0, transition }], t => t.point, 24); return samples.map((_, f) => blend(f, fallback).influence ?? 0); };
  const hard = influence(0), soft = influence(0.8), slow = influence(2);
  const rise = w => w.filter(v => v > 0.1 && v < 0.9).length;
  assert.ok(rise(hard) <= 1, 'transition 0 keeps the hard edge');
  assert.ok(rise(soft) >= 24 && rise(soft) <= 60, `0.8 s ~19 frames per edge, two edges, got ${rise(soft)}`);
  assert.ok(rise(slow) > rise(soft) * 2, 'a 2 s transition swings slower');
  assert.equal(soft[0], 0); assert.equal(soft[n - 1], 0);
  const mid = Math.round(n * 0.425); assert.ok(soft[mid] > 0.99, 'the middle of the zone still fully reaches the target');
  const blend = lookZoneAimOverride(samples, rail, [{ ...zone, transition: 0.8 }], t => t.point, 24);
  assert.equal(blend(0, fallback), fallback, 'far frames are exactly the default aim');
});
