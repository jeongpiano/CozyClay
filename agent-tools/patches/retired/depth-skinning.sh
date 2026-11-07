#!/bin/bash
# 2026-11-06 t10(cctb-78 보고: CozyClay Depth(mp4) 에서 리깅 인물이 120프레임 내내 T자): 깊이 패스의 ShaderMaterial(render-passes.js DEPTH_VERTEX)에
#   스키닝 코드가 없어 SkinnedMesh 가 바인드 자세(T자)로 그려진다(노멀 패스는 MeshNormalMaterial 이라 정상). 빌드 묶음의 그 셰이더에 three.js 스키닝 청크를 넣는다.
#   멱등. 판을 올리면 다시 돌린다. 되돌리기 = dist/assets/app-*.js.orig (allow-ui-only.sh 와 같은 원본) — 두 패치 모두 되돌려짐에 주의.
set -e
D=~/tools/cozyclay/node_modules/cozyclay/dist/assets
F=$(grep -lF "varying float vViewDepth" "$D"/app-*.js | grep -v "\.orig$" | head -1)
[ -n "$F" ] || { echo "shader not found"; exit 1; }
[ -f "$F.orig" ] || cp "$F" "$F.orig"
python3 - "$F" <<'PY'
import sys
p=sys.argv[1]; s=open(p,encoding="utf-8").read()
if "skinning_vertex" in s[s.find("varying float vViewDepth")-50:s.find("varying float vViewDepth")+800]:
    print("already patched"); sys.exit(0)
old="\nvarying float vViewDepth;\nvoid main() {\n\tvec4 local = vec4(position, 1.0);\n#ifdef USE_INSTANCING"
new="\n#include <common>\n#include <skinning_pars_vertex>\nvarying float vViewDepth;\nvoid main() {\n#include <skinbase_vertex>\n#include <begin_vertex>\n#include <skinning_vertex>\n\tvec4 local = vec4(transformed, 1.0);\n#ifdef USE_INSTANCING"
assert s.count(old)==1, "pattern count %d" % s.count(old)
open(p,"w",encoding="utf-8").write(s.replace(old,new)); print("patched", p)
PY
