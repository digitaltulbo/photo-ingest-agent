#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


PROJECT_DIR = Path("/Users/jinito/Workspaces/photo-ingest-agent")
DEFAULT_DEST = Path("/Volumes/980PRO/Photos")
DEFAULT_LIGHTROOM_WATCHED_DIR = Path("/Volumes/980PRO/LightroomAutoImport/watched")
DEFAULT_LIGHTROOM_DEST_DIR = Path("/Volumes/980PRO/Photos/LightroomAutoImported")
DEFAULT_LIGHTROOM_COLLECTION = "Photo Agent Auto Import"
DEFAULT_SOURCE_CANDIDATES = [
    Path("/Volumes/Untitled/DCIM"),
    Path("/Volumes/UNTITLED/DCIM"),
]
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


@dataclass(frozen=True)
class LatestPhotoSet:
    source: Path
    shoot_date: str
    count: int


def is_photo(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in PHOTO_EXTENSIONS and not path.name.startswith("._")


def find_source(explicit_source: str | None) -> Path:
    if explicit_source:
        source = Path(explicit_source).expanduser()
        if source.exists():
            return source.resolve()
        raise SystemExit(f"원본 폴더를 찾지 못했습니다: {source}")

    for candidate in DEFAULT_SOURCE_CANDIDATES:
        if candidate.exists():
            return candidate.resolve()

    volume_sources = sorted(Path("/Volumes").glob("*/DCIM"))
    for candidate in volume_sources:
        if candidate.exists():
            return candidate.resolve()

    raise SystemExit("메모리카드의 DCIM 폴더를 찾지 못했습니다. Mac mini에 카드를 꽂은 뒤 다시 실행하세요.")


def latest_photo_set(source: Path) -> LatestPhotoSet:
    date_counts: dict[str, int] = {}
    for path in source.rglob("*"):
        if not is_photo(path):
            continue
        shoot_date = datetime.fromtimestamp(path.stat().st_mtime).date().isoformat()
        date_counts[shoot_date] = date_counts.get(shoot_date, 0) + 1

    if not date_counts:
        raise SystemExit(f"사진 파일을 찾지 못했습니다: {source}")

    shoot_date = max(date_counts)
    return LatestPhotoSet(source=source, shoot_date=shoot_date, count=date_counts[shoot_date])


def run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PATH"] = f"{PROJECT_DIR / '.venv' / 'bin'}:{env.get('PATH', '')}"
    return subprocess.run(
        command,
        cwd=str(PROJECT_DIR),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def setup_lightroom_dirs(args: argparse.Namespace) -> int:
    watched_dir = Path(args.watched_dir).expanduser().resolve()
    dest_dir = Path(args.lightroom_dest).expanduser().resolve()
    watched_dir.mkdir(parents=True, exist_ok=True)
    dest_dir.mkdir(parents=True, exist_ok=True)
    print("Lightroom Auto Import 폴더 준비 완료")
    print(f"- Watched Folder: {watched_dir}")
    print(f"- Move to: {dest_dir}")
    print("- Subfolder Name: JPG_From_Photo_Agent")
    print(f"- Collection: {args.collection}")
    print("- iPad 확인: Lightroom Classic에서 이 collection의 Sync를 켜세요.")
    return 0


def parse_shoot_folder(output: str) -> str:
    match = re.search(r"^Shoot folder: (.+)$", output, re.MULTILINE)
    return match.group(1).strip() if match else ""


def parse_count(label: str, output: str) -> int | None:
    match = re.search(rf"^{re.escape(label)}:\s*(\d+)", output, re.MULTILINE)
    return int(match.group(1)) if match else None


def count_files(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for item in path.iterdir() if item.is_file())


def shoot_file_count(path: Path) -> int:
    return count_files(path / "01_RAW") + count_files(path / "02_JPG")


def find_latest_shoot(dest: Path) -> Path | None:
    shoot_dirs = [
        path
        for path in dest.glob("*/*")
        if path.is_dir() and ((path / "04_NOTES").exists() or (path / "05_NOTES").exists())
    ]
    if not shoot_dirs:
        return None
    non_empty = [path for path in shoot_dirs if shoot_file_count(path) > 0]
    candidates = non_empty or shoot_dirs
    return sorted(candidates, key=lambda path: path.stat().st_mtime, reverse=True)[0]


def ingest_latest(args: argparse.Namespace) -> int:
    source = find_source(args.source)
    latest = latest_photo_set(source)
    dest = Path(args.dest).expanduser().resolve()
    title = args.title or f"remote-{latest.shoot_date}"
    location = args.location or "미지정"

    command = [
        "photo-agent",
        "ingest",
        "--source",
        str(source),
        "--dest",
        str(dest),
        "--title",
        title,
        "--location",
        location,
        "--date",
        latest.shoot_date,
        "--only-date",
        latest.shoot_date,
        "--execute",
        "--plan-limit",
        str(args.plan_limit),
    ]
    if args.stage_lightroom_jpg:
        command.extend(["--stage-lightroom-jpg", "--lightroom-watched-dir", str(Path(args.watched_dir).expanduser())])

    result = run_command(command)
    shoot_folder = parse_shoot_folder(result.stdout)
    staged = parse_count("Lightroom JPG staged", result.stdout)
    skipped = parse_count("Skipped duplicates", result.stdout)

    print("Photo Agent 원격 실행 결과")
    print(f"- 상태: {'완료' if result.returncode == 0 else '실패'}")
    print(f"- 원본: {source}")
    print(f"- 선택된 촬영일: {latest.shoot_date}")
    print(f"- 해당 날짜 사진 수: {latest.count}")
    if shoot_folder:
        shoot_path = Path(shoot_folder)
        print(f"- 촬영 폴더: {shoot_path}")
        print(f"- RAW: {count_files(shoot_path / '01_RAW')}")
        print(f"- JPG: {count_files(shoot_path / '02_JPG')}")
        print(f"- 촬영 노트: {shoot_path / 'shoot-note.md'}")
        print(f"- Lightroom 메모: {shoot_path / '04_NOTES' / 'lightroom-auto-import.md'}")
    if args.stage_lightroom_jpg:
        print(f"- Lightroom watched folder: {Path(args.watched_dir).expanduser()}")
    if staged is not None:
        print(f"- Lightroom JPG 전달: {staged}")
    if skipped is not None:
        print(f"- Lightroom 중복 건너뜀: {skipped}")

    if result.returncode != 0:
        print("")
        print("실행 로그")
        print(result.stdout.strip())
    return result.returncode


def status(args: argparse.Namespace) -> int:
    dest = Path(args.dest).expanduser().resolve()
    latest = find_latest_shoot(dest)
    if latest is None:
        print("아직 촬영 폴더를 찾지 못했습니다.")
        return 0

    print("Photo Agent 최근 작업")
    print(f"- 촬영 폴더: {latest}")
    print(f"- 촬영 노트: {latest / 'shoot-note.md'}")
    print(f"- Lightroom 메모: {latest / '04_NOTES' / 'lightroom-auto-import.md'}")
    print(f"- RAW: {count_files(latest / '01_RAW')}")
    print(f"- JPG: {count_files(latest / '02_JPG')}")
    return 0


def stage_lightroom_latest(args: argparse.Namespace) -> int:
    dest = Path(args.dest).expanduser().resolve()
    shoot_dir = find_latest_shoot(dest)
    if shoot_dir is None or not (shoot_dir / "02_JPG").exists():
        raise SystemExit("Lightroom에 전달할 촬영 폴더를 찾지 못했습니다.")
    watched_dir = Path(args.watched_dir).expanduser().resolve()
    command = [
        "photo-agent",
        "lightroom-stage",
        "--shoot-dir",
        str(shoot_dir),
        "--watched-dir",
        str(watched_dir),
        "--execute",
        "--plan-limit",
        str(args.plan_limit),
    ]
    result = run_command(command)
    staged = parse_count("Lightroom JPG staged", result.stdout)
    skipped = parse_count("Skipped duplicates", result.stdout)
    print("Lightroom Auto Import 전달 결과")
    print(f"- 상태: {'완료' if result.returncode == 0 else '실패'}")
    print(f"- 촬영 폴더: {shoot_dir}")
    print(f"- Watched Folder: {watched_dir}")
    if staged is not None:
        print(f"- JPG 전달: {staged}")
    if skipped is not None:
        print(f"- 중복 건너뜀: {skipped}")
    print(f"- 로그: {shoot_dir / '04_NOTES' / 'lightroom-auto-import-log.md'}")
    if result.returncode != 0:
        print("")
        print("실행 로그")
        print(result.stdout.strip())
    return result.returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Hermes bridge for photo-ingest-agent.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    setup = subparsers.add_parser("setup-lightroom", help="Create 980PRO folders for Lightroom Classic Auto Import.")
    setup.add_argument("--watched-dir", default=str(DEFAULT_LIGHTROOM_WATCHED_DIR), help="Lightroom Classic Auto Import watched folder.")
    setup.add_argument("--lightroom-dest", default=str(DEFAULT_LIGHTROOM_DEST_DIR), help="Lightroom Classic Auto Import destination folder.")
    setup.add_argument("--collection", default=DEFAULT_LIGHTROOM_COLLECTION, help="Recommended Lightroom collection name.")
    setup.set_defaults(func=setup_lightroom_dirs)

    latest = subparsers.add_parser("ingest-latest", help="Ingest the latest date found on the memory card and stage JPG for Lightroom.")
    latest.add_argument("--source", default="", help="Source folder. Defaults to the first memory-card DCIM folder.")
    latest.add_argument("--dest", default=str(DEFAULT_DEST), help="Photos destination root.")
    latest.add_argument("--title", default="", help="Shoot title. Defaults to remote-YYYY-MM-DD.")
    latest.add_argument("--location", default="", help="Shoot location. Defaults to 미지정.")
    latest.add_argument("--stage-lightroom-jpg", action=argparse.BooleanOptionalAction, default=True)
    latest.add_argument("--watched-dir", default=str(DEFAULT_LIGHTROOM_WATCHED_DIR), help="Lightroom Classic Auto Import watched folder.")
    latest.add_argument("--plan-limit", type=int, default=10)
    latest.set_defaults(func=ingest_latest)

    lr_stage = subparsers.add_parser("lightroom-stage-latest", help="Stage the latest shoot JPG files for Lightroom Auto Import.")
    lr_stage.add_argument("--dest", default=str(DEFAULT_DEST), help="Photos destination root.")
    lr_stage.add_argument("--watched-dir", default=str(DEFAULT_LIGHTROOM_WATCHED_DIR), help="Lightroom Classic Auto Import watched folder.")
    lr_stage.add_argument("--plan-limit", type=int, default=10)
    lr_stage.set_defaults(func=stage_lightroom_latest)

    status_parser = subparsers.add_parser("status", help="Print the latest photo-agent result.")
    status_parser.add_argument("--dest", default=str(DEFAULT_DEST), help="Photos destination root.")
    status_parser.set_defaults(func=status)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
