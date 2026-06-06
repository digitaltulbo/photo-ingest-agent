# photo-ingest-agent

Mac mini + 외장 SSD + Lightroom Classic + Hermes Telegram Agent를 위한 로컬 사진 가져오기 도우미입니다.

현재 MVP의 목표는 단순합니다.

- 메모리카드에서 최신 촬영일 사진만 가져오기
- 외장 SSD에 RAW/JPG를 분리 저장하기
- 촬영 노트를 자세히 만들기
- JPG만 Lightroom Classic Auto Import watched folder로 전달하기
- Hermes agent가 Telegram에서 이 작업을 실행하게 하기

컬링 기능은 잠시 중지했습니다. 기준이 납득되는 더 나은 선별 엔진이 생기기 전까지는 자동 select/reject를 하지 않습니다.

## Hermes 기준 MVP

Telegram에서 photoagent에게 이렇게 말합니다.

```text
최신 사진 가져와줘
```

그러면 Hermes가 아래 로컬 액션을 실행합니다.

```bash
/Users/jinito/Workspaces/photo-ingest-agent/scripts/hermes_photo_bridge.py ingest-latest
```

실행 결과:

```text
/Volumes/980PRO/Photos/2026/2026-06-03_미지정_remote-2026-06-03/
├── 01_RAW/
├── 02_JPG/
├── 03_LIGHTROOM_AUTO_IMPORT/
├── 04_NOTES/
│   ├── ingest-log.md
│   ├── lightroom-auto-import.md
│   └── lightroom-auto-import-log.md
├── 05_SNS/
│   └── instagram-caption.md
└── shoot-note.md
```

그리고 JPG 파일은 Lightroom Classic Auto Import용 watched folder로 복사됩니다.

```text
/Volumes/980PRO/LightroomAutoImport/watched
```

Lightroom Classic에서 Auto Import가 켜져 있으면, 이 watched folder에 들어온 JPG를 자동으로 가져갑니다.

## Lightroom Classic Auto Import 설정

Lightroom Classic에서 한 번만 설정합니다.

1. Lightroom Classic 실행
2. `File > Auto Import > Auto Import Settings...`
3. Watched Folder:

```text
/Volumes/980PRO/LightroomAutoImport/watched
```

4. Move to:

```text
/Volumes/980PRO/Photos/LightroomAutoImported
```

5. Subfolder Name:

```text
JPG_From_Photo_Agent
```

6. Add to Collection을 켜고 collection을 만듭니다.

```text
Photo Agent Auto Import
```

7. Initial Previews는 `Minimal`로 둡니다.
8. `Enable Auto Import`를 켭니다.
9. Lightroom Classic 왼쪽 Collections 패널에서 `Photo Agent Auto Import` collection의 sync를 켭니다.

이 MVP에서는 Lightroom에 JPG만 자동 전달합니다. RAW는 `01_RAW`에 안전하게 보관하고, 사람이 필요할 때 Mac에서 직접 가져와 확인합니다.

중요: watched folder는 임시 입구입니다. Lightroom이 가져간 뒤 watched folder에서 파일이 사라지는 것은 정상입니다. Lightroom이 가져간 JPG는 980PRO의 `Photos/LightroomAutoImported/JPG_From_Photo_Agent` 아래에 저장됩니다.

## Hermes 명령

```text
최신 사진 가져와줘
```

- 메모리카드에서 가장 최근 촬영일을 찾습니다.
- 해당 날짜 사진만 외장 SSD로 복사합니다.
- RAW는 `01_RAW`, JPG는 `02_JPG`에 저장합니다.
- 촬영 노트와 로그를 만듭니다.
- JPG를 Lightroom Auto Import watched folder로 전달합니다.

```text
라이트룸에 JPG 올려줘
```

- 이미 가져온 최신 촬영 폴더의 `02_JPG` 파일을 Lightroom watched folder로 다시 전달합니다.

```text
라이트룸 설정 준비해줘
```

- 980PRO에 Lightroom Auto Import용 폴더를 만듭니다.
- Lightroom Classic 화면에서 넣어야 할 Watched Folder, Move to, Collection 이름을 알려줍니다.

```text
상태 알려줘
```

- 최근 촬영 폴더, RAW/JPG 개수, 촬영 노트 위치를 알려줍니다.

## 바탕화면 실행

개발 명령어를 몰라도 되도록 바탕화면 실행 파일도 사용할 수 있습니다.

1. 메모리카드를 Mac mini에 꽂습니다.
2. 바탕화면의 `Photo Ingest Today.command`를 더블클릭합니다.
3. 달력에서 촬영 날짜를 선택합니다.
4. 저장 위치, 촬영명, 장소를 입력합니다.
5. RAW/JPG 정리와 노트 생성 후 JPG를 Lightroom watched folder로 전달합니다.

## CLI 사용

설치:

```bash
cd /Users/jinito/Workspaces/photo-ingest-agent
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

가져오기:

```bash
photo-agent ingest \
  --source "/Volumes/Untitled/DCIM" \
  --dest "/Volumes/980PRO/Photos" \
  --title "가족산책" \
  --location "분당중앙공원" \
  --date 2026-06-03 \
  --only-date 2026-06-03 \
  --execute \
  --stage-lightroom-jpg
```

이미 가져온 최신 촬영 폴더를 Lightroom watched folder로 전달:

```bash
photo-agent lightroom-stage \
  --shoot-dir "/Volumes/980PRO/Photos/2026/2026-06-03_분당중앙공원_가족산책" \
  --watched-dir "/Volumes/980PRO/LightroomAutoImport/watched" \
  --execute
```

## 설계 원칙

- 원본 삭제 없음
- 메모리카드 원본 이동 없음
- RAW와 JPG 분리
- Lightroom에는 JPG만 자동 전달
- Auto Import watched folder는 임시 입구로만 사용
- Lightroom에 넘기는 JPG 파일명에는 촬영 폴더명을 prefix로 붙여 `IMG_0001.JPG` 중복 충돌을 줄임
- 촬영 노트는 사람이 나중에 더 적기 좋은 구조로 생성
- Hermes는 자연어 명령을 실제 로컬 액션으로 연결

## 다음 확장

- Lightroom watched folder 설정 상태 점검
- Lightroom으로 전달된 JPG 목록 추적
- iPad 셀렉 후 RAW와 연결하는 수동/반자동 워크플로우
- 더 나은 컬링 엔진이 정해지면 별도 모듈로 재도입
