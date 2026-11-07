#!/bin/bash
# 2026-11-06 t10(원장 #31714 "cozyclay 를 할수 있게 풀어줘"): CozyClay 의 "ui-only" 명령(카메라 키·렌즈·cast.replace 등)을
#   live(MCP·cclay live) 에서도 부를 수 있게 빌드 묶음의 거절 한 줄을 끈다. live 허브는 127.0.0.1 + 토큰이라 바깥에서는 못 부른다.
#   판을 올리면 이 패치가 사라지니 다시 돌린다(멱등). 되돌리기 = 같은 폴더 .orig 파일로 덮기.
set -e
D=~/tools/cozyclay/node_modules/cozyclay/dist/assets
F=$(grep -rlF "available only from the Studio UI" "$D" | head -1)
[ -n "$F" ] || { echo "guard not found"; exit 1; }
if grep -qE 'if\(!1&&[A-Za-z_]+\.exposure===`ui-only`' "$F"; then echo "already patched: $F"; exit 0; fi
[ -f "$F.orig" ] || cp "$F" "$F.orig"
python3 - "$F" <<'PY'
import sys
p=sys.argv[1]; s=open(p,encoding="utf-8").read()
import re
pat=re.compile(r"if\((\w+)\.exposure===`ui-only`&&(\w+)\(`CAPABILITY_MISSING`")
# 2026-11-07 cctb-44: 3.2.2 에서 변수 이름이 바뀜(n→e, K2→V2) — 이름에 상관없이 찾는다
assert len(pat.findall(s))==1, "pattern count %d" % len(pat.findall(s))
open(p,"w",encoding="utf-8").write(pat.sub(lambda m: "if(!1&&%s.exposure===`ui-only`&&%s(`CAPABILITY_MISSING`" % (m.group(1),m.group(2)), s))
PY
echo "patched: $F"
