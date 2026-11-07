#!/bin/bash
# 목적: 레일 카메라가 겨냥(aim) 대상의 높이를 구간 평균 하나로 고정하던 것을 프레임별 높이로 따라가게 한다.
# 실행: 사람이 직접(판을 올리면 다시). 멱등. 되돌리기 REVERT=1 bash aim-per-frame.sh
# 선택(원장 #32169 "평균/프레임 높이 중 선택"): 샷 이름에 "[aim:frame]" 이 있으면 프레임별, 없으면 원래대로 평균(followCam 의 모르는 칸은 저장 때 지워져서 이름 표식을 씀).
#   프리셋은 camera.follow {"aimPerFrame": true} → cozy_preset 이 샷 이름에 표식을 붙인다
# 요청: 2026-11-07 cctb-44, 원장 #32143·#32146 "같은 레벨의 그 선을 바라보도록" — 모기 S1 나선(다리→얼굴). 원인 조사 Codex(1107-3b19f2):
#   rfe() 가 aimHeight: g.reduce(...)/m(평균)을 넘기고 HE() 가 AE(l,{x,y:i.aimHeight,z}) 로 그 평균만 씀 → 경로로 오르내리는 물체를 못 따라감.
# 연결: dist/assets/app-*.js (같은 파일에 depth-inverse·allow-ui-only 패치도 있음 — .orig 로 통째 되돌리지 말 것). 편집기 탭은 새로고침해야 반영.
set -e
D=~/tools/cozyclay/node_modules/cozyclay/dist/assets
F=$(grep -lF "aimHeight:g.reduce((e,t)=>e+t.y,0)/m" "$D"/app-*.js | grep -v "\.orig$" | head -1)
[ -n "$F" ] || F=$(grep -lF "cctb44-aim-per-frame" "$D"/app-*.js | grep -v "\.orig$" | head -1)
[ -n "$F" ] || { echo "pattern not found"; exit 1; }
python3 - "$F" "${REVERT:-0}" <<'PY'
import sys
p, revert = sys.argv[1], sys.argv[2] == "1"
s = open(p, encoding="utf-8").read()
pairs = [("{...u,aimHeight:g.reduce((e,t)=>e+t.y,0)/m,distanceInfluence:0,pitchOffsetDeg:0}",
          "{...u,aimPerFrame:/\\[aim:frame\\]/.test(r.name||``),aimHeight:g.reduce((e,t)=>e+t.y,0)/m,distanceInfluence:0,pitchOffsetDeg:0}"),
         ("{yaw:d,pitch:p}=AE(l,{x:y,y:i.aimHeight,z:b})",
          "{yaw:d,pitch:p}=AE(l,{x:y,y:i.aimPerFrame?e[t].y:i.aimHeight,z:b})/*cctb44-aim-per-frame*/")]
for a, b in pairs:
    src, dst = (b, a) if revert else (a, b)
    if dst in s and src not in s:
        print("already", a[:30]); continue
    assert s.count(src) == 1, "count %d: %s" % (s.count(src), src[:40])
    s = s.replace(src, dst)
open(p, "w", encoding="utf-8").write(s); print("reverted" if revert else "patched", p)
PY
