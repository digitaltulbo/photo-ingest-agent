#!/bin/zsh
set -e

PROJECT_DIR="/Users/jinito/Workspaces/photo-ingest-agent"
DEFAULT_DEST="/Volumes/980PRO/Photos"
TODAY="$(date +%F)"

ask_text() {
  local prompt="$1"
  local default_value="$2"
  osascript - "$prompt" "$default_value" <<'APPLESCRIPT'
on run argv
  set promptText to item 1 of argv
  set defaultValue to item 2 of argv
  set answer to text returned of (display dialog promptText default answer defaultValue buttons {"취소", "확인"} default button "확인" with title "Photo Ingest Agent")
  return answer
end run
APPLESCRIPT
}

show_message() {
  local message="$1"
  osascript - "$message" <<'APPLESCRIPT'
on run argv
  display dialog (item 1 of argv) buttons {"확인"} default button "확인" with title "Photo Ingest Agent"
end run
APPLESCRIPT
}

SOURCE=""
if [ -d "/Volumes/Untitled/DCIM" ]; then
  SOURCE="/Volumes/Untitled/DCIM"
else
  SOURCE="$(find /Volumes -maxdepth 2 -type d -name DCIM 2>/dev/null | head -1)"
fi

if [ -z "$SOURCE" ]; then
  show_message "메모리카드의 DCIM 폴더를 찾지 못했습니다. 카드를 꽂은 뒤 다시 실행하세요."
  exit 1
fi

cd "$PROJECT_DIR"
source "$PROJECT_DIR/.venv/bin/activate"

SHOOT_DATE="$(swift "$PROJECT_DIR/scripts/date_picker.swift" "$TODAY")"
if [ -z "$SHOOT_DATE" ]; then
  show_message "촬영 날짜가 선택되지 않았습니다."
  exit 1
fi

METADATA="$(photo-agent inspect --source "$SOURCE" --only-date "$SHOOT_DATE" || true)"
INFERRED_CAMERA="$(printf "%s\n" "$METADATA" | sed -n 's/^camera=//p' | head -1)"
INFERRED_LENS="$(printf "%s\n" "$METADATA" | sed -n 's/^lens=//p' | head -1)"

DEST="$(ask_text "저장 위치를 입력하세요." "$DEFAULT_DEST")"
TITLE="$(ask_text "촬영명을 입력하세요. 이 이름이 폴더명에 들어갑니다." "untitled")"
LOCATION="$(ask_text "장소 또는 이벤트 장소를 입력하세요. 이 이름도 폴더명에 들어갑니다." "미지정")"
CAMERA="$(ask_text "카메라 정보입니다. 사진에서 읽은 값이 있으면 자동으로 들어갑니다." "${INFERRED_CAMERA:-수동 입력 예정}")"
LENS="$(ask_text "렌즈 정보입니다. 사진에서 읽은 값이 있으면 자동으로 들어갑니다." "${INFERRED_LENS:-수동 입력 예정}")"

if [ -z "$DEST" ]; then DEST="$DEFAULT_DEST"; fi
if [ -z "$TITLE" ]; then TITLE="untitled"; fi
if [ -z "$LOCATION" ]; then LOCATION="미지정"; fi
if [ -z "$CAMERA" ]; then CAMERA="수동 입력 예정"; fi
if [ -z "$LENS" ]; then LENS="수동 입력 예정"; fi

show_message "선택한 날짜($SHOOT_DATE)의 사진만 실제로 가져오고 JPG를 Lightroom Auto Import 폴더로 전달합니다.\n\n원본: $SOURCE\n저장 위치: $DEST\n촬영명: $TITLE\n장소: $LOCATION\n카메라: $CAMERA\n렌즈: $LENS"
LIGHTROOM_WATCHED="/Volumes/980PRO/LightroomAutoImport/watched"

photo-agent ingest \
  --source "$SOURCE" \
  --dest "$DEST" \
  --title "$TITLE" \
  --location "$LOCATION" \
  --camera "$CAMERA" \
  --lens "$LENS" \
  --date "$SHOOT_DATE" \
  --only-date "$SHOOT_DATE" \
  --execute \
  --stage-lightroom-jpg \
  --lightroom-watched-dir "$LIGHTROOM_WATCHED" \
  --open-finder \
  --plan-limit 20

show_message "완료했습니다.\n\nRAW/JPG 정리와 촬영 노트를 만들고, JPG를 Lightroom Auto Import 폴더로 전달했습니다.\n\nLightroom watched folder:\n$LIGHTROOM_WATCHED"
