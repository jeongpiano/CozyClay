#!/bin/bash
# 2026-11-06 cctb-44 원장 #32007 "코지클레이 앞뒤 구분되는 방법 연구": 깊이 패스가 near~far(장면 최소~최대, 최대 40m)를 직선으로 나눠
#   근접(0.1~0.3m)의 얼굴 굴곡이 1단계로 뭉개진다(M1 깊이 얼굴 영역 16비트 값 1종 실측). 역수 깊이(1/d, Depth Anything·MiDaS 와 같은 꼴)로 바꿔
#   가까운 곳에 단계를 몰아준다. 멱등. 판을 올리면 다시 돌린다.
#   되돌리기 = 이 파일의 REVERT=1 로 실행(셰이더 한 줄만 원래대로) — dist/assets/app-*.js.orig 는 다른 패치까지 되돌리니 쓰지 말 것.
set -e
D=~/tools/cozyclay/node_modules/cozyclay/dist/assets
F=$(grep -lF "varying float vViewDepth" "$D"/app-*.js | grep -v "\.orig$" | head -1)
[ -n "$F" ] || { echo "shader not found"; exit 1; }
[ -f "$F.orig" ] || cp "$F" "$F.orig"
python3 - "$F" "${REVERT:-0}" <<'PY'
import sys
p, revert = sys.argv[1], sys.argv[2] == "1"
s = open(p, encoding="utf-8").read()
lin = "float normalized = clamp((vViewDepth - uNear) / max(uRange - uNear, 0.0001), 0.0, 1.0);\n\tfloat grey = 1.0 - normalized;"
inv = "float grey = clamp((1.0 / max(vViewDepth, 0.0001) - 1.0 / max(uRange, 0.0001)) / max(1.0 / max(uNear, 0.0001) - 1.0 / max(uRange, 0.0001), 0.0001), 0.0, 1.0); /*cctb44-inverse-depth*/"
src, dst = (inv, lin) if revert else (lin, inv)
if dst in s and src not in s:
    print("already", "reverted" if revert else "patched"); sys.exit(0)
assert s.count(src) == 1, "pattern count %d" % s.count(src)
open(p, "w", encoding="utf-8").write(s.replace(src, dst)); print("reverted" if revert else "patched", p)
PY
# 2) 깊이 범위의 near 를 내린다 — 탐색 그림에서 0.157m 보다 가까운 면이 있었던 영상만(min=0 프레임) near=max(카메라 near, 0.03m), 아니면 원래 값.
#    (11-06 첫 판은 무조건 카메라 near 로 내려 2m 거리 인물이 거의 검게 나왔다 — test_make_depth 실측)
# (옛 설명) 범위는 0~40m 를 8비트(한 단계 0.157m)로 찍은 탐색 그림에서 구해서,
#    0.157m 보다 가까운 얼굴은 min=0 → 버려지고 near 가 0.157m 로 잡혀 얼굴 전체가 흰색으로 잘렸다(M1 실측). 빌드 이름이 바뀌면 패턴을 다시 찾는다.
python3 - "$F" "${REVERT:-0}" <<'PY'
import sys
p, revert = sys.argv[1], sys.argv[2] == "1"
s = open(p, encoding="utf-8").read()
a = "t=_we(n,wd.current.near,40)}"
b = "t=_we(n,wd.current.near,40);t={near:(n.some(e=>!(e.min>0))?Math.max(wd.current.near,0.03):t.near),far:t.far}/*cctb44-near2*/}"
old_b = "t=_we(n,wd.current.near,40);t={near:Math.min(t.near,wd.current.near),far:t.far}/*cctb44-near*/}"
s = s.replace(old_b, a)  # 첫 판(카메라 near 무조건) → 원래대로 돌린 뒤 새 판 적용
src, dst = (b, a) if revert else (a, b)
if dst in s and src not in s:
    print("near already", "reverted" if revert else "patched"); sys.exit(0)
assert s.count(src) == 1, "near pattern count %d" % s.count(src)
open(p, "w", encoding="utf-8").write(s.replace(src, dst)); print("near", "reverted" if revert else "patched")
PY

# 3) (11-06 22:2x 다시 고침) 범위 탐색 그림도 같은 셰이더(역수)로 찍히므로, 탐색 값을 역수로 풀어 거리로 바꾼다.
#    (이게 없으면 탐색 거리가 틀려 화면 전체가 흰색으로 잘렸다 — test_make_depth 실측). 2) 의 near 손질은 원래대로 되돌린다.
python3 - "$F" "${REVERT:-0}" <<'PY'
import sys
p, revert = sys.argv[1], sys.argv[2] == "1"
s = open(p, encoding="utf-8").read()
plain = "t=_we(n,wd.current.near,40)}"
for old in ("t=_we(n,wd.current.near,40);t={near:(n.some(e=>!(e.min>0))?Math.max(wd.current.near,0.03):t.near),far:t.far}/*cctb44-near2*/}",
            "t=_we(n,wd.current.near,40);t={near:Math.min(t.near,wd.current.near),far:t.far}/*cctb44-near*/}"):
    s = s.replace(old, plain)
lin = "n.push({min:40*(1-s/255),max:40*(1-o/255)})"
inv = "n.push({min:1/((s/255)*(1/wd.current.near-1/40)+1/40),max:1/((o/255)*(1/wd.current.near-1/40)+1/40)})/*cctb44-probe-inv*/"
src, dst = (inv, lin) if revert else (lin, inv)
if dst in s and src not in s:
    open(p, "w", encoding="utf-8").write(s); print("probe already", "reverted" if revert else "patched"); sys.exit(0)
assert s.count(src) == 1, "probe pattern count %d" % s.count(src)
open(p, "w", encoding="utf-8").write(s.replace(src, dst)); print("probe", "reverted" if revert else "patched")
PY
