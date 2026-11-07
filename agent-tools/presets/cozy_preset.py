# 목적: CozyClay 장면 프리셋을 조회하고 명령으로 재현하거나 저장한다.
# 실행: 사용자가 Python 3 명령줄에서 직접 실행한다.
# 요청: 2026-11-06 사용자, 반복 장면을 빠르게 불러오기 위해 작성 (1106-db2473).
# 연결: presets/library/*.json, ../node_modules/.bin/cclay, 로컬 CozyClay 허브.
# 이력·되돌리기: 1106-db2473; 사용을 중지하려면 이 파일과 library를 제거한다.
# 2026-11-08 Codex — 드라마 카메라 선택 지원; 복원: cozy_preset.py.bak-20261108-drama.
import argparse
import ast
import json
import operator
import re
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CLAY = ROOT.parent
LIBRARY = ROOT / 'library'
BIN = 'node_modules/.bin/cclay'
REF = re.compile(r'@([\w.-]+)', re.UNICODE)
PARAM = re.compile(r'^\$\{([A-Za-z_]\w*)\}$')


def path_for(name):
    if not re.fullmatch(r'[\w-]+', name):
        raise ValueError('프리셋 이름에는 문자, 숫자, 밑줄, 하이픈만 쓸 수 있습니다')
    return LIBRARY / (name + '.json')


def load(name):
    return json.loads(path_for(name).read_text(encoding='utf-8'))


def numeric(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError('매개변수는 숫자여야 합니다')
    return value


def expression(source, params):
    ops = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}
    def visit(node):
        if isinstance(node, ast.Constant):
            return numeric(node.value)
        if isinstance(node, ast.Name) and node.id in params:
            return numeric(params[node.id])
        if isinstance(node, ast.BinOp) and type(node.op) in ops:
            return ops[type(node.op)](visit(node.left), visit(node.right))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            return (+visit(node.operand) if isinstance(node.op, ast.UAdd) else -visit(node.operand))
        raise ValueError('허용되지 않은 수식: ' + source)
    return numeric(visit(ast.parse(source, mode='eval').body))


def substitute(value, params):
    if isinstance(value, dict):
        if set(value) == {'$expr'}:
            return expression(value['$expr'], params)
        return {k: substitute(v, params) for k, v in value.items()}
    if isinstance(value, list):
        return [substitute(v, params) for v in value]
    if isinstance(value, str) and (m := PARAM.fullmatch(value)):
        return numeric(params[m.group(1)])
    return value


def references(value, names):
    if isinstance(value, dict):
        return {k: references(v, names) for k, v in value.items()}
    if isinstance(value, list):
        return [references(v, names) for v in value]
    if isinstance(value, str):
        def replace(match):
            if match.group(1) not in names:
                raise ValueError('알 수 없는 이름 참조: ' + match.group(0))
            return names[match.group(1)]
        return REF.sub(replace, value)
    return value


def xyz(value):
    return dict(zip(('x', 'y', 'z'), value)) if isinstance(value, list) else value


class Live:
    def __init__(self, workspace=None, dry=False):
        self.workspace, self.dry = workspace, dry

    def call(self, *args, read=False):
        cmd = [BIN, 'live', *map(str, args)]
        if self.workspace:
            cmd += ['--workspace', self.workspace]
        print(shlex.join(cmd), file=sys.stdout if self.dry else sys.stderr, flush=True)
        if self.dry:
            return {}
        result = subprocess.run(cmd, cwd=CLAY, text=True, capture_output=True)
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or 'cclay 응답이 JSON이 아닙니다')
        if result.returncode or data.get('ok') is False:
            error = data.get('error', {})
            raise RuntimeError(error.get('message', str(data)))
        return data.get('value', data)

    def run(self, action, args):
        # 2026-11-06 cctb-44: 인물 추가 직후 motion.compile 이 "changed while the job was running" 으로 거절되는 일 — 잠깐 쉬고 3번까지 다시
        import time as _t
        for _i in range(4):
            try:
                return self.call('run', action, '--args', json.dumps(args, ensure_ascii=False, separators=(',', ':')))
            except RuntimeError as e:
                if 'changed while the job was running' not in str(e) or _i == 3:
                    raise
                _t.sleep(2 + _i * 2)

    def entities(self):
        # CLI inspect에는 페이지 커서 옵션이 없으므로 잘린 결과를 전체로 오인하지 않는다.
        data = self.call('inspect', '--scope', 'entities', read=True)
        rows = list(data.get('entities', []))
        # 2026-11-07 t10(원장 #32155 호리존·전철 직접): 24개 넘으면 잘림 → live cmd inspect_studio 의 cursor 로 끝까지 읽는다
        cursor, guard = data.get('nextCursor'), 0
        while cursor and guard < 50:
            page = self.call('cmd', 'inspect_studio', '--args', json.dumps({'scope': 'entities', 'limit': 24, 'cursor': cursor}), read=True)
            rows.extend(page.get('entities', []))
            cursor, guard = page.get('nextCursor'), guard + 1
        if cursor:
            raise RuntimeError('인물·물체 목록이 잘렸습니다. 전체 목록을 읽을 수 없어 중단합니다')
        return rows

    def shot(self):
        data = self.call('inspect', '--scope', 'shot', read=True)
        doc = data.get('document', data)
        shots = doc.get('shots', doc.get('shot', []))
        if isinstance(shots, dict):
            shots = [shots]
        if not shots:
            # 2026-11-06 cctb-44: 헤드리스로 새로 띄운 편집기는 샷이 없다 — 하나 만들고 다시 읽는다
            self.run('shot.create', {})
            data = self.call('inspect', '--scope', 'shot', read=True)
            doc = data.get('document', data)
            shots = doc.get('shots', doc.get('shot', []))
            if isinstance(shots, dict):
                shots = [shots]
        if not shots:
            raise RuntimeError('첫 샷을 찾을 수 없습니다')
        return shots[0]


# 2026-11-06 Codex — 대시보드가 동일한 프리셋 적용 경로를 호출하고 길이를 맞춘다.
def apply(name, overrides=None, live=None, *, frames=None, workspace=None, variant=None):
    preset = load(name) if isinstance(name, str) else name
    # 2026-11-08 Codex — 장면을 지우기 전에 변형을 확인하고 선택 카메라의 길이도 함께 맞춘다.
    if variant is not None:
        variants = preset.get('camera_variants', {})
        if variant not in variants:
            raise ValueError('알 수 없는 카메라 변형: ' + variant + ' (사용 가능: ' + ', '.join(variants) + ')')
        preset = {**preset, 'camera': variants[variant]}
    changes = overrides or {}
    live = live or Live(workspace)
    if isinstance(changes, dict):
        changes = [key + '=' + json.dumps(value, ensure_ascii=False) for key, value in changes.items()]
    params = dict(preset.get('params', {}))
    for item in changes:
        key, sep, raw = item.partition('=')
        if not sep or key not in params:
            raise ValueError('알 수 없는 --set 매개변수: ' + item)
        params[key] = numeric(json.loads(raw))
    p = substitute(preset, params)
    if frames is not None:
        if frames < 1 or p['frames'] < 1:
            raise ValueError('프레임 수는 양수여야 합니다')
        ratio = frames / p['frames']
        def scaled(frame):
            return min(frames - 1, max(0, round(frame * ratio)))
        for char in p.get('characters', []):
            for motion in char.get('motion', []):
                if 'f0' in motion:
                    motion['f0'] = scaled(motion['f0'])
        cam = p['camera']
        if 'range' in cam:
            cam['range'] = [scaled(v) for v in cam['range']]
            if preset['camera']['range'][1] == preset['frames'] - 1:
                cam['range'][1] = frames - 1
        for key in cam.get('keys', []):
            key['frame'] = scaled(key['frame'])
        p['frames'] = frames
    names = {}
    declared = [x['name'] for x in p.get('objects', []) + p.get('characters', [])]
    if len(set(declared)) != len(declared):
        raise ValueError('물체와 인물 이름은 중복될 수 없습니다')
    if live.dry:
        # 실제 생성 ID와 삭제 대상은 실행 시 읽으므로 dry-run에서는 식별자를 자리표시한다.
        print('# 기존 장면을 inspect하고 프리셋에 없는 인물과 물체를 제거합니다.')
        live.call('inspect', '--scope', 'entities')
        live.run('character.remove', {'characterId': '<기존 인물 id>'})
        live.run('object.remove', {'ids': ['<기존 물체 id>']})
        live.call('inspect', '--scope', 'shot')
        shot_id = '<첫 샷 id>'
    else:
        rows = live.entities()
        for row in rows:
            if row.get('kind') == 'character':
                live.run('character.remove', {'characterId': row['id']})
        ids = [r['id'] for r in rows if r.get('kind') == 'object']
        for i in range(0, len(ids), 100):
            live.run('object.remove', {'ids': ids[i:i + 100]})
        shot_id = live.shot()['id']
    live.run('shot.setTimeline', {'frameCount': p['frames']})
    live.run('shot.setRange', {'shotId': shot_id, 'range': {'startFrame': 0, 'endFrameExclusive': p['frames']}})  # 2026-11-06 cctb-44: 실제 스키마 {startFrame,endFrameExclusive}
    for obj in p.get('objects', []):
        before = set() if live.dry else {r['id'] for r in live.entities()}
        pos = xyz(obj.get('pos', [0, 0, 0]))
        live.run('object.add', {'kind': obj['kind'], 'name': obj['name'], 'placement': pos})
        if live.dry:
            live.call('inspect', '--scope', 'entities')
            oid = '<' + obj['name'] + ' id>'
        else:
            added = [r['id'] for r in live.entities() if r['kind'] == 'object' and r['id'] not in before]
            if len(added) != 1:
                raise RuntimeError('새 물체 ID를 유일하게 찾지 못했습니다: ' + obj['name'])
            oid = added[0]
        names[obj['name']] = oid
        fields = {'position': pos}
        if 'scale' in obj: fields['scale'] = xyz(obj['scale'])
        if 'color' in obj: fields['color'] = obj['color']
        if 'rot' in obj: fields['rotation'] = xyz(obj['rot'])  # 2026-11-07 cctb-44: 의자 방향(앉는 방향) 돌리기 — 모기 S1 책상 쪽 비스듬히
        live.run('object.set', {'id': oid, 'set': fields})
        if 'path' in obj:
            live.call('patch', '--target', 'object:' + oid, '--set', json.dumps({'path': references(obj['path'], names)}, ensure_ascii=False))
    for char in p.get('characters', []):
        before = set() if live.dry else {r['id'] for r in live.entities()}
        character = {'model': char['model'], 'posture': char.get('posture', 'stand')}  # 2026-11-06 cctb-44: subject 칸 없음(이름은 프리셋 안에서만 씀)
        character.update({k: v for k, v in char.items() if k not in ('name', 'model', 'motion', 'patch')})
        live.run('character.add', {'character': character})
        if live.dry:
            live.call('inspect', '--scope', 'entities')
            cid = '<' + char['name'] + ' id>'
        else:
            added = [r['id'] for r in live.entities() if r['kind'] == 'character' and r['id'] not in before]
            if len(added) != 1: raise RuntimeError('새 인물 ID를 유일하게 찾지 못했습니다: ' + char['name'])
            cid = added[0]
        names[char['name']] = cid
    # 2026-11-07 cctb-44: 인물 patch(parent·scale·hidden·position) — 움직이는 물체에 태운 작은 대역을 카메라 겨냥점으로 쓰는 시험(모기 S1)
    for char in p.get('characters', []):
        if isinstance(char.get('patch'), dict):
            live.call('patch', '--target', 'character:' + names[char['name']], '--set', json.dumps(references(char['patch'], names), ensure_ascii=False))
    for char in p.get('characters', []):
        if char.get('motion'):
            live.run('motion.compile', {'characterId': names[char['name']], 'spec': {'schema': 'cozyclay.motion-spec.v1', 'fps': 24, 'frames': p['frames'], 'use': references(char['motion'], names)}})
    cam = references(p['camera'], names)
    live.run('shot.clearKeys', {'shotId': shot_id})
    if cam['mode'] == 'rail':
        # 2026-11-07 cctb-44 원장 #32913: lookZones(바라보기 구역)도 넘긴다 — 포크 feat/look-zones 편집기에서만 받음(설치판은 모르는 칸이라 거절될 수 있음)
        live.run('shot.setCameraRail', {'shotId': shot_id, **{k: cam[k] for k in ('points', 'height', 'aim', 'aimHeight', 'focalMm', 'lookZones') if k in cam}})
        start, end = cam.get('range', [0, p['frames'] - 1])
        patch = {'mode': 'rail', 'railFollow': {'mode': 'range', 'startFrame': start, 'endFrame': end}}
        # 2026-11-08 cctb-78 원장 #33055·ec #33056 울렁거림: camera.dollyTiming({cuts:[{t,d}],envelopes}) 을 넘겨 레일 위 시간→거리를 고정(각속도 균등 등)
        if isinstance(cam.get('dollyTiming'), dict):
            patch['dollyTiming'] = cam['dollyTiming']
        # 2026-11-06 cctb-44 실측(모기 S1d·e): 레일 카메라 겨냥이 followCam response 0.7·lead 0.25 로 늦게 따라가 0프레임에 가슴을 올려다봄 → 프리셋 camera.follow 로 덮어쓰기
        if isinstance(cam.get('follow'), dict):
            shot_cam = (live.shot() or {}).get('camera', {}) if not live.dry else {}
            follow = dict(cam['follow'])
            per_frame = follow.pop('aimPerFrame', None)
            patch['followCam'] = {**(shot_cam.get('followCam') or {}), **follow}
            # 2026-11-07 cctb-44 원장 #32169 "평균/프레임 높이 중 선택": 편집기는 followCam 의 모르는 칸을 지우므로 샷 이름 표식 "[aim:frame]" 으로 고른다(patches/aim-per-frame.sh 가 읽음)
            base = re.sub(r'\s*\[aim:frame\]', '', (live.shot() or {}).get('name', 'Shot') if not live.dry else 'Shot')
            live.run('shot.rename', {'shotId': shot_id, 'name': base + (' [aim:frame]' if per_frame else '')})
        live.run('shot.setCamera', {'shotId': shot_id, 'patch': patch})
    elif cam['mode'] == 'keys':
        for key in cam['keys']:
            live.call('operate', '--frame', key['frame'])
            x, y, z = key['pos']; lx, ly, lz = key['look']
            live.run('shot.placeCamera', {'x': x, 'y': y, 'z': z, 'lookAtX': lx, 'lookAtY': ly, 'lookAtZ': lz, 'focalMm': key['focalMm']})
            live.run('shot.addKey', {'shotId': shot_id, 'frame': key['frame']})
    else:
        raise ValueError('알 수 없는 카메라 모드')


def save(name, desc, live):
    target = path_for(name)
    if target.exists():
        raise ValueError('이미 있는 프리셋입니다: ' + name)
    rows = live.entities()
    shot = live.shot()
    scene = live.call('inspect', '--scope', 'scene', read=True).get('document', {})
    objects_doc = {o['id']: o for o in scene.get('objects', [])}
    # ID가 이름과 겹치거나 이름이 중복되면 참조가 모호하므로 저장 전에 중단한다.
    named = [r for r in rows if r.get('kind') in ('object', 'character')]
    names = [r.get('name', '') for r in named]
    if len(set(names)) != len(names) or any(not re.fullmatch(r'[\w.-]+', n) for n in names):
        raise ValueError('장면의 인물·물체 이름이 중복되거나 참조할 수 없는 이름입니다')
    ids = {r['id']: '@' + r['name'] for r in named}
    def to_names(v):
        if isinstance(v, list): return [to_names(x) for x in v]
        if isinstance(v, dict): return {k: to_names(x) for k, x in v.items()}
        if isinstance(v, str):
            for ident in sorted(ids, key=len, reverse=True):
                v = v.replace(ident, ids[ident])
        return v
    objects, chars = [], []
    for row in named:
        if row['kind'] == 'object':
            obj = {'name': row['name'], 'kind': row.get('renderer'), 'pos': list(row['position'].values()), 'scale': list(row['scale'].values()), 'color': row.get('color')}
            source = objects_doc.get(row['id'], {})
            if source.get('path'):
                obj['path'] = to_names(source['path'])
            elif row.get('pathPointCount'):
                print('경고: %s의 경로 내용은 읽지 못해 저장하지 못했습니다.' % row['name'], file=sys.stderr)
            objects.append(obj)
        else:
            live.run('motion.report', {'characterId': row['id']})
            print('경고: %s의 마지막 compile 원본 spec을 확인할 수 없어 motion을 비웁니다.' % row['name'], file=sys.stderr)
            chars.append({'name': row['name'], 'model': row.get('modelId'), 'motion': []})
    camera = shot.get('camera', {})
    if camera.get('mode') == 'rail':
        cam = {'mode': 'rail', 'points': camera.get('cameraRail')}
        crane = camera.get('craneHeight')
        if crane: cam['height'] = crane.get('points', crane)
        for key in ('aim', 'aimHeight', 'focalMm'):
            if key in camera: cam[key] = to_names(camera[key])
        follow = camera.get('railFollow') or {}
        if follow.get('mode') == 'range': cam['range'] = [follow['startFrame'], follow['endFrame']]
    else:
        cam = {'mode': 'keys', 'keys': []}
        for key in shot.get('cameraKeys', []):
            pos = key.get('pos', key.get('position'))
            look = key.get('look', key.get('lookAt', key.get('target')))
            if isinstance(pos, dict): pos = [pos[k] for k in ('x', 'y', 'z')]
            if isinstance(look, dict): look = [look[k] for k in ('x', 'y', 'z')]
            if pos is None or look is None or 'focalMm' not in key:
                raise ValueError('카메라 키 형식을 변환할 수 없어 저장을 중단합니다')
            cam['keys'].append({'frame': key['frame'], 'pos': pos, 'look': look, 'focalMm': key['focalMm']})
        if camera.get('mode') != 'keys':
            print('경고: follow 카메라는 프리셋에서 지원하지 않습니다.', file=sys.stderr)
    timeline = scene.get('timeline', {})
    frames = timeline.get('frameCount', scene.get('frameCount', shot.get('endFrame', 119) + 1))
    data = {'_header': header('현재 장면에서 저장한 프리셋'), 'name': name, 'desc': desc, 'frames': frames, 'params': {}, 'objects': objects, 'characters': chars, 'camera': cam}
    with target.open('x', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print(target)


def header(purpose):
    # JSON에는 주석 문법이 없어 다섯 칸 머리말을 데이터로 보존한다.
    return {'목적': purpose, '실행': 'cozy_preset.py로 사용자가 실행', '요청': '2026-11-06 사용자, 장면 재사용 (1106-db2473)', '연결': 'presets/cozy_preset.py 및 로컬 CozyClay', '이력·되돌리기': '사용 중지 시 이 JSON 파일 삭제'}


def main():
    parser = argparse.ArgumentParser(description='CozyClay 장면 프리셋')
    sub = parser.add_subparsers(dest='command', required=True)
    # 2026-11-06 Codex — 대시보드에 기계가 읽는 목록을 제공한다.
    list_parser = sub.add_parser('list'); list_parser.add_argument('--json', action='store_true')
    show = sub.add_parser('show'); show.add_argument('name', nargs='?')
    apply_parser = sub.add_parser('apply'); apply_parser.add_argument('name'); apply_parser.add_argument('--set', action='append', default=[]); apply_parser.add_argument('--workspace'); apply_parser.add_argument('--dry-run', action='store_true')
    # 2026-11-08 Codex — 동일한 배치에서 대화 커버리지만 골라 적용할 수 있게 한다.
    apply_parser.add_argument('--variant', help='camera_variants의 카메라 이름')
    save_parser = sub.add_parser('save'); save_parser.add_argument('name'); save_parser.add_argument('--desc', default=''); save_parser.add_argument('--workspace')
    depth = sub.add_parser('export-depth'); depth.add_argument('out')
    args = parser.parse_args()
    if args.command == 'list':
        rows = []
        for path in sorted(LIBRARY.glob('*.json')):
            p = json.loads(path.read_text(encoding='utf-8'))
            if args.json:
                meta = p.get('params_meta', {})
                params = []
                for key, default in p.get('params', {}).items():
                    info = meta.get(key, {})
                    params.append({'key': key, 'label': info.get('label', key), 'type': type(default).__name__, 'default': default, 'min': info.get('min'), 'max': info.get('max')})
                # 2026-11-08 Codex — 기존 목록 소비자가 카메라 선택지를 함께 발견하게 한다.
                rows.append({'id': path.stem, 'name': p['name'], 'desc': p.get('desc', ''), 'frames': p['frames'], 'params': params, 'variants': list(p.get('camera_variants', {}))})
            else:
                print(f"{p['name']}\t{p.get('desc', '')}\t{p['frames']}프레임\t인물 {len(p.get('characters', []))}명")
        if args.json:
            print(json.dumps(rows, ensure_ascii=False))
    elif args.command == 'show':
        if args.name:
            # 2026-11-08 Codex — 원본 JSON의 camera_variants 이름과 카메라 설정을 그대로 보여 준다.
            print(json.dumps(load(args.name), ensure_ascii=False, indent=2))
        else:
            parser.error('show에는 프리셋 이름이 필요합니다')
    # 2026-11-08 Codex — 명령줄과 대시보드의 함수 호출이 같은 변형 선택 경로를 쓴다.
    elif args.command == 'apply': apply(load(args.name), args.set, Live(args.workspace, args.dry_run), variant=args.variant)
    elif args.command == 'save': save(args.name, args.desc, Live(args.workspace))
    else: print('깊이 영상 내보내기는 구현되지 않았습니다. 편집기 메뉴에서 직접 내보내세요.')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, OSError, RuntimeError, SyntaxError, ZeroDivisionError) as error:
        print('오류: ' + str(error), file=sys.stderr)
        sys.exit(1)
