# agent-tools — 원장님 제작 파이프라인용 CozyClay 도구 (JYCEnt 브랜치)

> 목적: CozyClay(원본 HaD0Yun/CozyClay)를 AI 영상 프리비즈(회색 참조 영상·깊이 영상)로 쓰기 위해 우리가 만든 명령줄 도구와 편집기 패치를 원본과 분리해 보관한다.
> 실행: 맥 M3 에서 `~/tools/cozyclay`(npm 으로 깐 cozyclay) 옆에 두고 쓴다. 대시보드(content_studio)·Claude·Codex 가 부른다.
> 요청: 2026-11-07 원장 #32852·#32858 "내 github 포크에 올리면서 진행", #32879 "원본 업데이트도 받을 수 있게".
> 연결: 편집기 http://127.0.0.1:5180/app, 라이브 허브 5184, `node_modules/.bin/cclay`. 운영 문서 옵시디언 `projects/제작-대시보드/조립기-개선/21-콘티마법사-코지클레이-영상생성-인수인계-2026-11-07.md`.
> 이력: 2026-11-07 cctb-44 처음(3.2.2 기준).

## 운영 원칙
- 포크 `main` = 원본 그대로(gh repo sync). 우리 것은 이 폴더 + `JYCEnt` 브랜치에만 → 원본 업데이트 때 충돌 최소.
- 편집기 본체를 고쳐야 하는 일반 기능은 원본에 PR(이미 #1094 깊이 뼈대·#1095 레일 겨냥 높이·#1096 깊이 역수 곡선이 3.2.2 에 들어감 → `patches/retired/`).

## presets/ (명령줄 도구)
| 파일 | 하는 일 |
|---|---|
| `cozy_preset.py` | 장면 JSON(spec) → 편집기에 세트·인물·동작·카메라 적용(`cclay live`) |
| `cozy_make_depth.py` | 헤드리스 편집기로 spec 을 적용해 깊이 영상·회색 미리보기(--preview) mp4 를 뽑음. `--aim-per-frame`, 검정 화면 검사, **투과 검사 자동 적용**(`--no-clearance` 로 끔) |
| `cozy_clearance.py` | **카메라 투과 켬/끔(인체·사물 따로)** — spec `camera.passThrough {body, objects}`, `clearanceM`. 닿는 구간을 가장 가까운 몸/사물 바깥으로 밀고 가우시안(σ 0.35초)으로 부드럽게 휘게 고친 레일을 돌려줌. 시험 `test_clearance.py`(29개) |
| `cozy_llm.py` | 말로 쓴 장면 설명 → spec(로컬·클라우드·hermes·deepseek) |
| `library/*.json` | 장면 프리셋(복도 밀어넣기, 호리존 줄서기, 옆 레일 앉은 인물, 지하철 승객) |
| `SPEC*.md` | 각 도구 명세 |

## patches/ (설치된 편집기 dist 에 덧대는 것 — 판을 올리면 다시 돌림, 멱등)
| 파일 | 왜 |
|---|---|
| `allow-ui-only.sh` | 카메라 키·렌즈 등 'ui-only' 명령을 라이브 허브에서도 부르게(원본은 #1091 거절 — 우리 쪽 유지) |
| `depth-default-inverse.sh` | 3.2.2 의 메뉴 Export → Depth(mp4) 기본 곡선을 linear → inverse(공식 옵션 #1096 은 승인 필요라 헤드리스가 못 부름) |
| `retired/*` | 3.2.2 에 원본으로 들어가 더 안 씀 |

## 업데이트 절차
1. `gh repo sync jeongpiano/CozyClay -b main` → `git rebase main` (JYCEnt)
2. `cd ~/tools/cozyclay && npm install cozyclay@<새 판>` (백업 `_bak_<판>`)
3. `bash patches/allow-ui-only.sh; bash patches/depth-default-inverse.sh` → `launchctl kickstart -k gui/$(id -u)/com.open.cozyclay`
4. 시험: `python3 -m unittest test_clearance` + `cozy_make_depth.py --spec <spec> --preview ...` 로 깊이·회색 확인

- 2026-11-07 cctb-44: 브랜치 이름 jjeclinic → JYCEnt (원장 #32926, GitHub rename — 옛 이름 링크는 자동 연결)
