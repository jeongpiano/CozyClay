// 목적: 레일과 바라보기 구역 명령의 검증·저장·영수증을 한 곳에서 처리한다.
// 실행: commands/shot.js가 명령 버스에 등록한다.
// 요청: 2026-11-07 원장, 협업 1107-14ed67 — 구역만 편집하는 액션 제공.
// 연결: camera-block.js, camera-look-zones.js; 외부 설정 없음.
// 이력·되돌리기: 구역은 null로 지우고 명령 버스에서 한 번에 undo한다.
import { createCameraBlock, updateCameraBlock } from '../camera-block.js';
import { railFollowForNewGeometry } from '../camera-rail-schedule.js';
import { buildRail } from '../camera-follow.js';
import { TIMELINE_FPS } from '../timeline-defaults.js';
import { fail } from './shared.js';

const zoneNote = zones => zones?.length ? `look zones: ${zones.map(zone => `${zone.id} ${zone.range ? `${Math.round(zone.range.t0 * 100)}–${Math.round(zone.range.t1 * 100)}%` : ''}${zone.near ? ` near (${zone.near.x}, ${zone.near.z}) r=${zone.near.radius} m` : ''} → ${zone.target.ids?.join(', ') ?? `(${Object.values(zone.target.point).join(', ')})`}`).join('; ')}; ` : '';

export function railCommands({ ports, shotOf, patchShot }) {
  function checkTargets(zones) {
    const cast = [...ports.state().characters, ...ports.state().objects];
    for (const zone of zones ?? []) for (const id of zone.target?.ids ?? []) {
      if (!cast.some(row => row.id === id)) fail('STALE_TARGET', `Look zone target ${id} is not a character or object in this scene.`);
    }
  }
  // A rail owns the frames it covers, so the camera keys there go. Its answer
  // names the move it makes: length, speed, height, aim and lens.
  function setRail({ shotId, points, height, aim, aimHeight, focalMm, lookZones }) {
    const shot = shotOf(shotId), cast = [...ports.state().characters, ...ports.state().objects];
    for (const id of Array.isArray(aim) ? aim : []) if (!cast.some(row => row.id === id)) fail('STALE_TARGET', `Aim ${id} is not a character or object in this scene.`);
    checkTargets(lookZones);
    const railFollow = railFollowForNewGeometry(shot.camera?.railFollow, shot.endFrame - shot.startFrame + 1);
    const span = railFollow?.mode === 'range' ? [shot.startFrame + railFollow.startFrame, shot.startFrame + railFollow.endFrame] : [shot.startFrame, shot.endFrame];
    const patch = { cameraRail: points, mode: 'rail', railFollow, ...(lookZones === undefined ? {} : { lookZones }), ...(focalMm === undefined ? {} : { focalMm }),
      ...(height === undefined ? {} : { craneHeight: { points: typeof height === 'number' ? [{ t: 0, height }, { t: 1, height }] : height } }),
      ...(aim === undefined && aimHeight === undefined ? {} : { aim: aimOf(aim === undefined ? createCameraBlock(shot.camera).aim : aim && (Array.isArray(aim) ? { ids: aim } : { point: aim }), aimHeight) }) };
    const keys = shot.cameraKeys.filter(key => key.frame < span[0] || key.frame > span[1]);
    patchShot(shotId, row => ({ ...row, cameraKeys: keys, camera: updateCameraBlock(row.camera, patch) }));
    const camera = createCameraBlock(shotOf(shotId).camera), metres = buildRail(camera.cameraRail)?.length ?? 0, seconds = (span[1] - span[0] + 1) / TIMELINE_FPS;
    const heights = camera.craneHeight?.points.map(point => point.height) ?? [camera.followCam.height], speed = metres / seconds;
    const aimed = camera.aim?.ids ? `${camera.aim.ids.join(', ')}${camera.aim.height === undefined ? '' : ` at ${camera.aim.height.toFixed(2)} m`}` : (camera.aim ? `(${['x', 'y', 'z'].map(axis => camera.aim.point[axis].toFixed(2)).join(', ')})` : 'the follow subject');
    const note = `${zoneNote(camera.lookZones)}${metres.toFixed(1)} m over ${seconds.toFixed(1)} s (${speed.toFixed(2)} m/s), height ${[...new Set([heights[0], heights.at(-1)])].map(h => h.toFixed(2)).join('-')} m, aim ${aimed}, ${camera.focalMm ? `${camera.focalMm} mm` : 'scene lens'}${shot.cameraKeys.length > keys.length ? `; ${shot.cameraKeys.length - keys.length} camera keys removed` : ''}.`;
    const fast = speed > camera.followCam.maxDollySpeed ? [{ code: 'RAIL_TOO_FAST', id: shotId, message: `${speed.toFixed(1)} m/s is past the ${camera.followCam.maxDollySpeed} m/s dolly cap, so the camera lags; lengthen the shot or the rail.` }] : [];
    return { note, warnings: fast };
  }
  // aimHeight moves a cast aim off the chest to a world height (a whole body, a face).
  const aimOf = (aim, aimHeight) => (aim?.ids && aimHeight !== undefined ? { ids: aim.ids, height: aimHeight } : aim);
  return {
    'shot.setCameraRail': setRail,
    'shot.setLookZones': ({ shotId, lookZones }) => {
      const shot = shotOf(shotId);
      if (!createCameraBlock(shot.camera).cameraRail) fail('TARGET_NOT_READY', `${shot.name || shotId} has no camera rail; lay one with shot.setCameraRail.`);
      checkTargets(lookZones);
      patchShot(shotId, row => ({ ...row, camera: updateCameraBlock(row.camera, { lookZones }) }));
      return { note: zoneNote(createCameraBlock(shotOf(shotId).camera).lookZones) || 'look zones: cleared.' };
    },
  };
}
