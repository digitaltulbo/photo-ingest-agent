# photo-ingest-agent

macOS + 외장 SSD + Lightroom Classic 중심의 개인 사진 워크플로우 보조 CLI입니다. 목표는 완전 자동 보정이 아니라 **안전한 가져오기, 원본 보호, 실패 컷 후보 리포트, 촬영 기록, 인스타 업로드 준비**입니다.

## 실제 사용법

개발 명령어를 몰라도 되도록 바탕화면에 실행 파일을 둡니다.

1. 메모리카드를 Mac mini에 꽂습니다.
2. 바탕화면의 `Photo Ingest Today.command`를 더블클릭합니다.
3. 달력 팝업에서 촬영 날짜를 선택합니다.
4. 팝업창에서 저장 위치, 촬영명, 장소를 입력합니다.
5. 카메라와 렌즈는 JPG 파일의 EXIF에서 읽은 값이 있으면 자동으로 기본 입력됩니다. 틀리거나 비어 있으면 팝업창에서 수정하면 됩니다.
6. 앱이 선택한 날짜 파일만 외장 SSD로 복사하고, JPG 기준 컬링 리포트까지 만듭니다.
7. 완료되면 생성된 촬영 폴더가 Finder에서 열립니다.

기본 저장 위치는 `/Volumes/980PRO/Photos`입니다. 실행 중에 다른 위치를 입력하면 그 위치로 가져옵니다.
장소 이름은 보통 사진 파일 안에 들어 있지 않습니다. GPS가 있는 사진도 좌표만 있는 경우가 많아서, 현재 버전에서는 사람이 장소명을 입력하는 방식이 가장 정확합니다.

현재 촬영 폴더 구조:

```text
Photos/
└── 2026/
    └── 2026-05-31_미지정_untitled/
        ├── 00_RAW/
        │   ├── RAW/
        │   └── JPG/
        ├── 01_CULL_REVIEW/
        │   ├── reject-candidates/
        │   └── keeper-candidates/
        ├── 02_SELECT/
        ├── 03_EXPORT/
        ├── 04_SNS/
        │   └── instagram-caption.md
        ├── 05_NOTES/
        │   ├── ingest-log.md
        │   └── cull-report.md
        └── shoot-note.md
```

`cull-report.md`에는 Select 후보와 Reject 후보가 나뉘며, 각 후보마다 선명도, 노출, 노이즈, 대비, 얼굴 잘림 가능성 같은 이유가 함께 기록됩니다.

## 전체 설계

## Hermes 원격 실행 연동

Mac mini에 메모리카드를 꽂아둔 상태에서 Telegram으로 photo agent를 부르기 위한 전용 Hermes 프로필을 준비했습니다.

- Hermes 프로필 이름: `photoagent`
- 프로필 지시문: `/Users/jinito/.hermes/profiles/photoagent/SOUL.md`
- 원격 실행 브릿지: `scripts/hermes_photo_bridge.py`
- 기본 동작: 가장 최근 촬영일의 사진만 가져오기 + JPG 컬링 + 짧은 결과 요약

수동 테스트:

```bash
scripts/hermes_photo_bridge.py status
scripts/hermes_photo_bridge.py ingest-latest
```

Telegram을 기존 채널과 분리하려면 photo agent 전용 봇 또는 전용 그룹/채널의 chat id를 `~/.hermes/profiles/photoagent/.env`에 넣어야 합니다. 기존 Studio Birthday 프로필의 `.env`는 복사하지 않습니다.

### 1. 사진 가져오기 도우미

- 메모리카드 또는 원본 폴더를 입력받습니다.
- 외장 SSD의 `Photos/YYYY/YYYY-MM-DD_장소_촬영명` 폴더를 만듭니다.
- `00_RAW/RAW`, `00_RAW/JPG`, `01_CULL_REVIEW`, `02_SELECT`, `03_EXPORT`, `04_SNS`, `05_NOTES` 구조를 생성합니다.
- 원본 파일은 `00_RAW/RAW` 또는 `00_RAW/JPG`로 복사합니다.
- 같은 파일이 이미 있으면 건너뜁니다.
- 이름만 같은 다른 파일은 `_dup1`, `_dup2` 형태로 저장해 덮어쓰지 않습니다.
- macOS 메모리카드에 생기는 `._파일명` 같은 보조 파일과 숨김 파일은 사진으로 취급하지 않습니다.
- 기본 실행은 dry-run입니다. 실제 복사는 `--execute`가 필요합니다.

### 2. 컬링 보조

- JPG/PNG/TIFF는 직접 분석합니다.
- RAW는 `rawpy`가 설치되어 있으면 간단한 프리뷰를 만들고, 없으면 건너뜁니다.
- CullSnap 스타일을 참고한 로컬 점수 체계로 선명도, 노출, 암부/하이라이트 클리핑, 대비, 노이즈를 계산합니다.
- dHash로 거의 같은 컷 그룹을 찾습니다.
- OpenCV Haar cascade로 얼굴이 너무 작거나 프레임 끝에 걸린 후보를 표시합니다.
- 원본은 삭제하지 않습니다.
- 후보 파일은 기본적으로 `01_CULL_REVIEW` 아래에 심볼릭 링크로 모읍니다.

### 3. 촬영 기록

`shoot-note.md`를 자동 생성합니다. 촬영 목적, 연습 주제, 보정 방향, 잘 된 점, 아쉬운 점, 다음 미션을 사람이 이어서 적을 수 있게 둡니다.

### 4. 인스타 업로드 준비

초기 버전은 실제 업로드를 하지 않습니다. `04_SNS/instagram-caption.md`에 촬영명, 장소, 이벤트 기반 캡션 초안과 해시태그를 생성합니다.

### 5. Lightroom Classic 연동 방향

MVP에서는 Lightroom을 직접 제어하지 않습니다. 안정적인 방식은 다음 순서입니다.

- `00_RAW` 폴더를 Lightroom Classic에서 수동 Import
- `01_CULL_REVIEW/reject-candidates`, `keeper-candidates`를 참고 폴더로 열어 비교
- 추후 XMP sidecar에 rating/label을 쓰는 옵션 검토
- Lightroom watched folder는 자동 가져오기에는 가능하지만 실수로 원치 않는 파일이 들어올 수 있어 후순위
- Adobe Lightroom Classic SDK/Lua 플러그인은 가능하지만 초기 설치 난이도와 유지보수 비용이 있어 후순위
- Adobe Lightroom Cloud API는 Classic 로컬 카탈로그 제어와 목적이 다르므로 MVP 핵심 경로는 아님

## 기술 스택 판단

MVP는 **Python**이 적합합니다.

- macOS 파일 작업과 외장 SSD 경로 처리가 단순합니다.
- Pillow/OpenCV/rawpy 등 사진 분석 라이브러리가 성숙합니다.
- CLI로 시작하고 나중에 FastAPI, Tauri, Electron, SwiftUI GUI로 감싸기 쉽습니다.
- Apple Silicon에서 `python -m venv`와 `pip`만으로 시작할 수 있습니다.

Node.js는 GUI/Electron 확장에는 좋지만, 이미지 품질 분석과 RAW 처리 생태계는 Python이 더 실용적입니다.

## MVP 범위

- `photo-agent ingest`
- `photo-agent cull`
- 안전한 중복 처리
- dry-run 기본값
- 촬영 폴더 구조 생성
- 사진 복사 로그 생성
- `shoot-note.md` 생성
- `instagram-caption.md` 생성
- `cull-report.md` 생성
- 원본 삭제 기능 없음

## 설치

Apple Silicon Mac mini 기준:

```bash
cd /Users/jinito/Workspaces/photo-ingest-agent
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

RAW 프리뷰 분석까지 시도하려면 선택 설치:

```bash
python -m pip install '.[raw]'
```

`rawpy` 설치가 실패하면 일단 생략해도 됩니다. JPG 분석과 RAW 건너뛰기 로그는 정상 동작합니다.

## 외부 테스트 Quick Start

GitHub에서 받은 테스터는 아래 순서로 바로 확인할 수 있습니다.

```bash
git clone https://github.com/digitaltulbo/photo-ingest-agent.git
cd photo-ingest-agent
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .

python tests/make_sample_images.py
photo-agent ingest \
  --source "tests/sample_source" \
  --dest "tests/output/Photos" \
  --title "테스트산책" \
  --location "로컬공원" \
  --date 2026-05-30 \
  --execute

photo-agent cull \
  --shoot-dir "tests/output/Photos/2026/2026-05-30_로컬공원_테스트산책" \
  --execute
```

결과는 `tests/output/Photos/2026/2026-05-30_로컬공원_테스트산책` 아래에서 확인합니다.

## 사용법

먼저 dry-run으로 복사 계획을 확인합니다.

```bash
photo-agent ingest \
  --source "/Volumes/CANON/DCIM" \
  --dest "/Volumes/PHOTO_SSD/Photos" \
  --title "가족산책" \
  --location "분당중앙공원" \
  --camera "Canon R8" \
  --lens "RF 24-50mm"
```

메모리카드에 예전 사진이 많이 남아 있으면 촬영일만 제한합니다. 현재 MVP는 EXIF 도구가 없는 환경에서도 안전하게 동작하도록 파일 수정일 기준으로 필터링합니다.

```bash
photo-agent ingest \
  --source "/Volumes/Untitled/DCIM" \
  --dest "/Volumes/PHOTO_SSD/Photos" \
  --title "untitled" \
  --location "미지정" \
  --date 2026-05-31 \
  --only-date 2026-05-31
```


문제가 없으면 실제 실행합니다.

```bash
photo-agent ingest \
  --source "/Volumes/CANON/DCIM" \
  --dest "/Volumes/PHOTO_SSD/Photos" \
  --title "가족산책" \
  --location "분당중앙공원" \
  --camera "Canon R8" \
  --lens "RF 24-50mm" \
  --execute \
  --open-finder
```

파일이 너무 많을 때 dry-run 미리보기는 기본 80개만 보여줍니다. 전체 목록을 보고 싶으면 `--plan-limit 0`을 붙입니다.

가져오기 후 컬링 리포트를 만듭니다.

```bash
photo-agent cull \
  --shoot-dir "/Volumes/PHOTO_SSD/Photos/2026/2026-05-30_분당중앙공원_가족산책" \
  --execute
```

가져오기와 컬링을 한 번에 실행할 수도 있습니다.

```bash
photo-agent ingest \
  --source "/Volumes/CANON/DCIM" \
  --dest "/Volumes/PHOTO_SSD/Photos" \
  --title "가족산책" \
  --location "분당중앙공원" \
  --camera "Canon R8" \
  --lens "RF 24-50mm" \
  --execute \
  --run-cull
```

## 테스트용 명령어

저장소에 테스트 이미지를 만든 뒤 dry-run과 실제 실행을 확인합니다.

```bash
python tests/make_sample_images.py

photo-agent ingest \
  --source "tests/sample_source" \
  --dest "tests/output/Photos" \
  --title "테스트산책" \
  --location "로컬공원"

photo-agent ingest \
  --source "tests/sample_source" \
  --dest "tests/output/Photos" \
  --title "테스트산책" \
  --location "로컬공원" \
  --execute

photo-agent cull \
  --shoot-dir "tests/output/Photos/2026/2026-05-30_로컬공원_테스트산책" \
  --execute
```

날짜가 다른 날이면 `--date 2026-05-30`을 붙여 고정할 수 있습니다.

## 구현 TODO

1. 안정적인 ingest CLI
2. 중복 파일 안전 처리
3. 촬영 노트와 인스타 캡션 템플릿
4. OpenCV/Pillow 기반 컬링 리포트
5. RAW 프리뷰 추출 옵션
6. Lightroom Classic 수동 Import 가이드
7. XMP sidecar rating/label 쓰기 실험
8. 로컬 GUI 또는 메뉴바 앱
9. LLM 캡션 생성 어댑터
10. CLIP/MediaPipe 기반 고급 장면/얼굴 분석

## AI 고도화 확장 구조

현재 코드는 API 키가 없어도 동작합니다. 추후에는 다음 인터페이스를 추가하면 됩니다.

- `CaptionProvider`: 로컬 템플릿, OpenAI, Claude 중 선택
- `ImageScorer`: OpenCV 기본 점수, CLIP 미학 점수, 얼굴/눈 감김 모델 중 선택
- `MetadataWriter`: report-only, XMP sidecar, Lightroom plugin bridge 중 선택
- `ReviewCollector`: symlink, copy, Finder tag, XMP label 중 선택

추천 순서:

1. 지금처럼 report-only 유지
2. Finder tag 또는 별도 후보 폴더 추가
3. XMP sidecar 실험
4. Lightroom Classic Lua 플러그인
5. 캡션 생성용 LLM 옵션

## 안전 원칙

- 원본 삭제 기능은 없습니다.
- 원본 RAW 파일을 수정하지 않습니다.
- 기본값은 dry-run입니다.
- 복사는 덮어쓰지 않습니다.
- 실패 후보는 삭제 후보가 아니라 확인 후보입니다.
