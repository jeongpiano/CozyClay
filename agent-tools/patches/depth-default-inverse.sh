#!/bin/bash
# 2026-11-07 cctb-44 원장 #32881(3.2.2 업데이트): 3.2.2 는 깊이 역수 곡선을 공식 옵션으로 넣었지만(#1096, 원장 PR) 메뉴 Export → Depth (mp4) 는
#   기본값 linear 로만 내보내고, inverse 를 고르는 명령(export.shotVideo)은 '편집기에서 사람 승인(confirm)' 이 필요해 헤드리스 도구가 못 부른다.
#   그래서 내보내기 함수의 depthCurve 기본값만 linear → inverse 로 바꾼다(가까운 얼굴·손의 굴곡이 살아남는 쪽). 판을 올리면 다시 돌린다(멱등).
#   되돌리기 = 같은 폴더 .orig-depthcurve 로 덮기. 원본에 '메뉴에서 곡선 고르기' 를 PR 로 내면 이 패치는 없앤다.
set -e
D=~/tools/cozyclay/node_modules/cozyclay/dist/assets
F=$(grep -lE 'depthCurve:[a-zA-Z_]+=`linear`' "$D"/app-*.js | grep -v '\.orig' | head -1)
[ -n "$F" ] || { grep -lE 'depthCurve:[a-zA-Z_]+=`inverse`/\*cctb44\*/' "$D"/app-*.js >/dev/null && { echo "already patched"; exit 0; }; echo "pattern not found"; exit 1; }
[ -f "$F.orig-depthcurve" ] || cp "$F" "$F.orig-depthcurve"
python3 - "$F" <<'PY'
import re,sys
p=sys.argv[1]; s=open(p,encoding='utf-8').read()
pat=re.compile(r'depthCurve:([A-Za-z_]+)=`linear`')
n=len(pat.findall(s)); assert n>=1, "count %d"%n
s=pat.sub(lambda m:'depthCurve:%s=`inverse`/*cctb44*/'%m.group(1), s)
open(p,'w',encoding='utf-8').write(s); print("patched",n)
PY
