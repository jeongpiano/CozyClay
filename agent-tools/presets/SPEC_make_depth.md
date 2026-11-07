# cozy_make_depth.py · list --json 명세 (2026-11-06 cctb-44, 원장 #32038·#32047, ec 와 약속)

## 목적
대시보드(게이트웨이, ec 담당)가 씬 화면 [코지클레이] 단추에서 부르는 두 명령. 셸 없이 인자 목록으로 불리고, **stdout 마지막 줄이 JSON** 이다.

## 1a. `cozy_preset.py list --json` (기존 파일에 옵션 추가)
- 출력: `[{id, name, desc, frames, params:[{key,label,type,default,min,max}]}]` — id = 파일 이름(확장자 없이). 프리셋 JSON 의 `params` 가 지금은 `{key: 기본값}` 꼴이면 type 은 기본값 타입(float/int/str), label 은 `params_meta.<key>.label` 이 있으면 그것, 없으면 key. min/max 는 `params_meta` 에 있으면.
- 기존 `list`(사람용 표)는 그대로.

## 1b. 새 파일 `~/tools/cozyclay/presets/cozy_make_depth.py`
```
cozy_make_depth.py --preset <id> --seconds <float> --fps 24 --width W --height H --params '<json>' --out <절대경로.mp4>
```
- 잠금: `~/tools/cozyclay/.lock` 을 fcntl.flock(LOCK_EX|LOCK_NB) — 잡혀 있으면 `{"ok":false,"error":"busy"}` 출력 후 종료 2.
- 프레임 수 = round(seconds*fps). 프리셋을 `cozy_preset.apply(name, overrides)`(파이썬 함수로 import — cozy_preset.py 를 함수로 쓸 수 있게 정리)로 적용하되, **frames 를 이 값으로 덮어쓴다**(shot.setTimeline·setRange·motion.compile frames·camera range 끝 = frames-1). 프리셋 안의 시각(키 frame, railFollow 범위, 동작 f0)은 `frames / preset_frames` 비율로 늘이고 줄인다(정수 반올림).
- 깊이 내보내기: Playwright(파이썬 `playwright.sync_api`, 이미 설치됨 — `python3 -c "import playwright"` 로 확인)로 **이미 열린 편집기**에 붙지 말고, 새 브라우저를 띄우지도 말 것 — 대신 **CDP 로 기존 크롬에 붙는 방법이 없으면**, 헤드리스 chromium 으로 `http://127.0.0.1:5180/app/` 를 열면 같은 프로젝트(마지막 자동 저장)가 열린다. ⚠ 편집기 탭이 둘이 되면 같은 문서를 둘이 고친다 — 그래서 순서: ① apply 는 cclay live 로(기존 편집기 탭에) ② 내보내기는 그 탭에서 해야 한다. 기존 탭에 붙을 길: `cclay live` 허브가 편집기에 명령을 보낼 때 쓰는 명령 중 내보내기가 있는지 `node_modules/.bin/cclay live commands` 와 `node_modules/cozyclay/src` 에서 `exportDepth|Depth (mp4)|blocking-depth` 를 찾아보고, **있으면 그것을 쓴다**. 없으면 헤드리스 chromium 을 `channel="chrome", headless=True, args=["--use-gl=angle","--enable-unsafe-swiftshader"]` 로 띄워 5180/app 을 열고(wait_until="load"), File → Export → "Depth (mp4)" 메뉴를 role=menuitem 으로 눌러 `page.expect_download()` 로 받는다 — 이 경우 그 헤드리스 탭이 편집기가 되므로 apply 도 그 탭이 연결된 뒤(`cclay live status` 의 editors 에 새 handle 이 생긴 뒤 `--workspace <그 handle>`) 그 탭에 한다. 끝나면 브라우저를 닫는다.
- 저장: `<out>.part` 로 받고 크기 > 0 이면 `<out>` 으로 이름 바꾸기. ffprobe 로 프레임 수·크기 읽어 결과에 넣는다(`--width/--height` 와 다르면 ffmpeg 로 그 크기로 다시 인코딩: `-vf scale=W:H -c:v libx264 -pix_fmt yuv420p`).
- 결과: `{"ok":true,"depth":out,"frames":N,"fps":24,"w":W,"h":H,"seconds":s,"preset":id}` / 실패 `{"ok":false,"error":"..."}` (예외는 잡아서 JSON 으로).
- 머리말 5칸(한국어): 목적·실행(대시보드 cozy_depth 잡, 사람)·요청(원장 #32038, ec 약속)·연결(편집기 5180, 허브 5184, 잠금 파일, 패치 3개 필요 ~/tools/cozyclay/patches)·이력/되돌리기.

## 검사(Codex)
- `python3 cozy_preset.py list --json | tail -1 | python3 -m json.tool` 성공.
- `python3 cozy_make_depth.py --help` 성공. 실제 실행은 하지 않는다(살아 있는 편집기를 바꿈 — Claude 가 한다).
- 문법 검사 `python3 -m py_compile` 두 파일.

## 하지 않을 것
- node_modules·dist 수정 금지. 게이트웨이 코드 수정 금지(ec 몫).
