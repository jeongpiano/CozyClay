# 드라마 촬영 프리셋 1차 — 대화 8종 (2026-11-08 cctb-78, 원장 #33156·#33158·#33166 "모두 진행")

## 목적
콘티마법사에서 장면 종류만 고르면(또는 LLM 이 골라) 인물·소품 배치 + 기본 카메라가 바로 나오는 출발점. 원장 확인 후 나머지(이동·탈것·장소·공연)로 넓힌다.

## 만들 파일 (`~/tools/cozyclay/presets/library/` 에 새 JSON 8개)
모양은 기존 `library/*.json`(특히 seated_side_rail.json, subway_car_riders.json, corridor_walk_pushin.json)과 같은 꼴 + `_header`(목적·실행·요청·연결·이력·되돌리기, 한국어).
1. `drama_table_facing` — 식탁에 마주 앉은 2인(A·B), 식탁·의자 2
2. `drama_cafe_facing` — 카페 작은 원탁 마주 앉기, 뒤 카운터·벽
3. `drama_office_desk` — 사무실 책상 사이 마주(한 명 앉고 한 명 서서 이야기)
4. `drama_sofa_side` — 소파에 나란히 앉은 2인, 앞 낮은 탁자
5. `drama_car_front` — 자동차 앞좌석 2인(운전석·조수석, 차 실내를 상자로: 대시보드·좌석·문·천장 없음)
6. `drama_elevator` — 엘리베이터 안 선 2인(좁은 상자 방)
7. `drama_meeting_room` — 회의실 긴 탁자 4~6인
8. `drama_phone_single` — 혼자 서서 통화(창가), 화면 나누기용 단독

각 파일 규칙
- frames 기본 120(5초). params 에 숫자만(거리·높이 등), 문자열 금지.
- 인물 model 은 y-bot-tpose/x-bot-tpose 섞어서, 앉는 사람은 `sitInSeat`, 선 사람은 `standIdle`(heading 으로 서로 마주 보게).
- 크기 실측 기준: 식탁 높이 0.75, 의자 좌판 0.45, 소파 좌판 0.42, 차 좌석 0.35, 엘리베이터 2.0×1.6×2.4.
- **카메라 변형 `camera_variants`**: 같은 파일 안에 이름: camera 객체 3~5개. 대화 장면은 반드시 `wide`(두 사람 다 보이는 넓은 화면, 180도 선 한쪽), `ots_a`(B 어깨 너머로 A), `ots_b`(A 어깨 너머로 B, wide 와 같은 쪽), 그리고 장면에 맞는 움직임 1~2개(`push_in` 천천히 밀기, `half_orbit` 반 바퀴, `track_side` 옆 따라가기 등). 기본 `camera` 는 `wide` 와 같게.
- 카메라는 기존 규칙: 움직임은 rail(points 2~40, height, aim ["@이름"], aimHeight, focalMm, range [0,frames-1]), 고정·밀기는 keys 정확히 2개. 대화 화각: wide 24~28mm, ots 50~85mm, 단독 35~50mm.
- 벽: 인물 뒤 1~3m 에 한 면 + 짧은 옆벽 하나까지(깊이 범위). 카메라 레일을 벽으로 둘러싸지 말 것.
- 180도 규칙: 두 사람을 잇는 선의 한쪽에만 카메라.

## 코드 수정
`cozy_preset.py`: `apply` 에 `--variant <이름>` — 있으면 `camera_variants[이름]` 을 `camera` 로 써서 적용. `list --json` 에 각 프리셋의 variants 이름 목록도. `show` 에도 표시. 머리말 이력 한 줄 + 고친 자리 '날짜·누구·왜' 주석.

## 검사(Codex 가 실행 — 편집기 띄우지 말 것, 5180/5184 쓰지 말 것)
- 8개 모두 `python3 cozy_preset.py apply <이름> --dry-run` 과 각 variant 마다 `--variant v --dry-run` 이 오류 없이 명령 목록을 냄.
- `python3 -c` 로 각 파일 JSON 파싱·frames·range·keys 개수 검사, 카메라 레일 점이 인물 0.3m 안을 지나지 않는지(cozy_clearance.fix_spec 의 min_before.body ≥ 0.25 를 report 로).
- 결과 표를 `SPEC_presets_drama_report.md` 로.

## 하지 말 것
기존 library 4개·다른 프리셋 도구 수정 금지(cozy_preset.py 만). node_modules 금지. 렌더 금지.
