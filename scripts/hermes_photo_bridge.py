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


def parse_shoot_folder(output: str) -> str:
    match = re.search(r"^Shoot folder: (.+)$", output, re.MULTILINE)
    return match.group(1).strip() if match else ""


def parse_count(label: str, output: str) -> int | None:
    match = re.search(rf"^{re.escape(label)}:\s*(\d+)", output, re.MULTILINE)
    return int(match.group(1)) if match else None


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
        "--run-cull",
        "--plan-limit",
        str(args.plan_limit),
    ]
    if args.review_mode:
        command.extend(["--review-mode", args.review_mode])

    result = run_command(command)
    shoot_folder = parse_shoot_folder(result.stdout)
    rejects = parse_count("Reject candidates", result.stdout)
    keepers = parse_count("Keeper candidates", result.stdout)
    duplicates = parse_count("Duplicate groups", result.stdout)

    print("Photo Agent 원격 실행 결과")
    print(f"- 상태: {'완료' if result.returncode == 0 else '실패'}")
    print(f"- 원본: {source}")
    print(f"- 선택된 촬영일: {latest.shoot_date}")
    print(f"- 해당 날짜 사진 수: {latest.count}")
    if shoot_folder:
        print(f"- 촬영 폴더: {shoot_folder}")
        print(f"- 컬링 리포트: {Path(shoot_folder) / '05_NOTES' / 'cull-report.md'}")
    if rejects is not None:
        print(f"- Reject 후보: {rejects}")
    if keepers is not None:
        print(f"- Select 후보: {keepers}")
    if duplicates is not None:
        print(f"- 유사/연사 그룹: {duplicates}")

    if result.returncode != 0:
        print("")
        print("실행 로그")
        print(result.stdout.strip())
    return result.returncode


def status(args: argparse.Namespace) -> int:
    dest = Path(args.dest).expanduser().resolve()
    shoot_dirs = sorted(
        (path for path in dest.glob("*/*") if path.is_dir() and (path / "05_NOTES").exists()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not shoot_dirs:
        print("아직 촬영 폴더를 찾지 못했습니다.")
        return 0

    latest = shoot_dirs[0]
    report = latest / "05_NOTES" / "cull-report.md"
    print("Photo Agent 최근 작업")
    print(f"- 촬영 폴더: {latest}")
    print(f"- 컬링 리포트: {report if report.exists() else '아직 없음'}")
    print(f"- RAW: {len(list((latest / '00_RAW' / 'RAW').glob('*'))) if (latest / '00_RAW' / 'RAW').exists() else 0}")
    print(f"- JPG: {len(list((latest / '00_RAW' / 'JPG').glob('*'))) if (latest / '00_RAW' / 'JPG').exists() else 0}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Hermes bridge for photo-ingest-agent.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    latest = subparsers.add_parser("ingest-latest", help="Ingest and cull the latest date found on the memory card.")
    latest.add_argument("--source", default="", help="Source folder. Defaults to the first memory-card DCIM folder.")
    latest.add_argument("--dest", default=str(DEFAULT_DEST), help="Photos destination root.")
    latest.add_argument("--title", default="", help="Shoot title. Defaults to remote-YYYY-MM-DD.")
    latest.add_argument("--location", default="", help="Shoot location. Defaults to 미지정.")
    latest.add_argument("--review-mode", choices=["symlink", "copy", "none"], default="symlink")
    latest.add_argument("--plan-limit", type=int, default=10)
    latest.set_defaults(func=ingest_latest)

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
