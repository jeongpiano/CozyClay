# 목적: 씬과 피드백을 CozyClay 장면 JSON으로 변환한다.
# 실행: 대시보드 또는 사람이 Python 3 명령줄에서 호출한다.
# 요청: 2026-11-06 원장 #32056·#32058, 장면 자동 생성과 수정.
# 연결: library/*.json, /Users/open/content_studio/core/llm.py, 지정한 입출력 JSON.
# 이력·되돌리기: SPEC_llm.md; 호출을 중단하고 이 파일을 제거한다.
import argparse
import json
import os
import math
from pathlib import Path
import sys

sys.path.insert(0, '/Users/open/content_studio')
from core.llm import llm_chat_meta  # 2026-11-06 cctb-44: provider·model 기록(원장 #32068·#32069 로컬/클라우드 선택)

ROOT = Path(__file__).resolve().parent
SYSTEM = '''Use literal numbers everywhere (no ${param} templates). Camera rail points must circle or pass beside people, never through them. Height marks t are fractions 0..1.
Return exactly one complete CozyClay preset JSON object with name, desc, frames,
params (object), objects (array), characters (array), and camera (object).
Objects have name, kind (cube|cylinder|sphere), pos [x,y,z], scale [sx,sy,sz],
color, optionally path {points:[{x,y,z}],speed}. Characters have name, model
(y-bot-tpose|x-bot-tpose), motion [{skill,f0,args}]. Use concrete values or
numeric params as in the examples. Coordinates are meters, y is up, the floor
is y=0, object positions are floor-based, characters face +z at heading 0,
and the camera is normally on the +z side. Build an enclosed room with a wall
1–3 meters behind the character to limit depth range.
Skills: standIdle {at:[x,z],heading,until}; walkTo {to:[x,z],steps,step,period}
lasts 16+steps*period+18 frames and f0+length must be <= frames-1;
sitInSeat {seat:"@object_name"} with the seat behind the character;
reachGrip {anchor,side:"l"|"r",reach,hold,release,define:{kind:"world",p:[x,y,z]}}
within 0.6m of the arm; hitReaction {from:"object:@name",speed};
throwObject and catchObject. Use a rail for moving or rotating cameras: 2–40
points {x,z}, height >= 0.1 as a number or 2–8 marks [{t,height}], aim ["@character"] plus
aimHeight or {x,y,z}, focalMm, range [0,frames-1]. Use exactly two keys for a
fixed camera or simple push-in, never three or more. Build a back wall 1-3 m
behind the people and at most one short side wall; never surround the camera
rail with walls (the depth export turns black). Never place a camera below
an asleep or unaware person's body looking up, or looking inside clothing.
Set frames exactly to the requested number. In feedback mode return the entire
revised preset and changes as an array of sentences. Examples follow verbatim:
'''+ '\n\n'.join((ROOT / 'library' / name).read_text(encoding='utf-8') for name in
                ('corridor_walk_pushin.json', 'seated_side_rail.json'))


def _openai_chat(provider, prompt):
    # 2026-11-06 cctb-44 원장 #32072(t10 안내): hermes = 헤르메스 게이트웨이 127.0.0.1:8642(model hermes-agent, 열쇠 ~/.hermes/.env API_SERVER_KEY 를 읽어 헤더로만),
    #   deepseek = DeepSeek 하네스와 같은 두뇌를 llm_router 127.0.0.1:11500(model local-fast, 5070 굽기 중이면 라우터가 다른 길)로.
    import urllib.request, re
    if provider == 'hermes':
        url, model, key = 'http://127.0.0.1:8642/v1/chat/completions', 'hermes-agent', ''
        try:
            for line in open(os.path.expanduser('~/.hermes/.env'), encoding='utf-8'):
                if line.startswith('API_SERVER_KEY='):
                    key = line.split('=', 1)[1].strip().strip('"').strip("'")
        except OSError:
            pass
    else:
        url, model, key = 'http://127.0.0.1:11500/v1/chat/completions', 'local-fast', ''
    body = {'model': model, 'messages': [{'role': 'system', 'content': SYSTEM + '\nReply with the JSON object only, no prose.'},
                                          {'role': 'user', 'content': prompt}], 'temperature': 0.2}
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={'Content-Type': 'application/json', **({'Authorization': 'Bearer ' + key} if key else {})})
    with urllib.request.urlopen(req, timeout=300) as r:
        d = json.loads(r.read())
    text = d['choices'][0]['message']['content']
    m = re.search(r'\{.*\}', text, re.S)
    if not m:
        raise RuntimeError('no JSON object in reply')
    return json.loads(m.group(0)), provider, d.get('model') or model


def _loose_json(text):
    """코드펜스·앞뒤 글·// 주석·끝 쉼표를 걷어내고 첫 { ~ 마지막 } 을 푼다(2026-11-06 cctb-44)."""
    import re
    t = text or ''
    m = re.search(r'```(?:json)?\s*([\s\S]*?)```', t)
    if m:
        t = m.group(1)
    i, j = t.find('{'), t.rfind('}')
    if i < 0 or j <= i:
        raise ValueError('no JSON object in reply')
    t = t[i:j + 1]
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        t2 = re.sub(r'(?m)//[^"\n]*$', '', t)
        t2 = re.sub(r',\s*([}\]])', r'\1', t2)
        t2 = re.sub(r'([}\]"\d]|true|false|null)(\s*\n\s*)(["{\[])', r'\1,\2\3', t2)  # 2026-11-07 cctb-44 ec 실측: 줄 끝 쉼표 빠짐("Expecting ',' delimiter")
        try:
            return json.loads(t2)
        except json.JSONDecodeError as e:
            raise ValueError(str(e))


def _normalize(spec):
    # 2026-11-06 cctb-44: 로컬 모델이 height t 를 0..2 로 쓰는 일 → 최대값으로 나눠 0..1 로(뜻은 같음)
    cam = spec.get('camera') if isinstance(spec, dict) else None
    hs = cam.get('height') if isinstance(cam, dict) else None
    if isinstance(hs, list) and hs and all(isinstance(h, dict) and isinstance(h.get('t'), (int, float)) for h in hs):
        mx = max(h['t'] for h in hs)
        if mx > 1:
            for h in hs:
                h['t'] = round(h['t'] / mx, 4)
    # 2026-11-06 cctb-44 실측: gemma4 가 높이 표시 9개를 써서 편집기가 거절(shot.setCameraRail height 는 2~8개, 점은 {x,z} 만 받음) → 고르게 8개로 추리고 점의 y 는 버린다
    if isinstance(hs, list) and len(hs) > 8:
        cam['height'] = [hs[round(i * (len(hs) - 1) / 7)] for i in range(8)]
    # 2026-11-06 cctb-44 ec 실측: DeepSeek 가 5초(120프레임)에 walkTo 를 f10 부터 142프레임으로 써 편집기가 거절 → 걸음 수를 줄여 마지막 프레임 안에 넣는다(길이 = 16 + steps*period + 18)
    frames = spec.get('frames') if isinstance(spec, dict) else None
    if isinstance(frames, int):
        # 2026-11-07 cctb-44 ec 실측(1106-f69ad3): 첫 동작이 walkTo 면 편집기가 "needs a standing pose keyed before f0" 로 거절 → 앞에 standIdle 을 끼운다
        for c in spec.get('characters') or []:
            ms = [m for m in (c.get('motion') or []) if isinstance(m, dict)] if isinstance(c, dict) else []
            if ms and min(ms, key=lambda m: m.get('f0', 0) if isinstance(m.get('f0'), int) else 0).get('skill') == 'walkTo':
                first = min(ms, key=lambda m: m.get('f0', 0) if isinstance(m.get('f0'), int) else 0)
                if not isinstance(first.get('f0'), int) or first['f0'] < 6:
                    first['f0'] = 6
                wa = first.get('args') if isinstance(first.get('args'), dict) else {}
                to = wa.get('to') if isinstance(wa.get('to'), list) and len(wa['to']) == 2 and all(isinstance(v, (int, float)) for v in wa['to']) else [0, 0]
                back = max(1, (frames - 1 - first['f0'] - 34) // (wa.get('period', 18) if isinstance(wa.get('period'), (int, float)) else 18)) * 0.40
                # 시작점: 편집기가 at 을 요구 — 정면(+z)으로 걸어 to 에 닿도록 그 걸음 길이만큼 뒤(-z)
                c['motion'] = [{'skill': 'standIdle', 'f0': 0, 'args': {'at': [to[0], round(to[1] - back, 3)], 'heading': 0, 'until': first['f0']}}] + c['motion']
        # 2026-11-07 cctb-44 ec 실측(1106-f69ad3 3차): 편집기 실제 걸음 ~0.42m(4걸음 1.67m) — steps·step 은 지우고(walkTo 가 고름)
        #   남은 프레임에 들어가는 최대 걸음 × 0.40m 보다 멀면 to 를 시작점 쪽으로 당긴다. 길이 = 16 + steps*period + 18
        for c in spec.get('characters') or []:
            start = None
            for mo in (c.get('motion') or []) if isinstance(c, dict) else []:
                a = mo.get('args') if isinstance(mo, dict) else None
                if not isinstance(a, dict):
                    continue
                if mo.get('skill') == 'walkTo' and isinstance(mo.get('f0'), int):
                    period = a.get('period', 18) if isinstance(a.get('period'), (int, float)) else 18
                    room = frames - 1 - mo['f0'] - 34
                    if room < period:
                        mo['f0'] = max(0, frames - 1 - 34 - period)
                        room = frames - 1 - mo['f0'] - 34
                    a.pop('steps', None); a.pop('step', None)
                    to = a.get('to')
                    if isinstance(start, list) and isinstance(to, list) and len(start) == 2 and len(to) == 2 and all(isinstance(v, (int, float)) for v in start + to):
                        dist = math.hypot(to[0] - start[0], to[1] - start[1])
                        reach = int(room // period) * 0.40
                        if dist > reach > 0:
                            k = reach / dist
                            a['to'] = [round(start[0] + (to[0] - start[0]) * k, 3), round(start[1] + (to[1] - start[1]) * k, 3)]
                    start = a.get('to', start)
                else:
                    start = a.get('at', a.get('to', start))
    pts = cam.get('points') if isinstance(cam, dict) else None
    if isinstance(pts, list):
        cam['points'] = [{'x': p['x'], 'z': p['z']} if isinstance(p, dict) and 'x' in p and 'z' in p else p for p in pts]
    return spec


def validate(spec, frames):
    errors = []
    if not isinstance(spec, dict):
        return ['response must be a JSON object']
    for key, typ in [('name', str), ('desc', str), ('frames', int), ('params', dict),
                     ('objects', list), ('characters', list), ('camera', dict)]:
        if key not in spec or not isinstance(spec[key], typ) or (key == 'frames' and isinstance(spec[key], bool)):
            errors.append(f'{key} must be {typ.__name__}')
    if spec.get('frames') != frames:
        errors.append(f'frames must equal {frames}')
    for i, character in enumerate(spec.get('characters', []) if isinstance(spec.get('characters'), list) else []):
        if not isinstance(character, dict) or not isinstance(character.get('motion'), list):
            errors.append(f'characters[{i}].motion must be an array')
            continue
        for j, motion in enumerate(character['motion']):
            f0 = motion.get('f0') if isinstance(motion, dict) else None
            if isinstance(f0, bool) or not isinstance(f0, int) or not 0 <= f0 < frames:
                errors.append(f'characters[{i}].motion[{j}].f0 must be an integer in [0,{frames-1}]')
    # 2026-11-06 cctb-44 실측(로컬 gemma4): '${circle_radius}'·'-${circle_radius}' 처럼 틀을 문자열로 남기고, 레일을 인물 한가운데로 지나가게 썼다.
    def _strs(o, path=''):
        if isinstance(o, str) and '${' in o:
            yield path
        elif isinstance(o, dict):
            for k, v in o.items():
                if k not in ('params',):
                    yield from _strs(v, f'{path}.{k}')
        elif isinstance(o, list):
            for i, v in enumerate(o):
                yield from _strs(v, f'{path}[{i}]')
    for bad in _strs(spec):
        errors.append(f'{bad}: use a literal number, not a ${{param}} template')
    camera = spec.get('camera')
    chars_at = []
    for c in spec.get('characters', []) if isinstance(spec.get('characters'), list) else []:
        for m in c.get('motion', []) if isinstance(c, dict) else []:
            at = (m.get('args') or {}).get('at') or (m.get('args') or {}).get('to') if isinstance(m, dict) else None
            if isinstance(at, list) and len(at) == 2 and all(isinstance(v, (int, float)) for v in at):
                chars_at.append(at)
    if isinstance(camera, dict) and camera.get('mode') == 'rail':
        hs = camera.get('height')
        if isinstance(hs, list) and any(isinstance(h, dict) and not (0 <= (h.get('t') if isinstance(h.get('t'), (int, float)) else -1) <= 1) for h in hs):
            errors.append('rail height t values must be within [0,1]')
        for k, pt in enumerate(camera.get('points') or []):
            if isinstance(pt, dict) and all(isinstance(pt.get(a), (int, float)) for a in ('x', 'z')):
                for at in chars_at:
                    if math.hypot(pt['x'] - at[0], pt['z'] - at[1]) < 0.25:
                        errors.append(f'camera.points[{k}] passes through a character at {at}; keep at least 0.25 m away')
        # 2026-11-06 cctb-44 실측(hermes→5070 Qwen): 복도 벽(x=±1.6) 바깥 x=±2.5 로 레일을 돌려 6장 중 4장이 벽만 보였다 → 레일 점과 인물 사이를 벽 상자가 막으면 되묻는다
        targets = list(chars_at)
        objs = {o.get('name'): o for o in spec.get('objects', []) if isinstance(o, dict)} if isinstance(spec.get('objects'), list) else {}
        for c in spec.get('characters', []) if isinstance(spec.get('characters'), list) else []:
            for m in c.get('motion', []) if isinstance(c, dict) else []:
                seat = str((m.get('args') or {}).get('seat', '')).lstrip('@') if isinstance(m, dict) else ''
                pos = (objs.get(seat) or {}).get('pos')
                if isinstance(pos, list) and len(pos) == 3:
                    targets.append([pos[0], pos[2]])
        boxes = []
        for o in objs.values():
            pos, sc = o.get('pos'), o.get('scale')
            if o.get('kind') == 'cube' and isinstance(pos, list) and isinstance(sc, list) and len(pos) == 3 and len(sc) == 3 \
                    and all(isinstance(v, (int, float)) for v in pos + sc) and min(sc[0], sc[2]) <= 0.5 and sc[1] >= 1.5:
                boxes.append((o.get('name'), pos[0] - sc[0] / 2, pos[0] + sc[0] / 2, pos[2] - sc[2] / 2, pos[2] + sc[2] / 2))
        for k, pt in enumerate(camera.get('points') or []):
            if not (isinstance(pt, dict) and all(isinstance(pt.get(a), (int, float)) for a in ('x', 'z'))):
                continue
            for at in targets:
                hit = next((b[0] for b in boxes for s in range(1, 20)
                            if b[1] <= pt['x'] + (at[0] - pt['x']) * s / 20 <= b[2] and b[3] <= pt['z'] + (at[1] - pt['z']) * s / 20 <= b[4]), None)
                if hit:
                    errors.append(f'camera.points[{k}] at ({pt["x"]},{pt["z"]}) sees the person through wall "{hit}"; keep the rail inside the room')
                    break
        points = camera.get('points')
        if not isinstance(points, list) or len(points) < 2:
            errors.append('rail points must contain at least two points')
        height = camera.get('height')
        values = [x.get('height') if isinstance(x, dict) else None for x in height] if isinstance(height, list) else [height]
        if not values or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0.1 for v in values):
            errors.append('rail height values must be numbers >= 0.1')
    return errors


def main():
    parser = argparse.ArgumentParser(description='씬 글을 CozyClay 장면 JSON으로 생성')
    parser.add_argument('--scene-json', required=True)
    parser.add_argument('--feedback')
    parser.add_argument('--current')
    parser.add_argument('--seconds', required=True, type=float)
    parser.add_argument('--out', required=True)
    parser.add_argument('--provider', default='local', choices=['local', 'cloud', 'hermes', 'deepseek'])  # 2026-11-06 cctb-44 원장 #32069: 고를 수 있게, 기본 로컬
    args = parser.parse_args()
    if not math.isfinite(args.seconds) or args.seconds <= 0 or round(args.seconds * 24) < 1:
        raise ValueError('seconds must produce at least one frame')
    out = Path(args.out)
    if not out.is_absolute():
        raise ValueError('out must be an absolute path')
    scene = json.loads(Path(args.scene_json).read_text(encoding='utf-8'))
    if not isinstance(scene, dict):
        raise ValueError('scene must be a JSON object')
    frames = round(args.seconds * 24)
    prompt = f'Create a scene with exactly {frames} frames. Scene: ' + json.dumps(scene, ensure_ascii=False)
    feedback_mode = bool(args.current and args.feedback)
    if feedback_mode:
        current = json.loads(Path(args.current).read_text(encoding='utf-8'))
        prompt += '\nRevise this entire current scene: ' + json.dumps(current, ensure_ascii=False)
        prompt += '\nFeedback: ' + args.feedback + '\nInclude changes as an array of sentences.'
    last_error = ''
    for attempt in range(3):
        try:
            if args.provider in ('hermes', 'deepseek'):
                spec, used_provider, used_model = _openai_chat(args.provider, prompt)
            else:
                # 2026-11-06 cctb-44 ec 실측(itest_48 씬2): gemma4 가 가끔 JSON 이 아닌 글(주석·끝 쉼표 등)을 내 json_mode 파싱이 3번 다 'Expecting value' → 글로 받아 관대하게 풀고, 못 풀면 그 오류를 붙여 되묻는다
                text = None
                if args.provider == 'local':
                    # 2026-11-07 cctb-44 ec 실측(1106-f69ad3 간헐): 쉼표 빠진 JSON 이 남음 → Ollama format:"json"(문법 제약 출력)으로 직접 부른다. 실패하면 아래 공용 경로
                    try:
                        from core.llm import local_model, _post
                        base, lm = local_model()
                        if lm:
                            r = _post(base + '/api/generate', {'model': lm, 'prompt': SYSTEM + '\n\n' + prompt, 'stream': False,
                                                               'think': False, 'format': 'json', 'keep_alive': 120}, timeout=240)
                            text, used_provider, used_model = r.get('response') or '', 'local', lm
                    except Exception:
                        text = None
                if not text:
                    text, used_provider, used_model = llm_chat_meta(prompt, system=SYSTEM, provider=('local' if args.provider == 'local' else 'auto'), json_mode=False, timeout=240)
                try:
                    spec = _loose_json(text)
                except ValueError as bad:
                    prompt += '\nYour previous reply was not valid JSON (' + str(bad)[:120] + '). Reply with one JSON object only, no comments, no trailing commas.'
                    last_error = 'invalid JSON: ' + str(bad)[:200]
                    continue
            spec = _normalize(spec)
            errors = validate(spec, frames)
            if feedback_mode and (not isinstance(spec, dict) or not isinstance(spec.get('changes'), list) or any(not isinstance(c, str) for c in spec['changes'])):
                errors.append('changes must be an array of sentences')
            if not errors:
                changes = spec.pop('changes', [])
                if not isinstance(changes, list) or any(not isinstance(c, str) for c in changes):
                    changes = []
                out.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
                # llm_chat deliberately discards provider metadata; do not claim a guessed model.
                return {'ok': True, 'spec': str(out), 'changes': changes, 'provider': used_provider, 'model': used_model}
            last_error = '; '.join(errors)
            prompt += '\nCorrect this invalid response and return the complete JSON. Errors: ' + last_error
            prompt += '\nPrevious response: ' + json.dumps(spec, ensure_ascii=False)
        except Exception as error:
            last_error = str(error)
        if attempt == 0:
            continue
    raise RuntimeError('LLM failed after two attempts: ' + last_error)


if __name__ == '__main__':
    try:
        print(json.dumps(main(), ensure_ascii=False))
    except Exception as error:
        print(json.dumps({'ok': False, 'error': str(error)}, ensure_ascii=False))
        sys.exit(1)
