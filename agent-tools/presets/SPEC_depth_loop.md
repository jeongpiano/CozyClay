# 깊이 영상으로 '뚫음·너무 붙음' 찾아 고치는 반복 — cozy_clearance 보강 (2026-11-07 cctb-44, 원장 #32899)

## 왜
cozy_clearance.py 의 몸 근사(캡슐)는 실제 회색 인형과 모양이 달라, S1w5 를 고쳐도 6.3~6.5초에 카메라가 허벅지를 뚫는다(원장 지적).
실제 렌더러가 내보낸 **깊이 영상**에 뚫음 신호가 보인다: 아주 가까운 면(깊이 밝기 >235, 역수 곡선) 비율이 화면의 15%↑ 였다가 0.25초 안에 2%↓로 뚝 떨어짐(카메라가 면 안으로 들어가 뒷면이 안 그려짐). 이 실측으로 고친다.

## 할 일 (파일 2개 수정·1개 추가, numpy·표준 라이브러리만)
1. `cozy_clearance.py` 에 함수 추가
   - `aim_path(spec) -> np.ndarray(frames,3)`: camera.aim 이 `["@이름"]` 이면 그 사물의 `path`(points[{x,y,z}], speed m/s)를 프레임 f 에서 이동거리 speed*f/24 로 따라간 점(끝에서 멈춤), path 없으면 그 사물 pos. aim 이 좌표면 고정점. 못 구하면 카메라 경로 무게중심.
   - `depth_problems(depth_mp4: str, fps=24, near_level=235, enter=0.15, leave=0.02, close=0.30) -> list[int]`: ffmpeg 로 92×52 회색조 프레임을 읽어 프레임별 near 비율. 문제 프레임 = (near ≥ enter 이고 다음 6프레임 안에 near ≤ leave 로 떨어지는 '뚫음' 프레임과 그 앞 6프레임) ∪ (near ≥ close '너무 붙음' 프레임). 정렬된 고유 목록.
   - `push_back(spec, frames: list[int], amount=0.12) -> (new_spec, report)`: camera_path 로 P(f), aim_path 로 A(f). 문제 프레임의 밀 방향 n = -unit(A-P)(바라보는 방향의 반대 = 몸에서 멀어지는 쪽), y 성분 0.5배 후 다시 단위화. raw = n*amount (문제 프레임만), required = amount, normals = n → 기존 `smooth_push` 로 부드럽게 → P+push → 기존 `write_rail`(rail) / keys 모드는 키 pos 만. report: {frames: 개수, windows: [[t0,t1]...], max_push_m}.
   - fix_spec 은 그대로 둔다(캡슐 검사가 1단계, 이 반복이 2단계).
2. `cozy_make_depth.py`: `make()` 가 깊이 영상을 저장한 뒤, spec 의 camera.passThrough.body 가 false 이고 `--no-clearance` 가 아니면 `depth_problems` 를 돌려 문제가 있으면 `push_back` 으로 고친 spec 으로 **다시 내보내기**(깊이·--preview 모두). 최대 `--depth-loop N`(기본 3)번. 매 회 결과를 `clearance.depth_loop` 목록에 {round, problems, windows, max_push_m} 로 남기고, 마지막 고친 spec 을 `<out stem>_spec_fixed.json` 으로 저장(덮어씀). 문제 0 이면 즉시 끝. N 회 뒤에도 남으면 결과 JSON `"depth_loop_unresolved": [초...]`.
   - 반복은 같은 잠금·같은 헤드리스 탭 흐름을 재사용하되, 복잡하면 make() 를 고친 spec 으로 다시 부르는 단순한 방법도 됨(잠금 중첩만 피할 것).
3. 시험 `test_clearance.py` 에 추가: depth_problems(합성 mp4 — 가까운 흰 면 비율이 0.4→0.0 으로 떨어지는 30프레임 영상을 ffmpeg 로 만들어) 뚫음 프레임 검출, push_back 이 문제 프레임에서 카메라-겨냥점 거리를 늘리고 다른 프레임은 ±σ 밖에서 거의 그대로(<1cm)인지, aim_path 가 path 를 따라가는지.

## 시험 실측(Claude 가 함 — Codex 는 편집기 띄우지 말 것)
Claude 가 `python3 cozy_make_depth.py --spec .../MQ_S1w5d_spec.json --preview ... --aim-per-frame` 로 실제 반복을 돌려 6.3~6.5초 뚫음이 사라지는지 본다.

## 하지 않을 것
node_modules·편집기 코드 수정 금지. 기존 시험 29개 깨지지 않게.
