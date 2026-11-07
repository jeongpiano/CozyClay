<!-- 목적: 카메라 인체·사물 투과 방지 구현의 시험 결과와 재현 방법을 기록한다.
실행: 원장·후속 Codex가 읽고 아래 명령으로 재검증한다.
요청: 2026-11-07 원장 — SPEC_clearance.md 그대로 구현하고 시험 결과를 남길 것.
연결: cozy_clearance.py, cozy_make_depth.py, test_clearance.py, SPEC_clearance.md.
이력·되돌리기: --no-clearance로 끄거나 cozy_make_depth.py.bak-20261107-clearance를 복원한다. -->
# 카메라 clearance 시험 결과 — 2026-11-07

구현 및 명세의 필수 시험을 완료했다. `python3 -m py_compile cozy_clearance.py cozy_make_depth.py test_clearance.py` 성공, `python3 -m unittest -v test_clearance` **29개 전부 통과**. Python 3.14.8, numpy 2.5.1, 24fps 기준이다. 실제 편집기·게이트웨이 호출과 영상 굽기는 실행하지 않았다.

| 시험 입력 | changed / 보정 횟수 | 인체 최소 거리 전→후(m) | 사물 최소 거리 전→후(m) | 최대 이동(m) | 최대 가속도 전→후(m/s²) | points / height | 최소 높이(m) | 판정 |
|---|---|---|---|---|---|---|---|---|
| MQ_S1w5 | true / 3 | -0.029583 → 0.124697 | 0.139876 → 0.075931 | 0.198605 | 6.874734 → 6.085686 | 180 / 8 | 0.100000 | 통과, 잔여 충돌·경고 없음 |
| MQ_S1w6 | false / 0 | 0.166481 → 0.166481 | 0.078729 → 0.078729 | 0.000000 | 9.639666 → 9.639666 | 35 / 8 | 0.100000 | 통과, 잔여 충돌·경고 없음 |
| MQ_S4b | true / 3 | -0.038493 → 0.120124 | -0.004603 → 0.072000 | 0.376647 | 14.061724 → 17.963643 | 180 / 8 | 0.100000 | 통과, 잔여 충돌·경고 없음 |
| S1w5, passThrough 양쪽 true | false / 0 | 검사 생략 | 검사 생략 | 0 | 검사 생략 | 원본 35 / 8 | 원본 유지 | 통과, spec 전체 동일 |

S1w5의 인체 최소 거리는 음수에서 **0.124697m**로 개선돼 명세의 0.11m 합격선과 기본 간격 0.12m를 모두 만족한다. S1w6는 원래 안전하므로 spec을 변경하지 않았다. 세 입력 파일은 CLI 실행 전후 SHA-256이 동일했다.

**어떤 구간을 얼마나 밀었나**

시간은 첫 프레임을 0초로 한 양끝 포함 범위다. `pushed_m`은 해당 원래 충돌 프레임에서 보정 전후 카메라 위치의 최대 차이이며, 길이 균등 레일로 바꾸면서 생기는 시간별 위치 재배분도 포함한다.

- MQ_S1w5: `head` 13.167–13.417초, 최대 0.057780m; `thigh_l` 3.708–4.958초, 최대 0.198605m; `shin_l` 3.333–4.750초, 최대 0.198605m; `shin_r` 2.583–3.958초, 최대 0.198605m.

- MQ_S1w6: 충돌 구간 없음, 이동 0m.

- MQ_S4b: `torso` 11.083–11.167초, 최대 0.120095m; `head` 0.000–0.000초, 최대 0.018256m; `thigh_l` 10.917–11.292초, 최대 0.120095m; `shin_l` 11.875–12.292초, 최대 0.374537m; `shin_r` 11.542–12.167초, 최대 0.376647m; `seat` 10.833–11.583초, 최대 0.318721m; `seat` 14.833–14.958초, 최대 0.039338m.

S1w5의 최대 가속도는 감소했다. S4b는 27.7% 증가했다. 보고서의 `acceleration_increased` 경고 기준은 원래의 1.5배와 원래+0.5m/s² 중 큰 값을 넘을 때이며, 세 장면 모두 기준 이하다. 수치는 저장된 최종 레일을 다시 읽은 프레임별 위치의 2차 차분 × 24²로 계산했다.

**구현과 추가 검증**

`cozy_clearance.fix_spec()`은 입력을 복제하고 인체·사물을 독립적으로 검사한다. supportY 기준 상자(회전 XYZ 포함)·원기둥·구·캡슐의 부호 거리와 법선, 앉은/선 인체, knee 방향·턱/뺨 손 위치, solid 제외 규칙을 구현했다. Gaussian σ=0.35초, ±3σ로 보정 벡터를 펼치며 반대 법선의 상쇄가 전체 레일을 과하게 밀지 않도록 프레임별 배율 포락선을 사용한다. 높이 마크 압축·재표본 오차를 위한 0.012m 여유를 보정 프레임에 더하고, **저장 형태의 레일을 매회 재검사**한다. 최대 6회다.

레일은 수평 길이 균등으로 재표본하고 처음·끝을 포함한 최대 8개 높이 마크를 가장 큰 보간 오차부터 분할해 선택한다. 최종 points 2~512, 카메라 높이 0.05m 이상을 확인했다. 1·3·12프레임의 정지/수직 레일과 1,200프레임의 512점 상한도 시험했다. aim·focal·range·follow·다른 장면 필드는 보정 전후 동일하며 S1w5의 330프레임 뒤 끝점 정지도 유지된다.

`character.bodyModel`은 `cozy_clearance.BODY_DEFAULTS`의 모든 치수 이름을 덮어쓸 수 있다. 개별 부위는 예를 들어 `"head":{"a":[0,1.6,0],"radius":0.12}` 또는 `"thigh_r":{"a":[...],"b":[...],"radius":0.09}`로 월드 좌표를 지정한다. `b`를 생략한 `a` 재정의는 구로 처리한다. 모든 보고서에 `static_body_assumption: true`를 기록한다.

`cozy_make_depth.make()`는 spec 로드 직후 기존 매개변수 치환으로 좌표를 확정하고 보정한다. 바뀐 경우 `<out.stem>_spec_fixed.json`을 저장하고 반환 JSON의 `clearance`에 결과와 경로를 담는다. `--no-clearance`는 보정을 호출하지 않는다. 렌더러 모의 객체로 보정 spec 저장·적용 일치, 매개변수 override, --aim-per-frame, --preview, 검정 영상 실패 분기와 임시 파일 정리를 검증했다. 기존 잠금 처리 코드는 변경하지 않았으며 실제 다중 편집기 동시 실행은 시험 범위에 포함하지 않았다.

keys 모드는 기존 키의 pos만 변경한다. 키 시각이 불규칙해도 실제 프레임 간격으로 Gaussian을 계산한다. 안전한 두 키 사이의 경로만 상자를 통과하는 시험에서는 키를 추가하지 않고 `key_interpolation_collision`과 잔여 구간을 보고하는 것을 확인했다. 상자를 정면으로 대칭 관통하는 별도 레일은 서로 반대인 법선만으로 우회하지 못해 6회 뒤 `remaining_collisions`와 최소 거리를 보고했다. 이처럼 보고서의 `ok: true`는 검사 실행 성공이며, 모든 입력에서 충돌 해결을 보증하는 값은 아니다. 지원하지 않는 카메라 모드는 원본 spec을 그대로 반환하고 `unsupported_mode`를 남긴다.

**재현 방법과 산출물**

```sh
cd /Users/open/tools/cozyclay/presets
python3 -m py_compile cozy_clearance.py cozy_make_depth.py test_clearance.py
python3 -m unittest -v test_clearance
python3 cozy_make_depth.py --help
python3 cozy_clearance.py /Users/open/content_studio/work/mosquito_cozy/MQ_S1w5_spec.json --out /tmp/MQ_S1w5_fixed.json --report /tmp/MQ_S1w5_clearance.json
```

이번 CLI 실행의 세 장면 fixed JSON과 전체 report JSON 및 투과 시험 입력·출력은 `/private/tmp/cozy-clearance-20261107-mt68_q57`에 저장했다. CLI 마지막 줄 JSON과 --report 파일이 동일함을 검사했다. 구현은 표준 라이브러리와 numpy만 사용한다. 수정 전 깊이 생성 파일은 `cozy_make_depth.py.bak-20261107-clearance`에 보관했다.
