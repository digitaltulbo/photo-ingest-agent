from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path

from PIL import ExifTags, Image


PHOTO_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".tif",
    ".tiff",
    ".heic",
    ".cr2",
    ".cr3",
    ".nef",
    ".arw",
    ".raf",
    ".orf",
    ".rw2",
    ".dng",
}
JPG_EXTENSIONS = {".jpg", ".jpeg"}
RAW_EXTENSIONS = {".cr2", ".cr3", ".nef", ".arw", ".raf", ".orf", ".rw2", ".dng"}

SHOOT_DIRS = [
    "01_RAW",
    "02_JPG",
    "03_LIGHTROOM_AUTO_IMPORT",
    "04_NOTES",
    "05_SNS",
]

DEFAULT_LIGHTROOM_WATCHED_DIR = Path("/Volumes/980PRO/LightroomAutoImport/watched")


@dataclass(frozen=True)
class ShootInfo:
    shoot_date: date
    title: str
    location: str
    event: str
    camera: str
    lens: str
    purpose: str
    practice: str
    time_of_day: str
    light: str

    @property
    def display_name(self) -> str:
        parts = [self.location, self.event or self.title]
        clean_parts = [slugify(part) for part in parts if part.strip()]
        return f"{self.shoot_date.isoformat()}_{'_'.join(clean_parts)}"


@dataclass
class CopyPlanItem:
    source: Path
    destination: Path
    action: str
    reason: str = ""


def slugify(value: str) -> str:
    value = value.strip().replace(" ", "")
    value = re.sub(r"[/:\\?%*|\"<>]", "-", value)
    value = re.sub(r"-+", "-", value)
    return value or "untitled"


def is_supported_photo_file(path: Path) -> bool:
    if path.suffix.lower() not in PHOTO_EXTENSIONS:
        return False
    return not any(part.startswith(".") for part in path.parts)


def is_jpg_file(path: Path) -> bool:
    return path.suffix.lower() in JPG_EXTENSIONS and not path.name.startswith("._")


def matches_date_filter(path: Path, only_date: date | None) -> bool:
    if only_date is None:
        return True
    modified = datetime.fromtimestamp(path.stat().st_mtime)
    start = datetime.combine(only_date, time.min)
    end = datetime.combine(only_date, time.max)
    return start <= modified <= end


def find_photo_files(source: Path, only_date: date | None = None) -> list[Path]:
    return sorted(
        path
        for path in source.rglob("*")
        if path.is_file() and is_supported_photo_file(path) and matches_date_filter(path, only_date)
    )


def infer_camera_lens(source: Path, only_date: date | None = None) -> tuple[str, str]:
    for path in find_photo_files(source, only_date):
        if path.suffix.lower() in RAW_EXTENSIONS:
            continue
        try:
            with Image.open(path) as image:
                exif = image.getexif()
                if not exif:
                    continue
                camera = clean_exif_text(get_exif_value(exif, "Model"))
                lens = clean_exif_text(
                    get_exif_value(exif, "LensModel")
                    or get_exif_value(exif, "LensSpecification")
                    or get_exif_value(exif, "LensMake")
                )
                if camera or lens:
                    return camera, lens
        except Exception:
            continue
    return "", ""


def get_exif_value(exif: Image.Exif, name: str) -> object | None:
    for tag_id, value in exif.items():
        if ExifTags.TAGS.get(tag_id) == name:
            return value
    return None


def clean_exif_text(value: object | None) -> str:
    if value is None:
        return ""
    if isinstance(value, (tuple, list)):
        return " ".join(str(part) for part in value).strip()
    return str(value).replace("\x00", "").strip()


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def photo_bucket_dir(shoot_dir: Path, source: Path) -> Path:
    return shoot_dir / ("01_RAW" if source.suffix.lower() in RAW_EXTENSIONS else "02_JPG")


def resolve_destination(shoot_dir: Path, source: Path) -> CopyPlanItem:
    target = photo_bucket_dir(shoot_dir, source) / source.name
    if not target.exists():
        return CopyPlanItem(source, target, "copy")

    if target.stat().st_size == source.stat().st_size and sha256_file(target) == sha256_file(source):
        return CopyPlanItem(source, target, "skip", "same file already exists")

    stem = source.stem
    suffix = source.suffix
    for index in range(1, 10_000):
        candidate = target.parent / f"{stem}_dup{index}{suffix}"
        if not candidate.exists():
            return CopyPlanItem(source, candidate, "copy", f"name conflict: kept both files as {candidate.name}")
    raise RuntimeError(f"Too many duplicate names for {source.name}")


def build_copy_plan(source: Path, shoot_dir: Path, only_date: date | None = None) -> list[CopyPlanItem]:
    return [resolve_destination(shoot_dir, file_path) for file_path in find_photo_files(source, only_date)]


def ensure_structure(shoot_dir: Path, execute: bool) -> None:
    if not execute:
        return
    for relative in SHOOT_DIRS:
        (shoot_dir / relative).mkdir(parents=True, exist_ok=True)


def write_text(path: Path, content: str, execute: bool) -> None:
    if execute:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def copy_files(plan: list[CopyPlanItem], execute: bool) -> None:
    if not execute:
        return
    for item in plan:
        if item.action == "copy":
            item.destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item.source, item.destination)


def make_shoot_note(info: ShootInfo, raw_count: int, jpg_count: int) -> str:
    return f"""# 촬영 기록

## 기본 정보
- 날짜: {info.shoot_date.isoformat()}
- 촬영명: {info.title}
- 장소: {info.location}
- 이벤트: {info.event or info.title}
- 카메라: {info.camera}
- 렌즈: {info.lens}
- 시간대: {info.time_of_day}
- 빛 상황: {info.light}
- RAW 파일 수: {raw_count}
- JPG 파일 수: {jpg_count}

## 오늘의 촬영 목적
- {info.purpose}

## 오늘의 연습 주제
- {info.practice}

## 촬영 전/현장 메모
- 날씨:
- 이동 동선:
- 가장 좋았던 빛:
- 가장 어려웠던 장면:
- 다시 찍고 싶은 장면:

## 파일 정리 메모
- RAW 보관 위치: `01_RAW`
- JPG 보관 위치: `02_JPG`
- Lightroom Auto Import 준비 폴더: `03_LIGHTROOM_AUTO_IMPORT`
- 원본 삭제/이동 여부: 삭제 없음, 메모리카드 원본 이동 없음

## Lightroom 셀렉 메모
- 1차 셀렉 기준:
- 별점 기준:
- 플래그 기준:
- iPad에서 확인할 컷:
- Mac에서 RAW로 다시 볼 컷:

## Lightroom 보정 방향
- 전체 톤:
- 화이트밸런스:
- 노출:
- 대비:
- 색감:
- 크롭/구도:

## 잘 된 점
-

## 아쉬운 점
-

## 다음 촬영 미션
1.
2.
3.

## 인스타 업로드 메모
- 캡션 아이디어:
- 해시태그:
- 업로드 후보 컷:
"""


def make_caption(info: ShootInfo) -> str:
    place = info.location
    event = info.event or info.title
    tags = [
        "#사진기록",
        "#사진독학",
        "#일상사진",
        "#스냅사진",
        "#라이트룸",
        "#LightroomClassic",
        "#사진연습",
        "#오늘의사진",
        "#감성사진",
        "#풍경스냅",
        "#가족사진",
        "#산책사진",
        f"#{slugify(place)}",
        f"#{slugify(event)}",
        "#캐논",
        "#미러리스",
        "#photostudy",
        "#dailyphoto",
        "#snapshot",
        "#koreaphoto",
    ]
    return f"""# Instagram 업로드 준비

## 캡션 초안 1: 감성형
{place}에서 보낸 {event}의 조용한 순간들. 오늘의 빛과 표정을 오래 기억하고 싶어서 몇 장 남겨두었다.

## 캡션 초안 2: 사진 공부 기록형
오늘은 {place}에서 {event}을 촬영했다. 구도와 빛을 더 천천히 보고, Lightroom에서는 색을 과하게 밀지 않는 방향으로 정리해볼 예정.

## 캡션 초안 3: 짧고 담백한 업로드형
{place}, {event}. 오늘의 기록.

## 해시태그
{" ".join(tags)}

## 스토리 문구
1. 오늘의 빛 기록
2. 산책하며 찍은 몇 장
3. Lightroom 정리 전 원본 셀렉 중

## 릴스 제목 아이디어
1. {place}에서 찍은 오늘의 스냅
2. {event} 사진 정리 과정
3. Lightroom 전후 기록
4. 오늘의 사진 연습 노트
5. 오늘 찍은 사진 돌아보기

## 다음 업로드 때 개선할 점
- 촬영 후 바로 좋았던 빛, 구도, 아쉬운 컷을 `shoot-note.md`에 3줄 이상 기록하기.
"""


def make_ingest_log(
    info: ShootInfo,
    source: Path,
    shoot_dir: Path,
    plan: list[CopyPlanItem],
    execute: bool,
    only_date: date | None,
) -> str:
    copied = sum(1 for item in plan if item.action == "copy")
    skipped = sum(1 for item in plan if item.action == "skip")
    raw_count = sum(1 for item in plan if item.destination.parent.name == "01_RAW" and item.action == "copy")
    jpg_count = sum(1 for item in plan if item.destination.parent.name == "02_JPG" and item.action == "copy")
    lines = [
        "# Ingest Log",
        "",
        f"- 실행 시각: {datetime.now().isoformat(timespec='seconds')}",
        f"- 모드: {'execute' if execute else 'dry-run'}",
        f"- 원본 경로: `{source}`",
        f"- 촬영 폴더: `{shoot_dir}`",
        f"- 날짜 필터: `{only_date.isoformat() if only_date else '없음'}`",
        f"- 복사 예정/완료: {copied}",
        f"- RAW 복사 예정/완료: {raw_count}",
        f"- JPG 복사 예정/완료: {jpg_count}",
        f"- 중복으로 건너뜀: {skipped}",
        "",
        "## 파일별 처리",
    ]
    for item in plan:
        note = f" ({item.reason})" if item.reason else ""
        lines.append(f"- {item.action}: `{item.source}` -> `{item.destination}`{note}")
    return "\n".join(lines) + "\n"


def make_lightroom_note(watched_dir: Path) -> str:
    return f"""# Lightroom Auto Import 메모

## Lightroom Classic 설정
1. Lightroom Classic을 엽니다.
2. `File > Auto Import > Auto Import Settings...`로 이동합니다.
3. Watched Folder를 아래 경로로 지정합니다.

`{watched_dir}`

4. Auto Import를 켭니다.

## 현재 MVP 원칙
- Lightroom에는 JPG만 자동으로 넘깁니다.
- RAW 원본은 `01_RAW`에 보관하고, 나중에 사람이 필요할 때 Lightroom에서 직접 확인합니다.
- Watched Folder는 임시 입구입니다. 실제 원본 보관소가 아닙니다.
- Lightroom이 가져간 뒤 watched 폴더가 비워지는 것은 정상 동작입니다.
"""


def make_stage_log(shoot_dir: Path, watched_dir: Path, plan: list[CopyPlanItem], execute: bool) -> str:
    staged = sum(1 for item in plan if item.action == "copy")
    skipped = sum(1 for item in plan if item.action == "skip")
    lines = [
        "# Lightroom Auto Import Stage Log",
        "",
        f"- 실행 시각: {datetime.now().isoformat(timespec='seconds')}",
        f"- 모드: {'execute' if execute else 'dry-run'}",
        f"- 촬영 폴더: `{shoot_dir}`",
        f"- Watched Folder: `{watched_dir}`",
        f"- JPG 전달 예정/완료: {staged}",
        f"- 중복으로 건너뜀: {skipped}",
        "",
        "## 파일별 처리",
    ]
    for item in plan:
        note = f" ({item.reason})" if item.reason else ""
        lines.append(f"- {item.action}: `{item.source}` -> `{item.destination}`{note}")
    return "\n".join(lines) + "\n"


def open_in_finder(path: Path) -> None:
    subprocess.run(["open", str(path)], check=False)


def count_plan_bucket(plan: list[CopyPlanItem], bucket: str) -> int:
    return sum(1 for item in plan if item.destination.parent.name == bucket and item.action == "copy")


def print_plan(shoot_dir: Path, plan: list[CopyPlanItem], execute: bool, plan_limit: int) -> None:
    copy_count = sum(1 for item in plan if item.action == "copy")
    skip_count = sum(1 for item in plan if item.action == "skip")
    print(f"Mode: {'EXECUTE' if execute else 'DRY-RUN'}")
    print(f"Shoot folder: {shoot_dir}")
    print(f"Plan summary: {len(plan)} supported photo files, {copy_count} to copy, {skip_count} to skip")
    print("Folders:")
    for relative in SHOOT_DIRS:
        print(f"  - {shoot_dir / relative}")
    print("Files:")
    if not plan:
        print("  - No supported photo files found.")
    visible_plan = plan if plan_limit <= 0 else plan[:plan_limit]
    for item in visible_plan:
        note = f" ({item.reason})" if item.reason else ""
        print(f"  - {item.action}: {item.source} -> {item.destination}{note}")
    omitted = len(plan) - len(visible_plan)
    if omitted > 0:
        print(f"  ... {omitted} more files omitted from preview. Use --plan-limit 0 to show all.")
    if not execute:
        print("\nNo files were copied. Re-run with --execute to apply this plan.")


def run_ingest(args: argparse.Namespace) -> int:
    source = Path(args.source).expanduser().resolve()
    dest_root = Path(args.dest).expanduser().resolve()
    if not source.exists():
        raise SystemExit(f"Source does not exist: {source}")

    shoot_date = date.fromisoformat(args.date) if args.date else date.today()
    only_date = date.fromisoformat(args.only_date) if args.only_date else None
    inferred_camera, inferred_lens = infer_camera_lens(source, only_date)
    camera = args.camera or inferred_camera or "수동 입력 예정"
    lens = args.lens or inferred_lens or "수동 입력 예정"
    info = ShootInfo(
        shoot_date=shoot_date,
        title=args.title,
        location=args.location,
        event=args.event or args.title,
        camera=camera,
        lens=lens,
        purpose=args.purpose,
        practice=args.practice,
        time_of_day=args.time_of_day,
        light=args.light,
    )
    shoot_dir = dest_root / str(shoot_date.year) / info.display_name
    execute = args.execute

    ensure_structure(shoot_dir, execute)
    plan = build_copy_plan(source, shoot_dir, only_date)
    raw_count = count_plan_bucket(plan, "01_RAW")
    jpg_count = count_plan_bucket(plan, "02_JPG")

    print_plan(shoot_dir, plan, execute, args.plan_limit)
    write_text(shoot_dir / "shoot-note.md", make_shoot_note(info, raw_count, jpg_count), execute)
    write_text(shoot_dir / "05_SNS/instagram-caption.md", make_caption(info), execute)
    write_text(shoot_dir / "04_NOTES/ingest-log.md", make_ingest_log(info, source, shoot_dir, plan, execute, only_date), execute)
    write_text(
        shoot_dir / "04_NOTES/lightroom-auto-import.md",
        make_lightroom_note(Path(args.lightroom_watched_dir).expanduser()),
        execute,
    )
    copy_files(plan, execute)

    if execute and args.stage_lightroom_jpg:
        stage_args = argparse.Namespace(
            shoot_dir=str(shoot_dir),
            watched_dir=args.lightroom_watched_dir,
            execute=True,
            plan_limit=args.plan_limit,
        )
        run_lightroom_stage(stage_args)

    if execute and args.open_finder:
        open_in_finder(shoot_dir)

    return 0


def run_lightroom_stage(args: argparse.Namespace) -> int:
    shoot_dir = Path(args.shoot_dir).expanduser().resolve()
    watched_dir = Path(args.watched_dir).expanduser().resolve()
    jpg_dir = shoot_dir / "02_JPG"
    if not shoot_dir.exists():
        raise SystemExit(f"Shoot folder does not exist: {shoot_dir}")
    if not jpg_dir.exists():
        raise SystemExit(f"JPG folder does not exist: {jpg_dir}")

    watched_dir.mkdir(parents=True, exist_ok=True) if args.execute else None
    stage_record_dir = shoot_dir / "03_LIGHTROOM_AUTO_IMPORT"
    stage_record_dir.mkdir(parents=True, exist_ok=True) if args.execute else None
    plan = [resolve_stage_destination(watched_dir, path) for path in sorted(jpg_dir.iterdir()) if is_jpg_file(path)]

    print(f"Mode: {'EXECUTE' if args.execute else 'DRY-RUN'}")
    print(f"Shoot folder: {shoot_dir}")
    print(f"Lightroom watched folder: {watched_dir}")
    print(f"Plan summary: {len(plan)} JPG files")
    visible_plan = plan if args.plan_limit <= 0 else plan[: args.plan_limit]
    for item in visible_plan:
        note = f" ({item.reason})" if item.reason else ""
        print(f"  - {item.action}: {item.source} -> {item.destination}{note}")
    omitted = len(plan) - len(visible_plan)
    if omitted > 0:
        print(f"  ... {omitted} more files omitted from preview. Use --plan-limit 0 to show all.")

    copy_files(plan, args.execute)
    write_text(stage_record_dir / "last-lightroom-stage-log.md", make_stage_log(shoot_dir, watched_dir, plan, args.execute), args.execute)
    write_text(shoot_dir / "04_NOTES/lightroom-auto-import-log.md", make_stage_log(shoot_dir, watched_dir, plan, args.execute), args.execute)

    staged = sum(1 for item in plan if item.action == "copy")
    skipped = sum(1 for item in plan if item.action == "skip")
    print(f"Lightroom JPG staged: {staged}")
    print(f"Skipped duplicates: {skipped}")
    print(f"Stage log: {shoot_dir / '04_NOTES/lightroom-auto-import-log.md'}")
    return 0


def resolve_stage_destination(watched_dir: Path, source: Path) -> CopyPlanItem:
    target = watched_dir / source.name
    if not target.exists():
        return CopyPlanItem(source, target, "copy")
    if target.stat().st_size == source.stat().st_size and sha256_file(target) == sha256_file(source):
        return CopyPlanItem(source, target, "skip", "same file already exists in Lightroom watched folder")
    for index in range(1, 10_000):
        candidate = watched_dir / f"{source.stem}_dup{index}{source.suffix}"
        if not candidate.exists():
            return CopyPlanItem(source, candidate, "copy", f"name conflict: kept both files as {candidate.name}")
    raise RuntimeError(f"Too many duplicate names for {source.name}")


def run_inspect(args: argparse.Namespace) -> int:
    source = Path(args.source).expanduser().resolve()
    only_date = date.fromisoformat(args.only_date) if args.only_date else None
    camera, lens = infer_camera_lens(source, only_date)
    print(f"camera={camera}")
    print(f"lens={lens}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="photo-agent",
        description="Local photo ingest and Lightroom Auto Import staging assistant.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest = subparsers.add_parser("ingest", help="Create shoot folder, copy photos safely, and generate notes.")
    ingest.add_argument("--source", required=True, help="Memory card or source folder path.")
    ingest.add_argument("--dest", required=True, help="Destination Photos root, e.g. /Volumes/PHOTO_SSD/Photos.")
    ingest.add_argument("--title", required=True, help="Shoot title, e.g. 가족산책.")
    ingest.add_argument("--location", required=True, help="Location, e.g. 분당중앙공원.")
    ingest.add_argument("--event", default="", help="Optional event name. Defaults to title.")
    ingest.add_argument("--date", default="", help="Shoot date YYYY-MM-DD. Defaults to today.")
    ingest.add_argument("--only-date", default="", help="Only ingest files whose file modified date is YYYY-MM-DD.")
    ingest.add_argument("--camera", default="", help="Camera name.")
    ingest.add_argument("--lens", default="", help="Lens name.")
    ingest.add_argument("--purpose", default="개인 사진 기록과 사진 연습", help="Shoot purpose.")
    ingest.add_argument("--practice", default="구도, 빛, 순간 포착 관찰", help="Practice theme.")
    ingest.add_argument("--time-of-day", default="수동 입력 예정", help="Time of day note.")
    ingest.add_argument("--light", default="수동 입력 예정", help="Light condition note.")
    ingest.add_argument("--execute", action="store_true", help="Actually create folders and copy files. Default is dry-run.")
    ingest.add_argument("--open-finder", action="store_true", help="Open created shoot folder in Finder after execute.")
    ingest.add_argument("--stage-lightroom-jpg", action="store_true", help="Copy JPG files to the Lightroom Auto Import watched folder after ingest.")
    ingest.add_argument("--lightroom-watched-dir", default=str(DEFAULT_LIGHTROOM_WATCHED_DIR), help="Lightroom Classic Auto Import watched folder.")
    ingest.add_argument("--plan-limit", type=int, default=80, help="Maximum file plan lines to print. Use 0 to show all.")
    ingest.set_defaults(func=run_ingest)

    stage = subparsers.add_parser("lightroom-stage", help="Copy shoot JPG files to Lightroom Classic Auto Import watched folder.")
    stage.add_argument("--shoot-dir", required=True, help="Shoot folder containing 02_JPG.")
    stage.add_argument("--watched-dir", default=str(DEFAULT_LIGHTROOM_WATCHED_DIR), help="Lightroom Classic Auto Import watched folder.")
    stage.add_argument("--execute", action="store_true", help="Actually copy JPG files. Default is dry-run.")
    stage.add_argument("--plan-limit", type=int, default=80, help="Maximum file plan lines to print. Use 0 to show all.")
    stage.set_defaults(func=run_lightroom_stage)

    inspect = subparsers.add_parser("inspect", help="Inspect source photos and print simple metadata defaults.")
    inspect.add_argument("--source", required=True, help="Memory card or source folder path.")
    inspect.add_argument("--only-date", default="", help="Only inspect files whose modified date is YYYY-MM-DD.")
    inspect.set_defaults(func=run_inspect)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    raise SystemExit(args.func(args))
