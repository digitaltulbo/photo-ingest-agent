from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from statistics import mean
from typing import Iterable

from PIL import ExifTags, Image, ImageFilter, ImageStat

try:
    import cv2  # type: ignore
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover - optional import fallback
    cv2 = None
    np = None

try:
    import rawpy  # type: ignore
except Exception:  # pragma: no cover - optional import fallback
    rawpy = None


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
RAW_EXTENSIONS = {".cr2", ".cr3", ".nef", ".arw", ".raf", ".orf", ".rw2", ".dng"}

SHOOT_DIRS = [
    "00_RAW",
    "00_RAW/RAW",
    "00_RAW/JPG",
    "01_CULL_REVIEW/reject-candidates",
    "01_CULL_REVIEW/keeper-candidates",
    "02_SELECT",
    "03_EXPORT",
    "04_SNS",
    "05_NOTES",
]


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


@dataclass
class ImageAnalysis:
    path: Path
    ok: bool
    reason: str
    blur_score: float | None = None
    brightness: float | None = None
    shadow_clip_pct: float | None = None
    highlight_clip_pct: float | None = None
    contrast_score: float | None = None
    noise_score: float | None = None
    quality_score: float | None = None
    dhash: int | None = None
    width: int | None = None
    height: int | None = None
    faces: int | None = None
    face_notes: list[str] | None = None


def slugify(value: str) -> str:
    value = value.strip().replace(" ", "")
    value = re.sub(r"[/:\\?%*|\"<>]", "-", value)
    value = re.sub(r"-+", "-", value)
    return value or "untitled"


def find_photo_files(source: Path, only_date: date | None = None) -> list[Path]:
    return sorted(
        path
        for path in source.rglob("*")
        if path.is_file() and is_supported_photo_file(path) and matches_date_filter(path, only_date)
    )


def is_supported_photo_file(path: Path) -> bool:
    if path.suffix.lower() not in PHOTO_EXTENSIONS:
        return False
    return not any(part.startswith(".") for part in path.parts)


def matches_date_filter(path: Path, only_date: date | None) -> bool:
    if only_date is None:
        return True
    modified = datetime.fromtimestamp(path.stat().st_mtime)
    start = datetime.combine(only_date, time.min)
    end = datetime.combine(only_date, time.max)
    return start <= modified <= end


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


def photo_bucket(path: Path) -> str:
    return "RAW" if path.suffix.lower() in RAW_EXTENSIONS else "JPG"


def resolve_destination(raw_dir: Path, source: Path) -> CopyPlanItem:
    target = raw_dir / photo_bucket(source) / source.name
    if not target.exists():
        return CopyPlanItem(source, target, "copy")

    if target.stat().st_size == source.stat().st_size and sha256_file(target) == sha256_file(source):
        return CopyPlanItem(source, target, "skip", "same file already exists")

    stem = source.stem
    suffix = source.suffix
    for index in range(1, 10_000):
        candidate = raw_dir / f"{stem}_dup{index}{suffix}"
        if not candidate.exists():
            return CopyPlanItem(source, candidate, "copy", f"name conflict: kept both files as {candidate.name}")
    raise RuntimeError(f"Too many duplicate names for {source.name}")


def build_copy_plan(source: Path, raw_dir: Path, only_date: date | None = None) -> list[CopyPlanItem]:
    return [resolve_destination(raw_dir, file_path) for file_path in find_photo_files(source, only_date)]


def ensure_structure(shoot_dir: Path, execute: bool) -> None:
    for relative in SHOOT_DIRS:
        path = shoot_dir / relative
        if execute:
            path.mkdir(parents=True, exist_ok=True)


def write_text(path: Path, content: str, execute: bool) -> None:
    if execute:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def write_text_if_missing(path: Path, content: str, execute: bool) -> None:
    if execute and not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def copy_files(plan: list[CopyPlanItem], execute: bool) -> None:
    if not execute:
        return
    for item in plan:
        if item.action == "copy":
            item.destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item.source, item.destination)


def make_shoot_note(info: ShootInfo) -> str:
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

## 오늘의 촬영 목적
- {info.purpose}

## 오늘의 연습 주제
- {info.practice}

## 컬링 결과 요약
- 아직 컬링 전입니다. `photo-agent cull` 실행 후 `05_NOTES/cull-report.md`를 확인하세요.

## Lightroom 보정 방향
-

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
5. 버릴 컷과 남길 컷 고르기

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
    lines = [
        "# Ingest Log",
        "",
        f"- 실행 시각: {datetime.now().isoformat(timespec='seconds')}",
        f"- 모드: {'execute' if execute else 'dry-run'}",
        f"- 원본 경로: `{source}`",
        f"- 촬영 폴더: `{shoot_dir}`",
        f"- 날짜 필터: `{only_date.isoformat() if only_date else '없음'}`",
        f"- 복사 예정/완료: {copied}",
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


def load_image_for_analysis(path: Path) -> Image.Image:
    suffix = path.suffix.lower()
    if suffix in RAW_EXTENSIONS:
        if rawpy is None:
            raise RuntimeError("RAW preview requires optional dependency: rawpy")
        with rawpy.imread(str(path)) as raw:
            array = raw.postprocess(use_camera_wb=True, half_size=True, no_auto_bright=True)
        return Image.fromarray(array)
    return Image.open(path).convert("RGB")


def compute_blur_score(image: Image.Image) -> float:
    gray = image.convert("L")
    gray.thumbnail((1600, 1600))
    if cv2 is not None and np is not None:
        array = np.array(gray)
        return float(cv2.Laplacian(array, cv2.CV_64F).var())
    edges = gray.filter(ImageFilter.FIND_EDGES)
    return float(ImageStat.Stat(edges).var[0])


def compute_exposure(image: Image.Image) -> tuple[float, float, float]:
    gray = image.convert("L")
    gray.thumbnail((1600, 1600))
    values = list(gray.getdata())
    total = len(values) or 1
    brightness = mean(values)
    shadow_clip = sum(1 for value in values if value <= 5) / total * 100
    highlight_clip = sum(1 for value in values if value >= 250) / total * 100
    return float(brightness), float(shadow_clip), float(highlight_clip)


def compute_contrast_score(image: Image.Image) -> float:
    gray = image.convert("L")
    gray.thumbnail((1600, 1600))
    return float(ImageStat.Stat(gray).stddev[0])


def compute_noise_score(image: Image.Image) -> float:
    gray = image.convert("L")
    gray.thumbnail((1600, 1600))
    if cv2 is not None and np is not None:
        array = np.array(gray, dtype=np.float32)
        kernel = np.array([[1, -2, 1], [-2, 4, -2], [1, -2, 1]], dtype=np.float32)
        filtered = cv2.filter2D(array, -1, kernel)
        return float(np.mean(np.abs(filtered)))
    edges = gray.filter(ImageFilter.FIND_EDGES)
    return float(ImageStat.Stat(edges).mean[0])


def compute_dhash(image: Image.Image, hash_size: int = 8) -> int:
    gray = image.convert("L").resize((hash_size + 1, hash_size), Image.Resampling.LANCZOS)
    pixels = list(gray.getdata())
    result = 0
    for row in range(hash_size):
        for col in range(hash_size):
            left = pixels[row * (hash_size + 1) + col]
            right = pixels[row * (hash_size + 1) + col + 1]
            result = (result << 1) | int(left > right)
    return result


def hamming_distance(left: int, right: int) -> int:
    return bin(left ^ right).count("1")


def detect_faces(image: Image.Image) -> tuple[int | None, list[str]]:
    if cv2 is None or np is None:
        return None, ["OpenCV face detector unavailable"]
    cascade_path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
    detector = cv2.CascadeClassifier(str(cascade_path))
    if detector.empty():
        return None, ["OpenCV face cascade unavailable"]
    resized = image.convert("RGB")
    resized.thumbnail((1800, 1800))
    array = cv2.cvtColor(np.array(resized), cv2.COLOR_RGB2GRAY)
    faces = detector.detectMultiScale(array, scaleFactor=1.1, minNeighbors=5, minSize=(24, 24))
    notes: list[str] = []
    width, height = resized.size
    for x, y, w, h in faces:
        face_area = (w * h) / max(width * height, 1)
        near_edge = x < 4 or y < 4 or x + w > width - 4 or y + h > height - 4
        if face_area < 0.01:
            notes.append("face is very small")
        if near_edge:
            notes.append("face may be clipped by frame edge")
    return int(len(faces)), notes


def analyze_one(path: Path) -> ImageAnalysis:
    try:
        with load_image_for_analysis(path) as image:
            width, height = image.size
            blur = compute_blur_score(image.copy())
            brightness, shadow_clip, highlight_clip = compute_exposure(image.copy())
            contrast = compute_contrast_score(image.copy())
            noise = compute_noise_score(image.copy())
            dhash = compute_dhash(image.copy())
            faces, face_notes = detect_faces(image.copy())
            quality = compute_quality_score(blur, brightness, shadow_clip, highlight_clip, contrast, noise, face_notes)
            return ImageAnalysis(
                path=path,
                ok=True,
                reason="",
                blur_score=blur,
                brightness=brightness,
                shadow_clip_pct=shadow_clip,
                highlight_clip_pct=highlight_clip,
                contrast_score=contrast,
                noise_score=noise,
                quality_score=quality,
                dhash=dhash,
                width=width,
                height=height,
                faces=faces,
                face_notes=face_notes,
            )
    except Exception as exc:
        return ImageAnalysis(path=path, ok=False, reason=str(exc))


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(value, high))


def compute_quality_score(
    blur: float | None,
    brightness: float | None,
    shadow_clip: float | None,
    highlight_clip: float | None,
    contrast: float | None,
    noise: float | None,
    face_notes: list[str] | None,
) -> float:
    sharpness_score = clamp((blur or 0) / 260)
    exposure_score = 1 - clamp(abs((brightness or 128) - 128) / 115)
    clipping_score = 1 - clamp(((shadow_clip or 0) / 35 + (highlight_clip or 0) / 20) / 2)
    contrast_score = clamp((contrast or 0) / 65)
    noise_score = 1 - clamp((noise or 0) / 42)
    face_penalty = 0.06 if face_notes and any("clipped" in note for note in face_notes) else 0
    small_face_penalty = 0.03 if face_notes and any("small" in note for note in face_notes) else 0
    return clamp(
        sharpness_score * 0.38
        + exposure_score * 0.24
        + clipping_score * 0.16
        + contrast_score * 0.12
        + noise_score * 0.10
        - face_penalty
        - small_face_penalty
    )


def reject_reasons(
    result: ImageAnalysis,
    blur_threshold: float,
    dark_threshold: float,
    bright_threshold: float,
    quality_threshold: float,
) -> list[str]:
    reasons: list[str] = []
    if not result.ok:
        return reasons
    if result.blur_score is not None and result.blur_score < blur_threshold:
        reasons.append(f"흔들림/초점 의심: blur score {result.blur_score:.1f} < {blur_threshold:.0f}")
    if result.brightness is not None and result.brightness < dark_threshold:
        reasons.append(f"너무 어두움: 평균 밝기 {result.brightness:.1f} < {dark_threshold:.0f}")
    if result.brightness is not None and result.brightness > bright_threshold:
        reasons.append(f"너무 밝음: 평균 밝기 {result.brightness:.1f} > {bright_threshold:.0f}")
    if result.highlight_clip_pct is not None and result.highlight_clip_pct > 20:
        reasons.append(f"하이라이트 날아감 의심: {result.highlight_clip_pct:.1f}%")
    if result.shadow_clip_pct is not None and result.shadow_clip_pct > 35:
        reasons.append(f"암부 뭉침 의심: {result.shadow_clip_pct:.1f}%")
    if result.noise_score is not None and result.noise_score > 34:
        reasons.append(f"노이즈/거친 디테일 의심: noise score {result.noise_score:.1f}")
    if result.contrast_score is not None and result.contrast_score < 12:
        reasons.append(f"대비가 낮아 밋밋하거나 흐릿할 가능성: contrast {result.contrast_score:.1f}")
    if result.face_notes:
        for note in result.face_notes:
            if "clipped" in note:
                reasons.append("얼굴이 프레임에 잘렸을 가능성")
    if result.quality_score is not None and result.quality_score < quality_threshold:
        reasons.append(f"종합 품질 점수 낮음: {result.quality_score:.2f} < {quality_threshold:.2f}")
    return reasons


def keeper_reasons(result: ImageAnalysis) -> list[str]:
    reasons: list[str] = []
    if not result.ok:
        return reasons
    if result.blur_score is not None:
        reasons.append(f"상대적으로 선명함: blur score {result.blur_score:.1f}")
    if result.brightness is not None:
        reasons.append(f"노출이 무난함: 평균 밝기 {result.brightness:.1f}")
    if (result.shadow_clip_pct or 0) < 10 and (result.highlight_clip_pct or 0) < 10:
        reasons.append("암부/하이라이트 클리핑이 낮음")
    if result.faces:
        reasons.append(f"얼굴 감지됨: {result.faces}명")
    if result.contrast_score is not None:
        reasons.append(f"대비 점수: {result.contrast_score:.1f}")
    if result.noise_score is not None:
        reasons.append(f"노이즈 점수: {result.noise_score:.1f}")
    reasons.append(f"종합 품질 점수 {score_keeper(result):.2f}")
    return reasons


def group_duplicates(results: list[ImageAnalysis], max_distance: int) -> list[list[ImageAnalysis]]:
    remaining = [result for result in results if result.ok and result.dhash is not None]
    groups: list[list[ImageAnalysis]] = []
    used: set[Path] = set()
    for result in remaining:
        if result.path in used:
            continue
        group = [result]
        used.add(result.path)
        for other in remaining:
            if other.path in used or other.path == result.path:
                continue
            brightness_gap = abs((result.brightness or 0) - (other.brightness or 0))
            if hamming_distance(result.dhash or 0, other.dhash or 0) <= max_distance and brightness_gap <= 30:
                group.append(other)
                used.add(other.path)
        if len(group) > 1:
            groups.append(group)
    return groups


def is_reject_candidate(
    result: ImageAnalysis,
    blur_threshold: float,
    dark_threshold: float,
    bright_threshold: float,
    quality_threshold: float,
) -> bool:
    return bool(reject_reasons(result, blur_threshold, dark_threshold, bright_threshold, quality_threshold))


def score_keeper(result: ImageAnalysis) -> float:
    if not result.ok:
        return -1
    return result.quality_score if result.quality_score is not None else 0


def safe_link_or_copy(source: Path, target_dir: Path, mode: str, execute: bool) -> None:
    if mode == "none" or not execute:
        return
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / source.name
    if target.exists():
        return
    if mode == "copy":
        shutil.copy2(source, target)
    else:
        os.symlink(source, target)


def clear_review_dir(target_dir: Path, execute: bool) -> None:
    if not execute or not target_dir.exists():
        return
    for path in target_dir.iterdir():
        if path.is_file() or path.is_symlink():
            path.unlink()


def make_cull_report(
    raw_dir: Path,
    results: list[ImageAnalysis],
    duplicate_groups: list[list[ImageAnalysis]],
    rejects: list[ImageAnalysis],
    keepers: list[ImageAnalysis],
    review_mode: str,
    execute: bool,
    blur_threshold: float,
    dark_threshold: float,
    bright_threshold: float,
    quality_threshold: float,
) -> str:
    failed = [result for result in results if not result.ok]
    blur_candidates = [result for result in rejects if result.blur_score is not None and result.blur_score < 100]
    exposure_candidates = [
        result
        for result in rejects
        if (result.brightness is not None and (result.brightness < 45 or result.brightness > 215))
        or (result.highlight_clip_pct is not None and result.highlight_clip_pct > 20)
        or (result.shadow_clip_pct is not None and result.shadow_clip_pct > 35)
    ]
    lines = [
        "# Cull Report",
        "",
        f"- 분석 시각: {datetime.now().isoformat(timespec='seconds')}",
        f"- 모드: {'execute' if execute else 'dry-run'}",
        f"- 분석 폴더: `{raw_dir}`",
        f"- 전체 파일 수: {len(results)}",
        f"- 분석 성공: {len(results) - len(failed)}",
        f"- 분석 실패/건너뜀: {len(failed)}",
        f"- 리뷰 후보 생성 방식: {review_mode}",
        f"- 컬링 엔진: CullSnap-inspired local scoring v2",
        f"- 종합 품질 reject 기준: {quality_threshold:.2f}",
        "",
        "## 점수 기준",
        "- 종합 품질 점수는 선명도, 노출, 클리핑, 대비, 노이즈, 얼굴 잘림 가능성을 합산합니다.",
        "- Select 후보는 기술 점수가 상대적으로 높은 컷입니다.",
        "- Reject 후보는 삭제 대상이 아니라 사람이 우선 확인할 실패 가능성 후보입니다.",
        "",
        "## 흔들림/초점 실패 후보",
    ]
    lines.extend(format_result_list(blur_candidates))
    lines.extend(["", "## 노출 실패 후보"])
    lines.extend(format_result_list(exposure_candidates))
    lines.extend(["", "## 중복/연사 유사 그룹"])
    if duplicate_groups:
        for index, group in enumerate(duplicate_groups, start=1):
            best = max(group, key=score_keeper)
            lines.append(f"### 그룹 {index} / 대표 추천: `{best.path.name}`")
            for item in group:
                lines.append(
                    f"- `{item.path.name}` score={score_keeper(item):.2f} "
                    f"blur={item.blur_score:.1f} brightness={item.brightness:.1f}"
                )
    else:
        lines.append("- 없음")
    lines.extend(["", "## Select 후보와 이유"])
    if keepers:
        for item in keepers:
            lines.append(f"- `{item.path.name}`")
            for reason in keeper_reasons(item):
                lines.append(f"  - 이유: {reason}")
    else:
        lines.append("- 없음")
    lines.extend(["", "## Reject 후보와 이유"])
    if rejects:
        for item in rejects:
            lines.append(f"- `{item.path.name}`")
            for reason in reject_reasons(item, blur_threshold, dark_threshold, bright_threshold, quality_threshold):
                lines.append(f"  - 이유: {reason}")
    else:
        lines.append("- 없음")
    lines.extend(["", "## 사람이 최종 확인해야 할 컷"])
    review_set = {item.path for item in rejects}
    for group in duplicate_groups:
        for item in group:
            review_set.add(item.path)
    if review_set:
        for path in sorted(review_set):
            lines.append(f"- `{path.name}`")
    else:
        lines.append("- 없음")
    lines.extend(["", "## Lightroom 확인 메모"])
    lines.append("- 이 리포트는 삭제 판단이 아니라 1차 검토용입니다.")
    lines.append("- `reject-candidates`는 실패 가능성이 있는 컷 모음이고, 최종 삭제 후보가 아닙니다.")
    lines.append("- `keeper-candidates`는 기술 점수가 상대적으로 좋은 컷입니다. 감성 판단은 직접 확인하세요.")
    if failed:
        lines.extend(["", "## 분석 실패/건너뜀"])
        for item in failed:
            lines.append(f"- `{item.path.name}`: {item.reason}")
    return "\n".join(lines) + "\n"


def format_result_list(items: Iterable[ImageAnalysis]) -> list[str]:
    items = list(items)
    if not items:
        return ["- 없음"]
    lines = []
    for item in items:
        face = "" if item.faces is None else f" faces={item.faces}"
        notes = "" if not item.face_notes else f" notes={', '.join(item.face_notes)}"
        lines.append(
            f"- `{item.path.name}` score={score_keeper(item):.2f} blur={item.blur_score:.1f} "
            f"brightness={item.brightness:.1f} shadow={item.shadow_clip_pct:.1f}% "
            f"highlight={item.highlight_clip_pct:.1f}% contrast={item.contrast_score:.1f} "
            f"noise={item.noise_score:.1f}{face}{notes}"
        )
    return lines


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
    raw_dir = shoot_dir / "00_RAW"
    execute = args.execute

    ensure_structure(shoot_dir, execute)
    plan = build_copy_plan(source, raw_dir, only_date)

    print_plan(shoot_dir, plan, execute, args.plan_limit)
    write_text(shoot_dir / "shoot-note.md", make_shoot_note(info), execute)
    write_text(shoot_dir / "04_SNS/instagram-caption.md", make_caption(info), execute)
    write_text(shoot_dir / "05_NOTES/ingest-log.md", make_ingest_log(info, source, shoot_dir, plan, execute, only_date), execute)
    write_text_if_missing(
        shoot_dir / "05_NOTES/cull-report.md",
        "# Cull Report\n\n- 아직 컬링 전입니다. `photo-agent cull` 명령을 실행하세요.\n",
        execute,
    )
    copy_files(plan, execute)

    if execute and args.open_finder:
        open_in_finder(shoot_dir)

    if execute and args.run_cull:
        cull_args = argparse.Namespace(
            shoot_dir=str(shoot_dir),
            raw_dir=None,
            execute=True,
            review_mode=args.review_mode,
            duplicate_distance=args.duplicate_distance,
            blur_threshold=args.blur_threshold,
            dark_threshold=args.dark_threshold,
            bright_threshold=args.bright_threshold,
            quality_threshold=args.quality_threshold,
            keeper_count=args.keeper_count,
        )
        run_cull(cull_args)

    return 0


def run_inspect(args: argparse.Namespace) -> int:
    source = Path(args.source).expanduser().resolve()
    only_date = date.fromisoformat(args.only_date) if args.only_date else None
    camera, lens = infer_camera_lens(source, only_date)
    print(f"camera={camera}")
    print(f"lens={lens}")
    return 0


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


def run_cull(args: argparse.Namespace) -> int:
    shoot_dir = Path(args.shoot_dir).expanduser().resolve() if args.shoot_dir else None
    raw_dir = Path(args.raw_dir).expanduser().resolve() if args.raw_dir else default_analysis_dir(shoot_dir)
    if raw_dir is None or not raw_dir.exists():
        raise SystemExit(f"RAW folder does not exist: {raw_dir}")
    if shoot_dir is None:
        shoot_dir = raw_dir.parent

    files = find_photo_files(raw_dir)
    print(f"Mode: {'EXECUTE' if args.execute else 'DRY-RUN'}")
    print(f"Analyzing {len(files)} files in {raw_dir}")
    results = [analyze_one(path) for path in files]
    duplicates = group_duplicates(results, args.duplicate_distance)
    rejects = [
        result
        for result in results
        if is_reject_candidate(
            result,
            args.blur_threshold,
            args.dark_threshold,
            args.bright_threshold,
            args.quality_threshold,
        )
    ]
    keeper_pool = [result for result in results if result.ok and result.path not in {reject.path for reject in rejects}]
    keepers = sorted(keeper_pool, key=score_keeper, reverse=True)[: args.keeper_count]

    reject_dir = shoot_dir / "01_CULL_REVIEW/reject-candidates"
    keeper_dir = shoot_dir / "01_CULL_REVIEW/keeper-candidates"
    clear_review_dir(reject_dir, args.execute)
    clear_review_dir(keeper_dir, args.execute)
    for item in rejects:
        safe_link_or_copy(item.path, reject_dir, args.review_mode, args.execute)
    for item in keepers:
        safe_link_or_copy(item.path, keeper_dir, args.review_mode, args.execute)

    report = make_cull_report(
        raw_dir,
        results,
        duplicates,
        rejects,
        keepers,
        args.review_mode,
        args.execute,
        args.blur_threshold,
        args.dark_threshold,
        args.bright_threshold,
        args.quality_threshold,
    )
    report_path = shoot_dir / "05_NOTES/cull-report.md"
    write_text(report_path, report, args.execute)
    print(f"Reject candidates: {len(rejects)}")
    print(f"Keeper candidates: {len(keepers)}")
    print(f"Duplicate groups: {len(duplicates)}")
    print(f"Report: {report_path}")
    if not args.execute:
        print("\nNo review links/copies or report were written. Re-run with --execute to apply.")
    return 0


def default_analysis_dir(shoot_dir: Path | None) -> Path | None:
    if shoot_dir is None:
        return None
    jpg_dir = shoot_dir / "00_RAW" / "JPG"
    if jpg_dir.exists():
        return jpg_dir
    return shoot_dir / "00_RAW"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="photo-agent",
        description="Local photo ingest, culling report, and SNS prep assistant.",
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
    ingest.add_argument("--run-cull", action="store_true", help="Run culling after ingest. Requires --execute.")
    ingest.add_argument("--plan-limit", type=int, default=80, help="Maximum file plan lines to print. Use 0 to show all.")
    add_cull_options(ingest)
    ingest.set_defaults(func=run_ingest)

    cull = subparsers.add_parser("cull", help="Analyze copied photos and write a culling report.")
    cull.add_argument("--shoot-dir", default="", help="Shoot folder containing 00_RAW.")
    cull.add_argument("--raw-dir", default="", help="RAW folder. If omitted, uses SHOOT_DIR/00_RAW.")
    cull.add_argument("--execute", action="store_true", help="Write report and create review links/copies. Default is dry-run.")
    add_cull_options(cull)
    cull.set_defaults(func=run_cull)

    inspect = subparsers.add_parser("inspect", help="Inspect source photos and print simple metadata defaults.")
    inspect.add_argument("--source", required=True, help="Memory card or source folder path.")
    inspect.add_argument("--only-date", default="", help="Only inspect files whose modified date is YYYY-MM-DD.")
    inspect.set_defaults(func=run_inspect)

    return parser


def add_cull_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--review-mode",
        choices=["symlink", "copy", "none"],
        default="symlink",
        help="How to collect reject/keeper candidates. Default: symlink.",
    )
    parser.add_argument("--duplicate-distance", type=int, default=6, help="dHash Hamming distance for similar groups.")
    parser.add_argument("--blur-threshold", type=float, default=55.0, help="Lower blur score is more likely blurry.")
    parser.add_argument("--dark-threshold", type=float, default=45.0, help="Mean brightness below this is dark candidate.")
    parser.add_argument("--bright-threshold", type=float, default=215.0, help="Mean brightness above this is bright candidate.")
    parser.add_argument("--quality-threshold", type=float, default=0.38, help="Composite quality score below this is reject candidate.")
    parser.add_argument("--keeper-count", type=int, default=30, help="Maximum keeper candidates to collect.")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    raise SystemExit(args.func(args))
