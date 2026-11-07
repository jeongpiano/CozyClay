# CozyClay 프리셋 도구 명세 (2026-11-06 cctb-44, 원장 #32030 "코지클레이도 프리셋들 저장해놓고 바로바로 불러서 사용")

## 목적
코지클레이(브라우저 프리비즈, `cclay live` 명령줄로 조작) 장면을 **이름 붙은 JSON 프리셋**으로 저장하고, 명령 한 줄로 불러와
몇 개 값(인물 위치·카메라 거리·길이)만 바꿔 쓰게 한다.

## 만들 것
- `~/tools/cozyclay/presets/cozy_preset.py` (Python 3, 표준 라이브러리만)
- 프리셋 폴더 `~/tools/cozyclay/presets/library/*.json`
- 파일 맨 위 5칸 머리말(목적·실행·요청·연결·이력/되돌리기, 한국어) — 기존 `~/tools/cozyclay/patches/*.sh` 머리말 참고

## 명령
- `cozy_preset.py list` — 이름·설명·길이(프레임)·인물 수
- `cozy_preset.py show <이름>`
- `cozy_preset.py apply <이름> [--set key=value ...] [--workspace <handle>] [--dry-run]`
  - 장면을 비운다: 프리셋에 없는 인물·물체를 지운다(`character.remove {characterId}`, `object.remove {ids:[...]}` — 스키마는 `cclay live commands --ids <id>` 로 확인).
  - 순서: `shot.setTimeline {frameCount}` → 첫 샷 `shot.setRange` → 물체(`object.add {kind,name,placement}` 후 새 id 는 `cclay live inspect --scope entities` 전후 비교로 찾는다 — **affectedIds 의 첫 칸은 새 id 가 아닐 수 있다**) → `object.set {id,set:{scale,position,color}}` → 물체 경로는 `cclay live patch --target object:<id> --set '{"path":{...}}'` → 인물(`character.add`, 새 id 는 같은 방식) → `motion.compile {characterId, spec:{schema:"cozyclay.motion-spec.v1",fps:24,frames,use:[...]}}` → 카메라.
  - 카메라 두 종류: `"camera":{"mode":"rail","points":[{x,z}...],"height":[{t,height}...] 또는 숫자,"aim":{"x","y","z"} 또는 ["@인물이름"],"aimHeight":n,"focalMm":n,"range":[시작,끝]}` → `shot.clearKeys`, `shot.setCameraRail`, `shot.setCamera {shotId, patch:{mode:"rail", railFollow:{mode:"range",startFrame,endFrame}}}`.
    또는 `"mode":"keys","keys":[{frame, pos:[x,y,z], look:[x,y,z], focalMm}]` → 각 키마다 `cclay live operate --frame N` → `shot.placeCamera {x,y,z,lookAtX..,focalMm}` → `shot.addKey {shotId, frame}`.
  - 프리셋 안의 이름 참조(`"@her"`, `"@cup"`)는 apply 때 실제 id 로 바꾼다(인물 aim, motion 의 `seat`, `object:<id>` 등 문자열 안 `@이름` 전부).
  - `--set` 은 프리셋 JSON 의 `params` 칸(기본값 표)을 덮는다. 프리셋 본문 숫자 자리에 `"${param}"` 또는 `{"$expr":"param+0.2"}`(파이썬 eval 금지 — +,-,*,/ 와 숫자·param 이름만 직접 파싱) 를 쓸 수 있다.
  - 실행은 `node_modules/.bin/cclay live run <id> --args '<json>'`(cwd `~/tools/cozyclay`), 결과 JSON 의 `ok` 가 false 면 그 줄과 error.message 를 출력하고 멈춘다. `--dry-run` 은 보낼 명령만 출력.
- `cozy_preset.py save <이름> [--desc 설명]` — 지금 장면을 프리셋으로 저장: `cclay live inspect --scope entities`(물체 위치·크기·색·경로 수), `--scope shot`(첫 샷 camera 블록: cameraRail·craneHeight·aim·focalMm·railFollow·cameraKeys), 인물의 motion 은 `motion.report {characterId}` 의 `specId` 로 `motion.describe` 가 아니라 **마지막 compile 에 쓴 spec 을 알 수 없으면 비워 두고 경고**(사람이 프리셋 JSON 에 채운다). id 는 이름(`@` 참조)으로 바꿔 쓴다.
- `cozy_preset.py export-depth <out.mp4>` — 메뉴 클릭이 필요한 일이라 이번엔 만들지 않는다(안내 문구만).

## 프리셋 JSON 꼴(예시 하나를 library 에 같이 만든다)
```json
{"name":"corridor_walk_pushin","desc":"복도에서 걸어와 멈춤 + 카메라 밀기(T1)","frames":120,
 "params":{"start_z":-4.0,"stop_z":-2.0},
 "objects":[{"name":"wall_l","kind":"cube","pos":[-1.6,0,-2],"scale":[0.2,2.6,7],"color":"#c2c6c8"},
            {"name":"wall_r","kind":"cube","pos":[1.6,0,-2],"scale":[0.2,2.6,7],"color":"#c2c6c8"}],
 "characters":[{"name":"her","model":"y-bot-tpose","motion":[{"skill":"standIdle","f0":0,"args":{"at":[0,"${start_z}"]}},
                {"skill":"walkTo","f0":10,"args":{"to":[0,"${stop_z}"]}}]}],
 "camera":{"mode":"keys","keys":[{"frame":0,"pos":[0,1.4,1.0],"look":[0,1.0,-3],"focalMm":35},{"frame":119,"pos":[0,1.4,0.2],"look":[0,1.1,-2],"focalMm":35}]}}
```
library 에 이 예시와 함께 `seated_side_rail`(의자에 앉은 인물 + 옆을 따라 오르는 레일)도 넣는다.

## 검사(구현 뒤 Codex 가 할 것)
- `python3 cozy_preset.py list`, `show`, `apply corridor_walk_pushin --dry-run` 이 오류 없이 돈다.
- 실제 apply 는 하지 않는다(살아 있는 편집기 장면을 바꾸므로 Claude 가 한다).

## 하지 않을 것
- 코지클레이 node_modules·dist 수정 금지. 비밀값 없음. 네트워크는 cclay 가 쓰는 로컬 허브뿐.
