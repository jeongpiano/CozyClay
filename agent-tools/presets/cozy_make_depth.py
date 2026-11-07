# 목적: 프리셋을 적용한 뒤 깊이 MP4를 대시보드에 제공한다.
# 실행: 대시보드 cozy_depth 잡 또는 사람이 Python 3으로 호출한다.
# 요청: 2026-11-06 원장 #32038, ec와 약속한 깊이 영상 연동.
# 연결: 편집기 5180, 허브 5184, ../.lock, ../patches 패치 3개 필요.
# 이력·되돌리기: 2026-11-07 Codex — 깊이 반복 보정; --depth-loop 0 또는 .bak-20261107-depthloop 복원.
import argparse
import fcntl
import json
import math
import os
import re
from pathlib import Path
import subprocess
import sys
import time

import cozy_preset


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError(message)


def status():
    result = subprocess.run([cozy_preset.BIN, 'live', 'status'], cwd=cozy_preset.CLAY,
                            capture_output=True, text=True, timeout=15)
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(result.stderr.strip() or 'live status 응답이 JSON이 아닙니다')
    if result.returncode or data.get('ok') is False:
        raise RuntimeError(str(data.get('error', 'live status 실패')))
    return data.get('value', data)


def probe(path):
    result = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                             '-count_frames', '-show_entries', 'stream=width,height,nb_read_frames',
                             '-of', 'json', str(path)], capture_output=True, text=True, check=True)
    stream = json.loads(result.stdout)['streams'][0]
    return int(stream['nb_read_frames']), int(stream['width']), int(stream['height'])


# 2026-11-07 Codex — 템플릿 수식·사용자 매개변수를 실제 좌표로 확정한 뒤 충돌을 검사한다.
def clearance_spec(preset, params, disabled=False):
    if disabled:
        return preset, {'enabled': False, 'changed': False}
    from cozy_clearance import fix_spec

    resolved_params = dict(preset.get('params', {}))
    for key, value in params.items():
        if key not in resolved_params:
            raise ValueError('알 수 없는 --set 매개변수: ' + key)
        resolved_params[key] = cozy_preset.numeric(value)
    fixed, report = fix_spec(cozy_preset.substitute(preset, resolved_params))
    return fixed, {**report, 'enabled': True}


def make(args):
    from playwright.sync_api import sync_playwright

    if not math.isfinite(args.seconds) or args.seconds <= 0 or args.fps != 24:
        raise ValueError('seconds는 양수이고 fps는 24여야 합니다')
    frames = round(args.seconds * args.fps)
    if frames < 1 or args.width < 1 or args.height < 1:
        raise ValueError('프레임 수와 영상 크기는 양수여야 합니다')
    # 2026-11-07 Codex — 보정 횟수는 재내보내기 횟수이며 마지막 영상도 다시 검사해야 한다.
    depth_loop = getattr(args, 'depth_loop', 3)
    if not isinstance(depth_loop, int) or depth_loop < 0:
        raise ValueError('depth-loop는 음이 아닌 정수여야 합니다')
    out = Path(args.out)
    if not out.is_absolute() or out.suffix.lower() != '.mp4':
        raise ValueError('out은 절대 경로의 mp4여야 합니다')
    params = json.loads(args.params)
    if not isinstance(params, dict):
        raise ValueError('params는 JSON 객체여야 합니다')
    # 2026-11-06 Codex — 생성한 장면도 기존 프리셋과 같은 경로로 적용한다.
    preset = cozy_preset.load(args.preset) if args.preset else json.loads(Path(args.spec).read_text(encoding='utf-8'))
    if not isinstance(preset, dict):
        raise ValueError('spec은 JSON 객체여야 합니다')
    # 2026-11-07 Codex — 내보낸 프레임 번호와 보정 좌표의 시간이 다르면 다른 구간을 밀게 된다.
    if not getattr(args, 'no_clearance', False) and preset.get('frames', 360) != frames:
        resolved_params = {**preset.get('params', {}), **params}
        preset = cozy_preset.substitute(preset, resolved_params)
        ratio = frames / preset.get('frames', 360)
        def scaled(frame):
            return min(frames - 1, max(0, round(frame * ratio)))
        for character in preset.get('characters', []):
            for motion in character.get('motion', []):
                if 'f0' in motion:
                    motion['f0'] = scaled(motion['f0'])
        camera = preset['camera']
        if 'range' in camera:
            start, end = camera['range']
            camera['range'] = [scaled(start), frames - 1 if end == preset.get('frames', 360) - 1 else scaled(end)]
        for key in camera.get('keys', []):
            key['frame'] = scaled(key['frame'])
        preset['frames'] = frames
    # 2026-11-07 Codex — 편집기를 열기 전에 투과 방지 spec을 확정한다.
    preset, clearance = clearance_spec(preset, params, getattr(args, 'no_clearance', False))
    clearance['depth_loop'] = []
    loop_enabled = clearance['enabled'] and not (preset['camera'].get('passThrough') or {}).get('body', False)
    unresolved = []
    # 2026-11-07 cctb-44 원장 #32169·ec 요청: --aim-per-frame = camera.follow.aimPerFrame=true(레일 겨냥 높이를 프레임마다, patches/aim-per-frame.sh 필요). 기본은 편집기 원래(평균)
    if args.aim_per_frame and isinstance(preset.get('camera'), dict):
        preset['camera']['follow'] = {**(preset['camera'].get('follow') or {}), 'aimPerFrame': True}
    # 2026-11-07 Codex — 실제 적용한 보정 spec을 영상 옆에 남겨 재현 가능하게 한다.
    fixed_path = out.with_name(out.stem + '_spec_fixed.json')
    def save_fixed():
        fixed_path.write_text(json.dumps(preset, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
        clearance['fixed_spec'] = str(fixed_path)
    if clearance['changed']:
        save_fixed()
    part = Path(str(out) + '.part')
    scaled = Path(str(out) + '.scaled.part')
    start_lock = (cozy_preset.CLAY / '.lock-start').open('a')
    fcntl.flock(start_lock, fcntl.LOCK_EX)   # 2026-11-07 t10: 띄우기·핸들 찾기 동안만 한 줄 서기
    before = {e['handle'] for e in status()['editors']}
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel='chrome', headless=True,
                args=['--use-gl=angle', '--enable-unsafe-swiftshader'])
            try:
                page = browser.new_page(accept_downloads=True)
                # 2026-11-07 cctb-44 원장 #32913: COZY_EDITOR_URL 로 포크 편집기(시험 포트)를 고를 수 있게. 기본은 설치판 5180
                page.goto(os.environ.get('COZY_EDITOR_URL', 'http://127.0.0.1:5180/app/'), wait_until='load')
                # 2026-11-06 cctb-44 실측: 새 브라우저는 시작 화면(프로젝트 고르기)이 메뉴를 가린다 → 새 Humanoid 프로젝트를 만든다
                try:
                    page.wait_for_selector('.v2-start-screen', timeout=8000)
                    page.get_by_text('Humanoid', exact=True).first.click()
                    page.get_by_role('button', name='Create').first.click()
                    page.wait_for_selector('.v2-start-screen', state='detached', timeout=15000)
                except Exception:
                    pass
                # 새 편집기에만 적용해야 기존 탭과 내보내기 탭이 서로 다른 상태가 되지 않는다.
                deadline = time.monotonic() + 30
                while True:
                    new = {e['handle'] for e in status()['editors']} - before
                    if len(new) == 1:
                        workspace = new.pop()
                        break
                    if len(new) > 1:
                        raise RuntimeError('새 편집기 핸들을 유일하게 찾지 못했습니다')
                    if time.monotonic() >= deadline:
                        raise RuntimeError('새 편집기가 허브에 연결되지 않았습니다')
                    time.sleep(0.5)
                fcntl.flock(start_lock, fcntl.LOCK_UN); start_lock.close()
                # 2026-11-07 Codex — 같은 탭·잠금을 재사용해야 반복 렌더가 다른 장면과 섞이지 않는다.
                for round_index in range(depth_loop + 1):
                    cozy_preset.apply(preset, params, frames=frames, workspace=workspace)
                    page.get_by_role('button', name='File', exact=True).click()
                    page.get_by_role('menuitem', name='Export', exact=True).click()
                    with page.expect_download(timeout=600000) as download:
                        page.get_by_role('menuitem', name='Depth (mp4)', exact=True).click()
                    download.value.save_as(str(part))
                    # 2026-11-06 cctb-44 원장 #32099 "shot camera 영상으로 렌더 전에 미리 볼 수 있게" → 같은 탭에서 Export → Video (mp4)(회색 인물·세트, 샷 카메라 그대로)
                    if args.preview:
                        page.keyboard.press('Escape')
                        page.get_by_role('button', name='File', exact=True).click()
                        page.get_by_role('menuitem', name='Export', exact=True).click()
                        with page.expect_download(timeout=600000) as pv:
                            page.get_by_role('menuitem', name='Video — this shot only (mp4)', exact=True).click()
                        pv_part = Path(args.preview + '.part')
                        pv.value.save_as(str(pv_part))
                        if pv_part.stat().st_size > 0:
                            os.replace(pv_part, args.preview)
                    if not part.is_file() or part.stat().st_size == 0:
                        raise RuntimeError('깊이 영상이 비어 있습니다')
                    count, width, height = probe(part)
                    if (width, height) != (args.width, args.height):
                        subprocess.run(['ffmpeg', '-y', '-i', str(part), '-vf', f'scale={args.width}:{args.height}',
                                        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-f', 'mp4', str(scaled)],
                                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                        if scaled.stat().st_size == 0:
                            raise RuntimeError('변환한 영상이 비어 있습니다')
                        count, width, height = probe(scaled)
                        os.replace(scaled, part)
                    # 2026-11-06 cctb-44 실측: 레일을 좌우 긴 벽(z 6m)이 감싸면 깊이가 전부 0(검정)인데 ok 로 나갔다 → 빈 깊이는 실패로 돌려준다
                    peak = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(part), '-vf', 'select=not(mod(n\\,12)),signalstats,metadata=print:key=lavfi.signalstats.YMAX:file=-',
                                           '-f', 'null', '-'], capture_output=True, text=True).stdout
                    ymax = [float(v) for v in re.findall(r'YMAX=([\d.]+)', peak)]
                    if ymax and max(ymax) <= 20:
                        part.unlink(missing_ok=True)
                        raise RuntimeError('깊이 영상이 전부 검정입니다(장면이 카메라를 감쌌을 수 있음 — 좌우 벽을 줄이거나 빼 보세요)')
                    if not loop_enabled:
                        break
                    from cozy_clearance import depth_problems, push_back

                    problems = depth_problems(str(part), fps=args.fps)
                    if not problems:
                        break
                    if round_index == depth_loop:
                        unresolved = [round(frame / args.fps, 6) for frame in problems]
                        break
                    preset, pushed = push_back(preset, problems)
                    clearance['depth_loop'].append(dict(round=round_index + 1, problems=pushed['frames'],
                                                        windows=pushed['windows'], max_push_m=pushed['max_push_m']))
                    clearance['changed'] = True
                    save_fixed()
            finally:
                browser.close()
        os.replace(part, out)
        result = {'ok': True, 'depth': str(out), 'frames': count, 'fps': args.fps,
                'w': width, 'h': height, 'seconds': args.seconds,
                # 2026-11-07 Codex — 잔여 충돌·가속도 경고도 호출자에게 전달한다.
                'preset': args.preset, 'spec': args.spec, 'clearance': clearance,
                'preview': args.preview if args.preview and os.path.isfile(args.preview) else None}
        if unresolved:
            result['depth_loop_unresolved'] = unresolved
        # 2026-11-08 cctb-78 원장 #33152·#33166 → #33172 "512로 바꾸자"(ec 최소 해상도 시험: 368 틈 못 들어감, 512 = 736 과 같은 경로, 시간 0.75배):
        #   렌더용 회색 참조는 512×288·24fps 정속이 기본 → 미리보기 옆에 <이름>_ref.mp4 를 만들고 결과 키 grey_ref(크기 중립 이름). 크기는 COZY_GREY_REF_W 로 바꿀 수 있음
        if result['preview']:
            w = int(os.environ.get('COZY_GREY_REF_W', '512')); h = round(w * 9 / 16 / 2) * 2
            grey = str(Path(result['preview']).with_name(Path(result['preview']).stem + '_ref.mp4'))
            made = subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', result['preview'], '-vf', f'scale={w}:{h},fps=24', '-an',
                                   '-c:v', 'libx264', '-crf', '18', '-pix_fmt', 'yuv420p', grey], capture_output=True)
            result['grey_ref'] = grey if made.returncode == 0 and os.path.isfile(grey) else None
            result['grey_ref_size'] = [w, h]
        return result
    finally:
        part.unlink(missing_ok=True)
        scaled.unlink(missing_ok=True)


def main():
    parser = Parser(description='CozyClay 깊이 영상 생성')
    # 2026-11-06 Codex — 이름과 파일 중 하나만 선택해 장면 출처를 명확히 한다.
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--preset')
    source.add_argument('--spec')
    parser.add_argument('--seconds', required=True, type=float)
    parser.add_argument('--fps', type=int, default=24)
    parser.add_argument('--width', required=True, type=int)
    parser.add_argument('--height', required=True, type=int)
    parser.add_argument('--params', default='{}')
    parser.add_argument('--out', required=True)
    parser.add_argument('--preview', help='샷 카메라 미리보기 mp4 경로(선택)')
    parser.add_argument('--aim-per-frame', action='store_true', help='레일 겨냥 높이를 프레임마다(기본: 평균)')
    # 2026-11-07 Codex — 기존 투과 경로가 필요한 장면은 명시적으로 검사를 끈다.
    parser.add_argument('--no-clearance', action='store_true', help='카메라 인체·사물 우회 보정 끄기')
    # 2026-11-07 Codex — 실측 보정 예산을 지정하고 0이면 검사 결과만 보고한다.
    parser.add_argument('--depth-loop', type=int, default=3, help='깊이 영상 기반 최대 보정 횟수(기본 3)')
    args = parser.parse_args()
    # 2026-11-07 t10(원장 #32160 "내보내기 잠금풀고, 여러개 동시 작업 가능하게", #32161 "창하나 더 열어서"):
    #   잠금 1칸 → 3칸(.lock, .lock1, .lock2). 판마다 자기 헤드리스 편집기를 새로 열므로 동시에 돌아도 장면이 섞이지 않는다.
    #   편집기를 띄우고 새 핸들을 찾는 몇 초만 .lock-start 로 줄을 세운다(둘이 동시에 뜨면 새 핸들이 2개라 구분 못 함).
    for name in ('.lock', '.lock1', '.lock2'):
        lock = (cozy_preset.CLAY / name).open('a')
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock.close()
            continue
        with lock:
            print(json.dumps(make(args), ensure_ascii=False))
        return 0
    print(json.dumps({'ok': False, 'error': 'busy'}))
    return 2


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as error:
        print(json.dumps({'ok': False, 'error': str(error)}, ensure_ascii=False))
        sys.exit(1)
