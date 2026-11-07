# 바라보기 구역(look zones) — 레일 카메라가 경로의 어느 구간·어느 반경 안에 있을 때 목표를 바라보게 (2026-11-07 cctb-44, 원장 #32907·#32909·#32912·#32913)

## 원장 요구 원문
- "카메라 특정 위치 혹은 어디 근처에서는 카메라가 어디를 중점적으로 바라보도록 하는 기능"
- "경로의 어디에, 어느 범위에 있을때, 목표 지점을 바라보고, 거기를 넘어나면 기본 세팅값(평균 혹은 같은레벨)을 바라본다."
- "범위는 슬라이더로 조정, 영향이 미치는 범위는 화면에 영역표시" (← 2단계, 이번 범위 밖. 단 엔진 함수는 화면이 그대로 쓸 수 있게 순수 함수로)
- 시험 시나리오: 앉은 인형의 무릎 사이에 '괴물' 표식, 카메라가 무릎 근처에 오면 괴물을 비춘다.

## 저장소·가지
- 저장소 `~/src/CozyClay` (원장 포크). **`main` 에서 새 가지 `feat/look-zones`** 를 따서 작업한다(나중에 upstream PR 로도 낼 수 있게 agent-tools 없이 깨끗하게). 끝나면 커밋까지만(메시지 영어, 도구 서명 금지). push·merge 는 Claude 가 한다.
- 저장소 규칙 `AGENTS.md` 의 린트 래칫(250줄 넘는 순수 파일 늘리지 않기, knip 미사용 export 금지, eslint)을 지킨다. 길어지면 새 파일 `src/camera-look-zones.js` 로 뺀다.

## 지금 구조 (읽고 시작)
- `src/camera-block.js` — `cloneRailAim` / `railShotFields(value, cameraRail)`: 레일이 있을 때만 `aim`·`focalMm` 를 블록에 싣는다(없으면 바이트 그대로 — 옛 샷이 안 바뀌게).
- `src/camera-direction.js` `buildShotCameraTracks` — 레일 샷: aim 이 있으면 프레임별 aim 점(`railAimPoint`)을 subject 로 넘겨 `buildRailFollowTrack(aimed, …, { aimPerFrame: true, distanceInfluence: 0, pitchOffsetDeg: 0 })`, 없으면 따라가는 인물(subjectSlice)로.
- `src/camera-follow.js` `buildRailFollowTrack` (418행~) — 레일 위치 s(f)·크레인 높이·겨냥 스프링(aimOmega)으로 프레임별 {pos, yaw, pitch, s}. 겨냥 y 는 507행.
- `src/commands/shot.js` `setRail` (133행~) — 액션 `shot.setCameraRail { points, height, aim, aimHeight, focalMm }`. 입력 스키마·설명이 어디 등록되는지 찾아 같이 고친다.

## 1단계 할 일 (엔진 + 명령 + 시험)
1. **블록 칸** `camera.lookZones` (레일 있을 때만, 최대 8개, 비면 칸 자체를 안 싣는다 — 옛 샷 바이트 그대로):
   ```json
   { "id": "z1", "target": { "ids": ["monster"] } | { "point": {"x":0,"y":0.5,"z":0.3} },
     "height": 0.45,              // 선택: target ids 일 때 겨냥 높이(m). 없으면 castAimPoint(사물은 가운데, 인물은 가슴)
     "range": { "t0": 0.30, "t1": 0.55 },     // 레일 길이 비율 구간(0..1)  — 둘 중 하나 또는 둘 다
     "near": { "x": 0.2, "z": 0.6, "radius": 0.6 },   // 이 점(바닥 x,z)에서 카메라 수평거리 radius(m) 안
     "feather": 0.08,             // 경계 번짐: range 면 레일 비율, near 면 m. 기본 range 0.05 / near 0.25
     "strength": 1.0 }            // 구역 한가운데서 목표 쪽으로 끄는 정도 0..1, 기본 1
   ```
   정규화 함수(`cloneLookZones`)가 이상한 값은 버리거나 잘라낸다(t 는 0..1 로, t0<t1, radius>0, ids 는 이 장면 cast 만 — 명령에서 STALE_TARGET).
2. **무게 w(f)**: range 는 레일 진행 비율 u=s/rail.length 에 대한 smoothstep 사다리꼴(t0-feather→t0 에서 0→1, t1→t1+feather 에서 1→0). near 는 카메라 수평거리 d 에 대해 d≤radius 면 1, radius+feather 에서 0 (smoothstep). 둘 다 있으면 곱. 구역 여러 개가 겹치면 w 가 큰 것 우선(또는 w 로 정규화 가중평균 — 하나 골라 주석에 이유).
3. **겨냥 섞기**: 기본 겨냥점 B(f) = 지금 쓰는 것(aim 있으면 railAimPoint, 없으면 따라가는 인물 x,z + aimHeight). 목표 T(f) = zone target(ids 면 castAimPoint 로 프레임마다 — 움직이는 괴물도 따라가게). 최종 A(f) = lerp(B, T, w·strength). **구역 밖이면 정확히 B** — 원장 "넘어나면 기본 세팅값".
   - 카메라 위치가 필요하므로 2패스: (1) 지금처럼 트랙을 한 번 만들어 s(f)·pos(f) 를 얻고 (2) w(f) 계산 → A(f) 를 subject 로 `aimPerFrame: true` 로 다시 만든다. 위치는 겨냥과 무관해야 하니(aimed 경로는 distanceInfluence 0) 두 패스의 pos 가 같아야 한다 — **aim 없는 따라가기 레일은 distanceInfluence 가 subject 에 걸리므로, 2패스에서도 위치는 1패스 위치를 그대로 쓰고 겨냥만 바꾸는 방식**으로(예: buildRailFollowTrack 에 `aimOverride(f)` 선택 인자 — 있으면 겨냥 목표만 그 점으로, 스프링은 그대로). 어느 쪽이든 "lookZones 없는 샷은 결과가 한 비트도 안 바뀐다"를 시험으로 지킨다.
   - 겨냥 스프링(aimResponse)이 그대로 걸려 전환이 부드럽다. 추가로 번짐이 0 이어도 튀지 않는지 시험.
4. **화면용 순수 함수** export(2단계 UI 가 쓸 것, knip 때문에 지금 시험에서 import 해서 쓰면 됨): `lookZoneWeights(track, rail, zones) -> number[]` 와 `lookZoneRailSpans(zones) -> [{id, t0, t1, feather}]`.
5. **명령**: `shot.setCameraRail` 에 `lookZones` 인자(배열, null=지움) 추가 + 설명 문장 한 줄. 별도 액션 `shot.setLookZones { shotId, lookZones }` 도 추가(레일 다시 그리지 않고 구역만 바꾸게 — 슬라이더가 쓸 것). 영수증 note 에 "look zones: z1 30–55% → monster" 처럼.
6. **내보내기·검증 경로**: `cclay live verify --checks framing` 의 geometry.shots[].camera.lookAt 과 Depth 내보내기가 같은 `buildShotCameraTracks` 를 쓰는지 확인(다른 경로가 있으면 거기도 같은 결과가 나오게).
7. **시험** (`test/verify-camera-look-zones.mjs` 새로, run-tests 목록에 등록되는 방식 확인):
   - lookZones 없는 샷: 기존 트랙과 완전히 같음(pos·yaw·pitch 깊은 비교).
   - range 구역 한가운데 프레임: 카메라 시선(yaw/pitch 로 만든 방향)이 목표 쪽을 향함(각도 오차 < 3°, 스프링 정착 뒤 프레임).
   - 구역 밖 충분히 먼 프레임: 기본 겨냥과 같음(< 0.5°).
   - near 구역: 반경 안/밖 동일 검사.
   - 경계 지나는 동안 프레임 간 yaw 변화량 최대치가 구역 없는 판의 3배 이하(튐 없음).
   - cloneLookZones 정규화(잘못된 값 버림, 9개면 8개).
   - 명령 왕복: setLookZones → 블록에 저장 → 다시 읽음.
8. 기존 시험 중 camera·shot 관련(`ls test | grep -i -E "camera|shot|rail"`)과 `npm run lint` 를 돌려 통과 확인. `npm test` 전체(build 포함)는 시간이 길면 camera/shot 관련만 + build 한 번.

## 하지 말 것
- 2단계 UI(슬라이더·영역 표시)는 이번에 만들지 않는다 — 단 4번 함수까지.
- 편집기를 띄워 조작하지 않는다(Claude 가 한다). 5180/5184 포트 쓰지 말 것(라이브 편집기 사용 중).
- `main` 에 커밋·push 금지. node_modules·패키지 버전 변경 금지.

## 끝나면 보고
바꾼 파일·줄 수, 새 시험 결과, lint 결과, 커밋 해시. 결정한 것(겹침 처리·2패스 방식)과 이유 한 줄씩.
