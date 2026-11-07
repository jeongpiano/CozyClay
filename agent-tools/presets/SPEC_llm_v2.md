# cozy_llm.py v2 — 콘티 그림·대본·앞뒤 씬을 읽고 배치·카메라·화각을 정한다 (2026-11-08 cctb-78, 원장 #33154·#33166)

## 목적
지금 cozy_llm.py 는 씬 JSON 글만 읽는다. 원장: "LLM 이 기본적으로 콘티와 대본, 앞뒤 씬의 흐름을 파악해서 기본적 배치와 카메라 움직임 화각 등을 설정, 피드백 받아 바로바로 수정". 대시보드(obsidian-ec)가 화면에서 부르고, 새 인자를 넘겨 준다.

## 새 인자 (모두 선택, 없으면 지금과 똑같이 동작 — 기존 호출 깨지면 안 됨)
- `--conti-image <png/jpg 절대경로>`: 이 씬 콘티 그림. 로컬 모델이면 Ollama `/api/generate` 의 `images:[base64]` 로 같이 보낸다(지금 local 경로가 이미 `_post(base+'/api/generate', {...})` 를 씀 — 거기에 images 추가). cloud/hermes/deepseek 는 그림 대신 `--conti-caption` 글이 있으면 그걸 쓰고, 없으면 그림 없이.
- `--conti-caption "<글>"`: 콘티 그림 설명(대시보드가 이미 가진 image_prompt 등).
- `--neighbors <json 파일>`: `{"prev": {"n":0,"summary":"...","end_frame":"<png 경로>","camera":"..."} | null, "next": {...} | null}` — 앞 씬 끝 상태와 다음 씬 시작을 이어지게 하라는 재료. 그림 경로는 로컬 모델이면 images 에 추가(최대 3장: 콘티·앞 끝·뒤 첫).
- `--script "<대사·지문>"`: 대본 원문(한국어 가능).
- `--preset <library 이름>`: 출발 프리셋을 지정(없으면 LLM 이 아래 카탈로그에서 고르거나 새로 짓는다).

## 프롬프트 보강 (SYSTEM 에 덧붙임, 영어)
1. **프리셋 카탈로그**: `library/*.json` 의 name·desc·camera_variants 이름을 한 줄씩 나열. "가장 맞는 프리셋을 출발점으로 쓰고 결과에 `"based_on": "<이름>"`, 고른 변형은 `"variant": "<이름>"` 로 적어라."
2. **화각 규칙**: shot size → focalMm·거리: extreme wide 16~20mm, wide 24~28mm(전신+공간), medium 35mm(허리 위), close-up 50~85mm(얼굴·어깨). 콘티 그림의 샷 크기·앵글(높낮이)·인물 화면 위치를 따라라.
3. **흐름 규칙**: 앞 씬 끝 카메라 쪽·인물 위치와 이어지게(같은 180도 선 쪽, 같은 인물 좌우), 다음 씬 첫 화면으로 자연스럽게 넘어가게 끝 구도를 잡아라.
4. **오늘 실측 규칙**: 카메라 길은 한 방향으로 매끈하게(급한 꺾임·되돌아가기 금지), 15초에 2바퀴 이상 금지, 의자·다리 사이 같은 좁은 틈을 지나가면 `camera.gap: true` 를 넣어라(거리 유지 3cm). 인물에 0.2m 보다 가깝게 가지 마라(틈 통과 제외).
5. 출력에 `"camera_story"`: 시각별 카메라 설명 한국어 3~6줄(예 "0~2초 식탁 옆 넓은 화면, 2~4초 B 어깨 너머로 A 에게 밀기") — 대시보드가 사람에게 보여 줌. 검사(validate)는 이 칸·based_on·variant 를 허용하고 장면 적용 전에 떼어 낸다(_normalize 또는 main 끝에서).
6. 피드백 모드: 지금처럼 전체 장면 + `changes`(문장 배열). 피드백 앞에 "[at 3.2s]" 같은 시각이 붙어 오면 그 시각 근처만 고쳐라.

## 출력 JSON 결과 (stdout 마지막 줄, 기존 키 유지 + 추가)
`{"ok":true, ..., "based_on": "...", "variant": "...", "camera_story": [...], "gap": bool}`

## 시험 (Codex 가 실행 — 실제 LLM 호출 1~2번은 local 로 해도 됨, 편집기·렌더 금지)
- 기존 호출(새 인자 없음)이 같은 꼴로 동작(--help·인자 파싱, validate 단위 시험).
- 새 인자 파싱·이미지 base64 첨부가 요청 본문에 들어가는지(요청 만드는 함수를 분리해 단위 시험).
- 실제 1회: `/Users/open/content_studio/projects/itest_50_mosquito_cozy/production/production.json` 씬 1 을 --scene-json 으로(그 씬 dict 를 임시 파일로), 콘티 그림은 그 씬 폴더의 conti 이미지(있으면), --neighbors 는 씬 2 요약으로 → 결과 spec·camera_story 를 `SPEC_llm_v2_report.md` 에.

## 하지 말 것
core/(대시보드) 코드 수정 금지 — 새 인자 목록만 보고서에 적어 Claude 가 대시보드 세션에 전달. 기존 library JSON 수정 금지.
