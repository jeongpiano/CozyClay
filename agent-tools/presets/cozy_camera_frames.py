# 목적: 열린 CozyClay 편집기의 샷 카메라를 프레임마다 렌더러 값 그대로(위치·바라보는 점·화각) JSON 으로 뽑는다
# 실행: python3 cozy_camera_frames.py --workspace <편집기 handle> --out cam.json [--step 1] [--shot <id>]  (Claude·Codex·대시보드)
# 요청: 2026-11-07 obsidian-ec(원장 #32866·#32890 "어려운 카메라 무빙을 코지클레이로 짠 뒤 잘 따르게") — 시각별 카메라 문장 자동 생성(core/camera_text.py) 재료
# 연결: cclay live operate --frame N 으로 재생 위치를 옮기고 cclay live verify --checks framing 의 geometry.shots[].camera(position·lookAt)를 읽음
#       — 레일·크레인·겨냥 해석을 다시 짜지 않고 편집기가 실제 쓰는 값. 화각은 샷 focalMm → 세로 화각(16:9, 풀프레임 36×24 기준 렌즈)
# 이력: 2026-11-07 cctb-44 처음. 되돌리기: 파일 삭제
import argparse, json, math, subprocess, sys
from pathlib import Path

CLAY = Path(__file__).resolve().parent.parent
BIN = 'node_modules/.bin/cclay'


def live(*args, workspace):
    r = subprocess.run([BIN, 'live', *map(str, args), '--workspace', workspace], cwd=CLAY, text=True, capture_output=True)
    d = json.loads(r.stdout or '{}')
    if r.returncode or d.get('ok') is False:
        raise RuntimeError((d.get('error') or {}).get('message') or r.stderr.strip() or r.stdout[:300])
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--workspace', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--step', type=int, default=1)
    ap.add_argument('--shot', default='')
    a = ap.parse_args()
    shots = live('inspect', '--scope', 'shot', workspace=a.workspace)['document']['shots']
    shot = next((s for s in shots if s['id'] == a.shot), shots[0]) if shots else None
    if not shot:
        raise SystemExit('샷이 없습니다')
    ents = live('inspect', '--scope', 'entities', workspace=a.workspace)['entities']
    chars = [e for e in ents if e['kind'] == 'character']
    target = chars[0]['id'] if chars else next(e['id'] for e in ents if e['kind'] == 'object' and e.get('name') != 'floor')
    focal = float((shot.get('camera') or {}).get('focalMm') or 35)
    vfov = math.degrees(2 * math.atan(24 / (2 * focal)))   # 풀프레임 세로 24mm 기준
    rows = []
    for f in range(int(shot['startFrame']), int(shot['endFrame']) + 1, max(1, a.step)):
        live('operate', '--frame', f, '--mode', 'camera', workspace=a.workspace)
        v = live('verify', '--targets', target, '--checks', 'framing', '--range', f'{f}:{f + 1}', workspace=a.workspace)
        cam = next((s['camera'] for s in v['geometry']['shots'] if s['shotId'] == shot['id']), v['geometry']['shots'][0]['camera'])
        p, t = cam['position'], cam['lookAt']
        rows.append({'frame': f, 'pos': [p['x'], p['y'], p['z']], 'target': [t['x'], t['y'], t['z']], 'fov': round(vfov, 3)})
    out = {'source': 'renderer (cclay live verify geometry, per frame)', 'shot': shot['id'], 'shotName': shot.get('name'),
           'fps': 24, 'focalMm': focal, 'vfovDeg': round(vfov, 3), 'units': 'metres, +Y up',
           'subjects': [{'id': c['id'], 'name': c.get('name'), 'position': c.get('position'), 'yawDeg': c.get('yawDeg'),
                         'posture': 'seated' if any('sit' in json.dumps(c).lower() for _ in [0]) else None} for c in chars],
           'frames': rows}
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps({'ok': True, 'out': a.out, 'frames': len(rows)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
