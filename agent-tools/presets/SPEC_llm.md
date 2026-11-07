# cozy_llm.py 명세 + cozy_make_depth.py --spec (2026-11-06 cctb-44, 원장 #32056·#32058)

## 목적
씬 글(지문·대사·카메라·길이)이나 사람의 피드백 문장을 LLM 에 주면, 코지클레이 **장면 JSON**(프리셋 파일과 같은 꼴)을 돌려준다.
대시보드(ec)가 [씬 글로 자동]·[피드백으로 고치기] 단추에서 부른다.

## 1. 새 파일 `~/tools/cozyclay/presets/cozy_llm.py`
```
cozy_llm.py --scene-json <씬 JSON 파일> [--feedback "<문장>"] [--current <지금 장면 JSON 파일>] --seconds S --out <spec.json 절대경로>
```
- 씬 JSON: 대시보드 production.json 의 씬 하나(키 description, video_action|h3_action, camera, shot, dialogue, duration_s …). 없으면 비어도 됨.
- LLM 호출: `sys.path.insert(0, "/Users/open/content_studio")` 후 `from core.llm import llm_chat` → `llm_chat(prompt, system=SYSTEM, json_mode=True, timeout=180)`(dict 반환). 실패하면 한 번 더, 그래도 실패면 `{"ok":false,"error":...}`.
- SYSTEM 프롬프트(영어로 써도 됨)에 넣을 것:
  - 출력 = 프리셋 JSON 하나: `{name, desc, frames, params:{}, objects:[{name,kind(cube|cylinder|sphere),pos:[x,y,z],scale:[sx,sy,sz],color, path?:{points:[{x,y,z}],speed?}}], characters:[{name, model:"y-bot-tpose"|"x-bot-tpose", motion:[{skill,f0,args}]}], camera:{mode:"rail"|"keys", ...}}` — 정확한 꼴은 `library/*.json` 두 개를 프롬프트에 예시로 그대로 넣는다(파일에서 읽어서).
  - 좌표: 미터, y 위, 인물 정면 기본 +z(heading 0), 카메라는 보통 +z 쪽. 바닥 y=0, 물체 position 은 바닥 기준.
  - 동작 기술과 인자: standIdle{at:[x,z],heading,until} · walkTo{to:[x,z],steps,step,period}(길이 16+steps*period+18 프레임, f0+길이 ≤ frames-1) · sitInSeat{seat:"@상자이름"}(상자는 인물 뒤) · reachGrip{anchor,side:"l"|"r",reach,hold,release,define:{kind:"world",p:[x,y,z]}}(팔 길이 0.6m 안) · hitReaction{from:"object:@이름",speed} · throwObject/catchObject.
  - 카메라 규칙: 움직이거나 도는 카메라는 rail(points 2~40개, height 숫자 또는 [{t,height}] 0.1m 이상, aim [@인물] + aimHeight 또는 {x,y,z}, focalMm, range:[0,frames-1]); 고정·단순 밀기만 keys 2개. 키 3개 이상 금지(끊김).
  - 막힌 방으로 짓기(인물 뒤 1~3m 에 벽) — 깊이 범위가 넓으면 몸이 뭉친다.
  - 잠든·모르는 사람 몸을 아래에서 올려다보거나 옷 속을 보는 카메라 금지.
  - frames = round(seconds*24).
- 피드백 모드(`--current` 와 `--feedback` 둘 다 있을 때): "지금 장면 JSON + 피드백 → 고친 장면 JSON 전체"를 돌려받는다. 바뀐 칸을 `changes:[문장]` 로 같이 받는다.
- 결과 검사(파이썬): 필수 키, frames 일치, 인물 motion 각 f0 < frames, rail points ≥2, height ≥0.1. 틀리면 그 오류 목록을 붙여 LLM 에 한 번 고쳐 달라고 다시 묻는다.
- 출력: `--out` 에 장면 JSON 저장, stdout 마지막 줄 `{"ok":true,"spec":out,"changes":[...],"model":...}`.
- 머리말 5칸(한국어).

## 2. `cozy_make_depth.py` 에 `--spec <장면 JSON 파일>` 추가
- `--preset` 과 둘 중 하나. `--spec` 이면 그 JSON 을 프리셋처럼 적용(`cozy_preset.apply` 가 dict 도 받게 정리).

## 검사(Codex)
- `python3 cozy_llm.py --help`, `python3 -m py_compile` 세 파일.
- 진짜 LLM 호출 한 번: library 의 seated_side_rail 설명으로 만든 가짜 씬 JSON(`{"video_action":"She sits on a stool in a corridor; the camera slowly circles her at chest height.","duration_s":5}`)으로 `cozy_llm.py` 실행 → 결과 JSON 이 검사 통과하는지. (편집기 적용·깊이 내보내기는 하지 않음)
