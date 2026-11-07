# cozy_clearance.py 명세 — 카메라 투과 켬/끔(인체·사물 따로) + 부딪히면 자연스럽게 비켜 가는 경로 (2026-11-07 cctb-44, 원장 #32842·#32846)

## 목적
CozyClay 장면 JSON(spec, 예: /Users/open/content_studio/work/mosquito_cozy/MQ_S1w5_spec.json)의 카메라 레일이 사람 몸(팔다리·몸통·머리)이나 사물(의자·책상·벽) **속을 지나가지 않게**, 굽기 전에 경로를 고친다. 인체·사물 투과를 따로 켬/끔한다. 고친 spec 을 cozy_make_depth.py 가 그대로 쓴다.

## 새 파일
`/Users/open/tools/cozyclay/presets/cozy_clearance.py` (표준 라이브러리 + numpy 만). 머리말 5칸 한국어(목적·실행·요청·연결·이력/되돌리기) — 기존 파일들과 같은 양식.
- 함수로 쓸 수 있게: `fix_spec(spec: dict) -> (new_spec: dict, report: dict)`
- 명령줄: `python3 cozy_clearance.py <spec.json> --out <fixed.json> [--report <report.json>]` — 표준출력 마지막 줄 JSON `{"ok":true,"changed":bool,"min_before":{"body":m,"objects":m},"min_after":{...},"segments":[{"t0":초,"t1":초,"pushed_m":최대,"what":"thigh_r"}],"out":path}`

## spec 에 새로 읽는 칸 (없으면 기본값 — 기존 spec 은 그대로 동작해야 함)
```json
"camera": {
  "passThrough": {"body": false, "objects": false},
  "clearanceM": {"body": 0.12, "objects": 0.06},
  "solidExclude": ["floor", "aimDot"]
}
```
- `passThrough.body=true` 면 인체 검사 안 함. `objects=true` 면 사물 검사 안 함. 둘 다 true 면 spec 을 바꾸지 않고 그대로 돌려줌(changed=false).
- 사물 각자에 `"solid": false` 를 주면 그 사물은 투과 허용. 이름이 floor 이거나 kind 가 empty/plane/text/light/effect 인 것은 항상 제외. 바닥은 '카메라 높이 ≥ 0.05m' 로만 지킨다.
- 기본: 둘 다 false(투과 안 함).

## 사물 모양 (spec objects)
- 실측(CozyClay inspect): 사물 `pos` 의 y 는 **바닥면**(supportY), x·z 는 중심. `scale` 이 크기(m). 예: chair_leg pos y 0.01, scale y 0.42 → y 0.01~0.43.
- cube = 상자(OBB, `rot` [x,y,z]도 — y 회전만 있어도 됨), cylinder = 세로 원기둥(반지름 scale.x/2, 높이 scale.y), sphere = 구, capsule = 캡슐.
- 거리 = 점에서 그 모양 표면까지(안이면 음수).

## 인체 근사 (spec characters)
캐릭터마다 원기둥(캡슐) 묶음. 축 선분 + 반지름. 모든 치수는 `character.bodyModel` 로 덮어쓸 수 있게(아래 기본값은 y-bot 키 약 1.75m 기준 근사).
- 자세: motion 에 `sitInSeat`(args.seat="@이름" → 그 사물) 가 있으면 **앉음**, 없으면 `character.posture` 또는 서기.
- 앉음: 엉덩이 중심 H = seat 윗면 중심(seat.pos.y + seat.scale.y) + 0.08 위. 앞 방향 F(수평 단위벡터): `reachGrip` 의 anchor 가 kneeL/kneeR 인 손 위치가 있으면 H→그 점의 수평 방향, 없으면 character.rot(도, y축) 로 (sin,cos), 없으면 +z.
  - 허벅지 L/R: H ± 0.10·S(옆 방향) → 무릎 K = 그 점 + 0.45·F, y 는 seat 윗면+0.10. 반지름 0.085
  - 정강이: K → 발목 A = K + 0.05·F, y=0.09. 반지름 0.06. 발: A → A + 0.16·F, y 0.05, 반지름 0.05
  - 몸통: H → 목 N = H + (0,0.52,0) (+ 손이 턱/뺨 anchor(chin*/cheek*) 면 그 손 쪽으로 0.06 기울임). 반지름 0.16
  - 머리: N + (0,0.13,0) 중심 구 반지름 0.11 (턱 괴기면 손 쪽으로 0.05 기울임)
  - 팔 L/R: 어깨 Sh = N + (0,-0.04,0) ± 0.19·S. 손 W = reachGrip 의 define.p(그 side) 가 있으면 그 점, 없으면 무릎 위(K + (0,0.08,0)). 팔꿈치 E = (Sh+W)/2 + (0,-0.10,0) + 0.06·(옆 바깥). 위팔 Sh→E 반지름 0.05, 아래팔 E→W 반지름 0.045, 손 W 구 0.05
- 서기: 엉덩이 H = pos + (0,0.92,0), 무릎 (0,0.48,0), 발목 (0,0.08,0) (좌우 ±0.10), 몸통 H→H+(0,0.52,0), 팔은 몸 옆으로 내림(어깨 → 엉덩이 높이, 옆 0.22).
- 모델은 정지(자세가 영상 내내 같다고 봄). 동작이 큰 경우는 다음 단계(지금은 범위 밖) — report 에 "static_body_assumption": true.

## 카메라 경로 읽기
- `camera.mode == "rail"`: points [{x,z}] 폴리라인(길이 기준 균등 이동으로 가정), height 마크 [{t(레일 길이 비율), height}] 선형 보간, range [f0,f1] 이 이동 구간(그 밖은 끝점에 정지), frames = spec.frames(기본 360). 프레임 f 의 카메라 위치 P(f) = (x,z at 길이비율 u(f)) + y=height(u(f)).
- `camera.mode == "keys"`: keys[{frame,pos,...}] — 프레임 사이 선형 보간으로 P(f) 를 만들고, 고친 결과도 keys 로(키 pos 만 바꿈, 필요하면 키 추가 금지 — 키 사이 구간이 걸리면 report 에 경고만).
- 그 밖의 모드는 손대지 않고 report 에 "unsupported_mode".

## 고치기 (자연스러운 각도)
1. 프레임마다 P(f) 와 각 모양의 거리 d. 기준 c = clearanceM(인체/사물). d < c 인 프레임이 '닿음'.
2. 닿은 프레임의 밀어낼 양 = c - d, 방향 = 가장 가까운 모양 표면의 바깥 법선(캡슐이면 축에서 수직 방향, 상자면 가장 가까운 면 법선). **수평 성분 위주**: 법선의 y 성분은 0.5배로 줄인다(카메라가 갑자기 뜨거나 가라앉지 않게).
3. **부드럽게**: 밀어낸 벡터 열을 시간축 가우시안(σ = 0.35초 = 약 8프레임, ±3σ)으로 펼친다 — 그 구간 앞뒤로 서서히 휘었다 돌아오는 곡선이 되게. 펼친 뒤에도 그 프레임의 밀어낼 양 이상이 되도록 배율을 맞춘다(필요 최소).
4. 고친 경로를 다시 검사해 여전히 닿으면 2~3 반복(최대 6회). 그래도 남으면 report 에 남은 구간·최소 거리.
5. 레일로 되돌리기: 고친 P(f) 의 x,z 를 길이 균등으로 재표본해 points(2~512개, 기본 프레임 2개마다 1점)로. 높이는 새 길이 비율 기준으로 **8개 이하 마크**로 근사(구간 오차 최소가 되게 고르되, 처음·끝 포함). 레일 이동이 길이 균등이므로 '시간 → 위치' 가 원래와 크게 달라지지 않게, 새 레일의 길이 비율이 원래 프레임 순서를 따르게 재표본할 것(프레임 f 에서의 위치를 그대로 쓰면 됨).
6. aim(겨냥점)·focal·range 등 다른 값은 그대로.
7. 검사: 원래 spec 과 고친 spec 의 P(f) 를 비교해 최대 이동량, 프레임 간 속도 변화(가속 급변)가 원래보다 크게 늘지 않았는지(report 에 accel_max_before/after).

## cozy_make_depth.py 연결
- `make()` 에서 spec 을 읽은 직후 `fix_spec` 을 부른다(인자 `--no-clearance` 로 끌 수 있게). 바뀌었으면 고친 spec 을 `<out 이름>_spec_fixed.json` 으로 옆에 저장하고 결과 JSON 에 `"clearance": report 요약` 을 넣는다.
- 기존 동작(잠금·--preview·--aim-per-frame·검정 검사)은 그대로.

## 시험 (Codex 가 한다 — 편집기를 띄우는 실제 실행은 하지 않는다)
1. `python3 -m py_compile` 두 파일.
2. `MQ_S1w5_spec.json`(허벅지 속을 지나가는 판) → fix_spec: changed=true, min_before.body < 0 또는 < 0.12, min_after.body ≥ 0.11, segments 에 다리/몸통 구간.
3. 같은 spec 에 passThrough.body=true, objects=true → changed=false, spec 동일.
4. `MQ_S1w6_spec.json`, `MQ_S4b_spec.json` 도 돌려 report 출력(바뀐 곳·최소 거리).
5. 고친 레일 points 개수 2~512, height 마크 ≤8, 높이 ≥0.05.
결과를 이 폴더에 `test_clearance_report.md` 로(표 하나 + 어떤 구간을 얼마나 밀었나).

## 하지 않을 것
- node_modules·편집기 코드 수정 금지. 게이트웨이(content_studio) 코드 수정 금지.
- 사람 대신 굽기·편집기 조작 금지(Claude 가 한다).
